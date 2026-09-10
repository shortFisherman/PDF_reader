"""P1-02 便携发行测试的公共夹具。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _reset_portable_launcher_logging() -> Iterator[None]:
    """每个测试后关闭启动器自己的日志 handler，避免文件句柄与目录跨测试泄漏。"""

    yield
    from pdf_reader import portable_launcher

    portable_launcher.reset_launcher_logging()
