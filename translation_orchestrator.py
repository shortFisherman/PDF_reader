import asyncio
import logging
import queue
import threading
from collections.abc import Iterator

from pdf2zh_next import SettingsModel, do_translate_async_stream

logger = logging.getLogger("pdf_reader.translate")


class TranslationError(Exception):
    pass


def run_translation(settings: SettingsModel, pdf_path: str, flow_label: str = "") -> Iterator[dict | str]:
    event_queue: queue.Queue = queue.Queue()
    error_info: str | None = None

    def run_translation_thread() -> None:
        nonlocal error_info
        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def _run() -> bool:
                async for evt in do_translate_async_stream(settings, pdf_path):
                    event_queue.put(evt)
                return True

            loop.run_until_complete(_run())
        except Exception as e:
            logger.error("[%s] thread exception", flow_label, exc_info=True)
            error_info = str(e)
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
            event_queue.put({"type": "_done"})

    thread = threading.Thread(target=run_translation_thread, daemon=True)
    thread.start()
    logger.info("[%s] thread start", flow_label)

    while True:
        try:
            evt = event_queue.get(timeout=1.0)
        except queue.Empty:
            yield ""
            continue

        if evt.get("type") == "_done":
            break

        yield evt

    logger.info("[%s] thread end", flow_label)
    thread.join(timeout=5.0)
    if thread.is_alive():
        logger.warning("[%s] thread join timeout", flow_label)

    if error_info:
        raise TranslationError(error_info)
