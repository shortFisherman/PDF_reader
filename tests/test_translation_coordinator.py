import threading
from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from translation_coordinator import TranslationBusyError, TranslationCoordinator, TranslationJob


@pytest.fixture
def coordinator() -> TranslationCoordinator:
    return TranslationCoordinator()


def test_initial_state(coordinator: TranslationCoordinator) -> None:
    assert coordinator.active_job is None
    assert coordinator.is_busy is False


def test_start_creates_metadata_and_is_frozen(coordinator: TranslationCoordinator) -> None:
    pages = [1, 3, 5]
    job = coordinator.start("doc-1", pages)

    assert isinstance(job.job_id, str)
    assert job.document_id == "doc-1"
    assert job.page_indices == (1, 3, 5)
    assert isinstance(job.created_at, datetime)
    assert job.status == "active"
    assert coordinator.active_job is job
    assert coordinator.is_busy is True

    with pytest.raises(FrozenInstanceError):
        job.job_id = "changed"


def test_start_copies_page_indices_into_tuple(coordinator: TranslationCoordinator) -> None:
    pages = [2, 4, 6]
    job = coordinator.start("doc-copy", pages)
    pages.append(8)

    assert isinstance(job.page_indices, tuple)
    assert job.page_indices == (2, 4, 6)


def test_second_start_raises_busy_with_active_job(coordinator: TranslationCoordinator) -> None:
    first = coordinator.start("doc-1", (1,))

    with pytest.raises(TranslationBusyError) as exc_info:
        coordinator.start("doc-2", (2,))

    assert exc_info.value.active_job is first
    assert coordinator.active_job is first
    assert coordinator.is_busy is True


def test_finish_releases_only_matching_job_and_is_idempotent(coordinator: TranslationCoordinator) -> None:
    job = coordinator.start("doc-1", (1,))

    assert coordinator.finish("other-job") is False
    assert coordinator.active_job is job

    assert coordinator.finish(job.job_id) is True
    assert coordinator.active_job is None
    assert coordinator.is_busy is False

    assert coordinator.finish(job.job_id) is False


def test_fail_releases_only_matching_job_and_is_idempotent(coordinator: TranslationCoordinator) -> None:
    job = coordinator.start("doc-1", (1,))

    assert coordinator.fail("other-job") is False
    assert coordinator.active_job is job

    assert coordinator.fail(job.job_id) is True
    assert coordinator.active_job is None
    assert coordinator.is_busy is False

    assert coordinator.fail(job.job_id) is False


def test_cancel_releases_only_matching_job_and_is_idempotent(coordinator: TranslationCoordinator) -> None:
    job = coordinator.start("doc-1", (1,))

    assert coordinator.cancel("other-job") is False
    assert coordinator.active_job is job

    assert coordinator.cancel(job.job_id) is True
    assert coordinator.active_job is None
    assert coordinator.is_busy is False

    assert coordinator.cancel(job.job_id) is False


def test_release_allows_new_start_and_stale_release_is_ignored(coordinator: TranslationCoordinator) -> None:
    first = coordinator.start("doc-1", (1,))
    coordinator.finish(first.job_id)

    second = coordinator.start("doc-2", (2,))
    assert coordinator.finish(first.job_id) is False
    assert coordinator.fail(first.job_id) is False
    assert coordinator.active_job is second
    assert coordinator.is_busy is True

    coordinator.finish(second.job_id)
    assert coordinator.active_job is None


def test_concurrent_start_allows_exactly_one_winner(coordinator: TranslationCoordinator) -> None:
    worker_count = 16
    barrier = threading.Barrier(worker_count)
    lock = threading.Lock()
    outcomes: list[object] = []

    def worker(worker_id: int) -> None:
        barrier.wait()
        try:
            job = coordinator.start(f"doc-{worker_id}", (worker_id,))
        except TranslationBusyError as exc:
            with lock:
                outcomes.append(exc)
        else:
            with lock:
                outcomes.append(job)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(worker_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [outcome for outcome in outcomes if isinstance(outcome, TranslationJob)]
    losers = [outcome for outcome in outcomes if isinstance(outcome, TranslationBusyError)]

    assert len(winners) == 1
    assert len(losers) == worker_count - 1
    assert coordinator.active_job is winners[0]
    assert coordinator.is_busy is True
    for exc in losers:
        assert exc.active_job is winners[0]
