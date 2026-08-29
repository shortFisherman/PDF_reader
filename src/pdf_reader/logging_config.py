import logging
import sys
from logging.handlers import RotatingFileHandler

from pdf_reader import paths
from pdf_reader.task_logging import SafeFormatter

LOG_DIR = paths.get_log_dir()


def setup_logging(debug: bool = False) -> None:
    root_pdf = logging.getLogger("pdf_reader")

    # 幂等：若已有 handler 则不重复添加
    if root_pdf.handlers:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = SafeFormatter("%(asctime)s %(levelname)s %(name)s [%(message)s]")

    level = logging.DEBUG if debug else logging.INFO

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root_pdf.addHandler(console)

    file_handler = RotatingFileHandler(
        str(LOG_DIR / "pdf_reader.log"),
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_pdf.addHandler(file_handler)

    root_pdf.setLevel(level)

    # 第三方 logger：debug off 时抬到 WARNING 屏蔽其 INFO 噪音；debug on 时降到 DEBUG 放行细节
    third_party_level = logging.DEBUG if debug else logging.WARNING
    for name in ("werkzeug", "pdf2zh_next", "babeldoc"):
        logging.getLogger(name).setLevel(third_party_level)


def reset_logging() -> None:
    """关闭并移除 pdf_reader 根 logger 的全部 handler（测试隔离用）。"""
    root_pdf = logging.getLogger("pdf_reader")
    for handler in list(root_pdf.handlers):
        root_pdf.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
