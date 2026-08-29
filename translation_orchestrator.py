import asyncio
import logging
import queue
import threading

from pdf2zh_next import SettingsModel, do_translate_async_stream

from task_logging import (
    STATUS_CANCELLING,
    STATUS_CLEANUP_DEFERRED,
    TaskContext,
    set_current_task,
    task_log,
    with_status,
)

logger = logging.getLogger("pdf_reader.translate")

WORKER_JOIN_TIMEOUT = 30.0
QUEUE_POLL_TIMEOUT = 1.0


class TranslationError(Exception):
    pass


class TranslationStream:
    """Iterator over upstream translation events, backed by a dedicated worker thread.

    The worker thread pushes events into a queue and always terminates by
    enqueueing an internal ``_done`` marker, so ``__next__`` can distinguish
    "no event right now" (heartbeat) from "worker finished".  Cancellation is
    cooperative: ``cancel()`` asks the worker to stop at the next event
    boundary; upstream work that does not check the boundary is allowed to
    finish and its events are discarded.

    The consumer owns the worker: exhaust the stream to completion (``__next__``
    joins the thread deterministically) or call ``cancel()`` / ``join()`` when
    abandoning it early.  Temp directories may only be removed after the worker
    has actually exited (``is_alive`` is False).
    """

    def __init__(
        self,
        settings: SettingsModel,
        pdf_path: str,
        flow_label: str = "",
        task_ctx: TaskContext | None = None,
    ) -> None:
        self._settings = settings
        self._pdf_path = pdf_path
        self._flow_label = flow_label
        self._task_ctx = task_ctx
        self._queue: queue.Queue = queue.Queue()
        self._error_info: str | None = None
        self._cancel_event = threading.Event()
        self._late_result_dropped = False
        self._thread = threading.Thread(
            target=self._thread_main,
            daemon=True,
            name=f"translate-{flow_label or 'worker'}",
        )
        self._thread.start()
        task_log(logger, logging.INFO, "thread start", task=self._task_ctx)

    def _thread_main(self) -> None:
        set_current_task(self._task_ctx)
        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def _run() -> None:
                async for evt in do_translate_async_stream(self._settings, self._pdf_path):
                    if self._cancel_event.is_set():
                        self._late_result_dropped = True
                        task_log(
                            logger,
                            logging.INFO,
                            "thread cancelled; late worker event dropped",
                            task=with_status(self._task_ctx, STATUS_CANCELLING),
                        )
                        break
                    self._queue.put(evt)

            loop.run_until_complete(_run())
        except Exception as e:
            task_log(
                logger,
                logging.ERROR,
                "thread exception",
                task=self._task_ctx,
                exc_info=True,
            )
            self._error_info = str(e)
        finally:
            if loop is not None:
                try:
                    pending = asyncio.all_tasks(loop)
                    if pending:
                        for task in pending:
                            task.cancel()
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
                loop.close()
            self._queue.put({"type": "_done"})

    def cancel(self) -> None:
        """Request cooperative cancellation; the worker stops at the next event boundary."""
        self._cancel_event.set()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    @property
    def late_result_dropped(self) -> bool:
        """取消后是否丢弃过迟到 worker 事件（供清理阶段记录 discarded）。"""
        return self._late_result_dropped

    def __iter__(self) -> "TranslationStream":
        return self

    def __next__(self) -> dict | str:
        while True:
            try:
                evt = self._queue.get(timeout=QUEUE_POLL_TIMEOUT)
            except queue.Empty:
                return ""
            if evt.get("type") == "_done":
                break
            return evt
        self._thread.join(timeout=WORKER_JOIN_TIMEOUT)
        if self._thread.is_alive():
            task_log(
                logger,
                logging.WARNING,
                "thread join timeout",
                task=with_status(self._task_ctx, STATUS_CLEANUP_DEFERRED),
            )
        else:
            task_log(logger, logging.INFO, "thread end", task=self._task_ctx)
        if self._error_info:
            raise TranslationError(self._error_info)
        raise StopIteration


def run_translation(
    settings: SettingsModel,
    pdf_path: str,
    flow_label: str = "",
    task_ctx: TaskContext | None = None,
) -> TranslationStream:
    """Start a background translation worker and return its event stream.

    The caller owns the worker: exhaust the stream to completion, or call
    ``cancel()`` / ``join()`` explicitly when abandoning it early.
    """
    return TranslationStream(settings, pdf_path, flow_label, task_ctx)
