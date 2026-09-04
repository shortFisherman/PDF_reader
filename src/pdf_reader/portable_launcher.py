"""Top-level Windows portable launcher; keeps the real user environment intact."""

from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from pdf_reader import paths
from pdf_reader.portable_runtime import (
    HEALTH_TOKEN_ENV,
    READY_FILE_ENV,
    build_service_environment,
    new_health_token,
    new_readiness_file,
)

EXIT_LAUNCHER_ERROR = 2
EXIT_SERVICE_START_FAILED = 3
EXIT_INTERRUPTED = 130


class PortableLaunchError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _service_executable(layout: paths.RuntimeLayout) -> Path:
    candidate = layout.resource_root / "PDF Reader Service.exe"
    resolved = candidate.resolve(strict=False)
    if resolved.parent != layout.resource_root.resolve(strict=False):
        raise PortableLaunchError("服务程序路径逃逸 app 目录", code="service_path_invalid")
    return resolved


def _readiness_endpoint(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ValueError("invalid readiness schema")
    host = payload.get("host")
    port = payload.get("port")
    if not isinstance(host, str) or not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("invalid readiness endpoint")
    normalized = host.strip().lower()
    if normalized == "localhost":
        display_host = "localhost"
    else:
        address = ipaddress.ip_address(normalized)
        if not address.is_loopback:
            raise ValueError("readiness endpoint is not loopback")
        display_host = f"[{normalized}]" if address.version == 6 else normalized
    token = payload.get("health_token")
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("invalid readiness health token")
    return f"http://{display_host}:{port}/", token


def wait_until_ready(
    process: subprocess.Popen[Any],
    readiness_file: Path,
    *,
    timeout: float,
) -> str:
    deadline = time.monotonic() + timeout
    last_error = "service did not publish readiness metadata"
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise PortableLaunchError(
                f"服务在就绪前退出（exit={return_code}）",
                code="service_exited_before_ready",
            )
        try:
            payload = json.loads(readiness_file.read_text(encoding="utf-8"))
            url, health_token = _readiness_endpoint(payload)
            request = urllib.request.Request(
                f"{url}api/health",
                headers={"X-PDF-Reader-Health-Token": health_token},
            )
            with urllib.request.urlopen(request, timeout=min(1.0, max(0.1, timeout))) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and response_payload == {"status": "ok"}:
                    return url
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.05)
    raise PortableLaunchError(
        f"等待本地服务就绪超时：{last_error}",
        code="service_start_timeout",
    )


def _stop_process(process: subprocess.Popen[Any], *, timeout: float = 10.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


def run_portable_launcher(
    launcher_executable: str | Path,
    *,
    startup_timeout: float = 30.0,
    open_browser: bool = True,
) -> int:
    """Run the private service and open the browser from the untouched parent env."""

    process: subprocess.Popen[Any] | None = None
    readiness_file: Path | None = None
    startup_complete = False
    try:
        layout = paths.RuntimeLayout.portable_from_executable(launcher_executable)
        paths.prepare_runtime_layout(layout)
        service_executable = _service_executable(layout)
        if not service_executable.is_file():
            raise PortableLaunchError(
                f"缺少便携服务程序：{service_executable}",
                code="service_executable_missing",
            )
        readiness_file = new_readiness_file(layout)
        child_environment = build_service_environment(layout)
        child_environment[READY_FILE_ENV] = str(readiness_file)
        child_environment[HEALTH_TOKEN_ENV] = new_health_token()
        command = [str(service_executable), "--launcher-executable", str(Path(launcher_executable).resolve())]
        process = subprocess.Popen(command, cwd=str(layout.portable_root), env=child_environment)
        url = wait_until_ready(process, readiness_file, timeout=startup_timeout)
        startup_complete = True
        if open_browser:
            webbrowser.open(url)
        return process.wait()
    except KeyboardInterrupt:
        if process is not None:
            _stop_process(process)
        return EXIT_INTERRUPTED
    except (OSError, paths.PathStrategyError, PortableLaunchError) as exc:
        if process is not None:
            _stop_process(process)
        code = getattr(exc, "code", "portable_launcher_failed")
        print(f"ERROR [{code}]: {exc}", file=sys.stderr)
        return EXIT_SERVICE_START_FAILED if process is not None and not startup_complete else EXIT_LAUNCHER_ERROR
    finally:
        if readiness_file is not None:
            try:
                readiness_file.unlink()
            except FileNotFoundError:
                pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="PDF Reader.exe")
    parser.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--startup-timeout", type=float, default=30.0, help=argparse.SUPPRESS)
    parser.add_argument("--launcher-executable", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    executable = (
        Path(args.launcher_executable).resolve() if args.launcher_executable else Path(sys.executable).resolve()
    )
    return run_portable_launcher(
        executable,
        startup_timeout=max(0.1, args.startup_timeout),
        open_browser=not args.no_browser,
    )


if __name__ == "__main__":
    raise SystemExit(main())
