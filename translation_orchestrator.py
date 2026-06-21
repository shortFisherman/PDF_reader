import asyncio
import queue
import threading

from pdf2zh_next import do_translate_async_stream


class TranslationError(Exception):
    pass


def run_translation(settings, pdf_path: str):
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
            error_info = str(e)
        finally:
            if loop is not None:
                try:
                    pending = asyncio.all_tasks(loop)
                    if pending:
                        for task in pending:
                            task.cancel()
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                except Exception:
                    pass
                loop.close()
            event_queue.put({"type": "_done"})

    thread = threading.Thread(target=run_translation_thread, daemon=True)
    thread.start()

    while True:
        try:
            evt = event_queue.get(timeout=1.0)
        except queue.Empty:
            yield ""
            continue

        if evt.get("type") == "_done":
            break

        yield evt

    thread.join(timeout=5.0)

    if error_info:
        raise TranslationError(error_info)
