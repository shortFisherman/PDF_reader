"""Frozen service bootstrap that establishes portable state before app imports."""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from pdf_reader import paths
from pdf_reader.portable_runtime import (
    PortableEnvironmentError,
    readiness_file_from_environment,
    validate_private_frozen_runtime,
    validate_service_environment,
    write_readiness_failure,
)


class PortableServiceError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def bootstrap_portable_service(
    launcher_executable: str | Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> paths.RuntimeLayout:
    """Validate/install the layout without importing application or upstream code."""

    layout = paths.RuntimeLayout.portable_from_executable(launcher_executable)
    try:
        validate_service_environment(layout, environment)
        validate_private_frozen_runtime(layout)
        paths.prepare_runtime_layout(layout)
        paths.install_runtime_layout(layout)
    except PortableEnvironmentError as exc:
        raise PortableServiceError(str(exc), code=exc.code) from exc
    return layout


def _load_app_main() -> Callable[[list[str] | None], int]:
    module = importlib.import_module("pdf_reader.app")
    return cast(Callable[[list[str] | None], int], module.main)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="PDF Reader Service.exe")
    parser.add_argument("--launcher-executable", required=True)
    parser.add_argument("service_args", nargs=argparse.REMAINDER)
    return parser


def _publish_bootstrap_failure(launcher_executable: str | Path, *, code: str, message: str) -> None:
    """把启动失败的稳定错误码写进就绪文件，让启动器不必靠超时猜测原因。

    这里运行在失败路径上：任何二次失败都必须被吞掉，只保留原始错误码与 stderr。
    """

    try:
        layout = paths.RuntimeLayout.portable_from_executable(launcher_executable)
        readiness_file = readiness_file_from_environment(layout)
        if readiness_file is None:
            return
        write_readiness_failure(layout, readiness_file, code=code, message=message)
    except Exception:  # noqa: BLE001 - 失败路径不能因为诊断本身失败而改变退出行为
        return


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        bootstrap_portable_service(args.launcher_executable)
    except (PortableServiceError, paths.PathStrategyError, OSError) as exc:
        code = getattr(exc, "code", "portable_service_bootstrap_failed")
        _publish_bootstrap_failure(args.launcher_executable, code=code, message=str(exc))
        print(f"ERROR [{code}]: {exc}", file=sys.stderr)
        return 2
    app_main = _load_app_main()
    return app_main(list(args.service_args))


if __name__ == "__main__":
    raise SystemExit(main())
