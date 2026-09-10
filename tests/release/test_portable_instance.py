"""P1-02 单实例所有权与实例记录：内核锁、记录校验、令牌认证控制通道。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from pdf_reader import paths, portable_instance, portable_runtime
from tests.release import portable_harness as h

REPO_ROOT = Path(__file__).resolve().parents[2]

LOCK_HOLDER_SCRIPT = textwrap.dedent(
    """
    import sys
    import time
    from pathlib import Path

    from pdf_reader.portable_instance import PosixFileLock

    lock = PosixFileLock(Path(sys.argv[1]))
    if not lock.acquire():
        print("denied", flush=True)
        raise SystemExit(1)
    print("locked", flush=True)
    time.sleep(float(sys.argv[2]))
    lock.release()
    """
)

LOCK_EXIT_SCRIPT = textwrap.dedent(
    """
    import sys
    from pathlib import Path

    from pdf_reader.portable_instance import PosixFileLock

    lock = PosixFileLock(Path(sys.argv[1]))
    if not lock.acquire():
        print("denied", flush=True)
        raise SystemExit(1)
    print("locked", flush=True)
    """
)


class FakeKernelApi:
    """假 Windows 内核 API：完整记录互斥体名与句柄生命周期。"""

    def __init__(self, *, handle: int = 7, already_exists: bool = False) -> None:
        self.created: list[str] = []
        self.closed: list[int] = []
        self._handle = handle
        self._already_exists = already_exists

    def create_mutex(self, name: str) -> tuple[int, bool]:
        self.created.append(name)
        return self._handle, self._already_exists

    def close_handle(self, handle: int) -> None:
        self.closed.append(handle)


def _spawn_lock_child(script: str, lock_path: Path, *extra: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", script, str(lock_path), *extra],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _read_first_line(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    return process.stdout.readline().strip()


def _terminate(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


class TestKernelOwnedLock:
    def test_mutex_ownership_is_granted_and_released(self):
        api = FakeKernelApi()
        lock = portable_instance.WindowsMutexLock("Local\\pdf-reader-test", kernel_api=api)

        assert lock.acquire() is True
        assert api.created == ["Local\\pdf-reader-test"]
        assert lock.name == "Local\\pdf-reader-test"

        lock.release()
        assert api.closed == [7]
        lock.release()  # 释放幂等：不会重复关闭句柄
        assert api.closed == [7]

    def test_existing_mutex_means_another_instance_owns_it(self):
        api = FakeKernelApi(already_exists=True)
        lock = portable_instance.WindowsMutexLock("Local\\pdf-reader-test", kernel_api=api)

        assert lock.acquire() is False
        assert api.closed == [7]  # 重复句柄立刻关闭，不泄漏内核对象

    def test_mutex_failure_reports_stable_code(self):
        api = FakeKernelApi(handle=0)
        lock = portable_instance.WindowsMutexLock("Local\\pdf-reader-test", kernel_api=api)

        with pytest.raises(portable_runtime.PortableEnvironmentError) as exc_info:
            lock.acquire()

        assert exc_info.value.code == "instance_lock_unavailable"
        assert api.closed == []

    def test_lock_name_is_stable_private_and_root_specific(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        other = h.make_portable_layout(tmp_path, name="另一个 portable 目录")

        name = portable_runtime.instance_lock_name(layout)

        assert name == portable_runtime.instance_lock_name(layout)
        assert name.startswith("Local\\pdf-reader-portable-")
        assert re.fullmatch(r"Local\\pdf-reader-portable-[0-9a-f]{24}", name)
        assert portable_runtime.instance_lock_name(other) != name
        assert str(tmp_path) not in name

    def test_instance_paths_stay_inside_data_runtime(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)

        assert layout.runtime_dir == layout.data_root / "runtime"
        assert layout.runtime_dir in layout.managed_directories
        assert portable_runtime.instance_lock_path(layout).parent == layout.runtime_dir
        assert portable_runtime.instance_record_path(layout).parent == layout.runtime_dir


@pytest.mark.skipif(sys.platform == "win32", reason="flock 只在 POSIX 上可用")
class TestPosixFileLockAcrossProcesses:
    def test_a_second_process_cannot_acquire_the_same_instance_lock(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        lock_path = portable_runtime.instance_lock_path(layout)
        child = _spawn_lock_child(LOCK_HOLDER_SCRIPT, lock_path, "30")
        try:
            assert _read_first_line(child) == "locked"
            contender = portable_instance.PosixFileLock(lock_path)
            assert contender.acquire() is False
            contender.release()  # 未持有的锁释放必须是无害的
            assert child.poll() is None
        finally:
            _terminate(child)

        assert portable_instance.PosixFileLock(lock_path).acquire() is True

    def test_lock_is_released_when_the_owning_process_dies(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        lock_path = portable_runtime.instance_lock_path(layout)
        child = _spawn_lock_child(LOCK_EXIT_SCRIPT, lock_path)
        assert _read_first_line(child) == "locked"
        assert child.wait(timeout=30) == 0

        lock = portable_instance.PosixFileLock(lock_path)
        assert lock.acquire() is True
        lock.release()

    def test_lock_file_is_owner_only_and_stays_inside_runtime_dir(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        lock_path = portable_runtime.instance_lock_path(layout)

        assert portable_instance.PosixFileLock(lock_path).acquire() is True

        assert lock_path.is_file()
        assert lock_path.parent == layout.runtime_dir
        assert lock_path.stat().st_mode & 0o777 == 0o600


class TestInstanceLockSelection:
    def test_windows_platform_selects_named_mutex(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        api = FakeKernelApi()

        lock = portable_instance.create_instance_lock(layout, kernel_api=api, platform="win32")

        assert isinstance(lock, portable_instance.WindowsMutexLock)
        assert lock.acquire() is True
        assert api.created == [portable_runtime.instance_lock_name(layout)]

    def test_non_windows_platform_selects_file_lock(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)

        lock = portable_instance.create_instance_lock(layout, platform="linux")

        assert isinstance(lock, portable_instance.PosixFileLock)


class TestInstanceRecord:
    def test_record_round_trip_reuses_tokens_but_hides_them_from_repr(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        record = h.make_instance_record(service_port=5100, launcher_port=5101)

        path = portable_instance.write_instance_record(layout, record)
        restored = portable_instance.read_instance_record(layout)

        assert restored == record
        assert path.parent == layout.runtime_dir
        assert path.name == "instance.json"
        assert record.health_token not in repr(record)
        assert record.control_token not in repr(record)
        assert record.service_control_token not in repr(record)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema"] == portable_instance.INSTANCE_RECORD_SCHEMA
        assert payload["service"]["health_token"] == record.health_token

    def test_missing_record_is_absent_not_an_error(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)

        assert portable_instance.read_instance_record(layout) is None

    def test_corrupt_record_is_a_stable_failure_code(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        target = h.instance_record_path(layout)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{ this is not json", encoding="utf-8")

        with pytest.raises(portable_instance.PortableInstanceError) as exc_info:
            portable_instance.read_instance_record(layout)

        assert exc_info.value.code == "instance_record_invalid"

    def test_truncated_record_is_a_stable_failure_code(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        target = h.instance_record_path(layout)
        target.parent.mkdir(parents=True, exist_ok=True)
        full = json.dumps(h.make_instance_record(service_port=5100, launcher_port=5101).to_payload())
        target.write_text(full[: len(full) // 2], encoding="utf-8")

        with pytest.raises(portable_instance.PortableInstanceError) as exc_info:
            portable_instance.read_instance_record(layout)

        assert exc_info.value.code == "instance_record_invalid"

    def test_record_with_wrong_schema_is_a_stable_failure_code(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        target = h.instance_record_path(layout)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"schema": 99}), encoding="utf-8")

        with pytest.raises(portable_instance.PortableInstanceError) as exc_info:
            portable_instance.read_instance_record(layout)

        assert exc_info.value.code == "instance_record_invalid"

    def test_record_rejects_unsafe_or_impossible_values(self):
        with pytest.raises(ValueError):
            h.make_instance_record(service_port=5100, launcher_port=5101, health_token="short")
        with pytest.raises(ValueError):
            h.make_instance_record(service_port=5100, launcher_port=5101, service_host="10.0.0.5")
        with pytest.raises(ValueError):
            h.make_instance_record(service_port=5100, launcher_port=0)
        with pytest.raises(ValueError):
            h.make_instance_record(service_port=5100, launcher_port=5101, pid=0)
        with pytest.raises(ValueError):
            portable_instance.InstanceRecord.from_payload({"schema": 1, "launcher": {}, "service": {}})

    def test_removing_a_missing_record_is_idempotent(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        portable_instance.write_instance_record(layout, h.make_instance_record(service_port=5100, launcher_port=5101))

        portable_instance.remove_instance_record(layout)
        portable_instance.remove_instance_record(layout)

        assert not h.instance_record_path(layout).exists()


class TestTokenAuthenticatedProbes:
    def test_health_probe_requires_the_exact_token_and_payload(self):
        endpoint = h.StubLoopbackEndpoint().start()
        try:
            record = h.make_instance_record(service_port=endpoint.port, launcher_port=endpoint.port)
            assert portable_instance.probe_service_health(record) is True

            endpoint.health_status = 404
            assert portable_instance.probe_service_health(record) is False

            endpoint.health_status = 200
            endpoint.health_payload = {"status": "ok", "extra": True}
            assert portable_instance.probe_service_health(record) is False

            wrong_token = h.make_instance_record(
                service_port=endpoint.port,
                launcher_port=endpoint.port,
                health_token="health-token-" + "z" * 32,
            )
            assert portable_instance.probe_service_health(wrong_token) is False
        finally:
            endpoint.stop()

    def test_health_probe_fails_closed_when_nothing_is_listening(self):
        port = h.free_loopback_port()

        assert (
            portable_instance.probe_service_health(h.make_instance_record(service_port=port, launcher_port=port))
            is False
        )

    def test_launcher_command_maps_accepted_rejected_and_unreachable(self):
        endpoint = h.StubLoopbackEndpoint().start()
        try:
            record = h.make_instance_record(service_port=endpoint.port, launcher_port=endpoint.port)
            assert portable_instance.send_launcher_command(record, "open_logs") == "opened"
            assert endpoint.control_commands == ["open_logs"]

            endpoint.control_commands.clear()
            rejected_token = h.make_instance_record(
                service_port=endpoint.port,
                launcher_port=endpoint.port,
                control_token="launcher-token-" + "z" * 32,
            )
            with pytest.raises(portable_instance.PortableInstanceError) as exc_info:
                portable_instance.send_launcher_command(rejected_token, "quit")
            assert exc_info.value.code == "launcher_control_rejected"
            assert endpoint.control_commands == []

            endpoint.control_status = 500
            endpoint.control_payload = {"status": "command_failed"}
            with pytest.raises(portable_instance.PortableInstanceError) as failure:
                portable_instance.send_launcher_command(record, "open_reader")
            assert failure.value.code == "launcher_control_rejected"

            endpoint.control_status = 200
            endpoint.control_payload = {"status": "unknown"}
            with pytest.raises(portable_instance.PortableInstanceError) as unexpected:
                portable_instance.send_launcher_command(record, "open_reader")
            assert unexpected.value.code == "launcher_control_rejected"
        finally:
            endpoint.stop()

        port = h.free_loopback_port()
        unreachable = h.make_instance_record(service_port=port, launcher_port=port)
        with pytest.raises(portable_instance.PortableInstanceError) as exc_info:
            portable_instance.send_launcher_command(unreachable, "open_reader")
        assert exc_info.value.code == "launcher_control_unreachable"

    def test_launcher_command_rejects_unknown_commands_locally(self):
        record = h.make_instance_record(service_port=5100, launcher_port=5101)

        with pytest.raises(ValueError):
            portable_instance.send_launcher_command(record, "open_shell")

    def test_service_shutdown_maps_accepted_rejected_and_unreachable(self):
        endpoint = h.StubLoopbackEndpoint().start()
        try:
            record = h.make_instance_record(service_port=endpoint.port, launcher_port=endpoint.port)
            portable_instance.send_service_shutdown(record)
            assert endpoint.shutdown_requests == 1
            assert endpoint.shutdown_bodies == [b"{}"]

            rejected_token = h.make_instance_record(
                service_port=endpoint.port,
                launcher_port=endpoint.port,
                service_control_token="service-token-" + "z" * 32,
            )
            with pytest.raises(portable_instance.PortableInstanceError) as exc_info:
                portable_instance.send_service_shutdown(rejected_token)
            assert exc_info.value.code == "service_shutdown_rejected"
            assert endpoint.shutdown_requests == 1

            endpoint.shutdown_status = 200
            endpoint.shutdown_payload = {"status": "ok"}
            with pytest.raises(portable_instance.PortableInstanceError) as unexpected:
                portable_instance.send_service_shutdown(record)
            assert unexpected.value.code == "service_shutdown_rejected"
        finally:
            endpoint.stop()

        port = h.free_loopback_port()
        with pytest.raises(portable_instance.PortableInstanceError) as exc_info:
            portable_instance.send_service_shutdown(h.make_instance_record(service_port=port, launcher_port=port))
        assert exc_info.value.code == "service_shutdown_unreachable"

    def test_records_and_tokens_never_leave_the_data_directory(self, tmp_path):
        layout = h.make_portable_layout(tmp_path)
        record = h.make_instance_record(service_port=5100, launcher_port=5101)
        path = portable_instance.write_instance_record(layout, record)

        assert layout.data_root in path.parents
        outside = tmp_path / "outside.json"
        with pytest.raises(paths.PathStrategyError):
            portable_runtime.write_json_descriptor(layout, outside, dict(record.to_payload()))
        assert not outside.exists()

    def test_harness_endpoint_never_accepts_a_foreign_token(self):
        endpoint = h.StubLoopbackEndpoint().start()
        try:
            assert portable_instance.probe_service_health(
                h.make_instance_record(service_port=endpoint.port, launcher_port=endpoint.port)
            )
            assert endpoint.health_hits == 1
            assert endpoint.requests == [("GET", "/api/health")]
        finally:
            endpoint.stop()
