"""P0-02 按规范路径共享的进程内锁。"""

from pdf_reader.path_locks import lock_for_path
from pdf_reader.user_glossary import UserGlossaryStore


def test_lock_for_path_is_shared_per_canonical_path(tmp_path):
    first = tmp_path / "doc" / "user_glossary.csv"
    second = tmp_path / "doc" / "sub" / ".." / "user_glossary.csv"
    other = tmp_path / "other" / "user_glossary.csv"
    assert lock_for_path(first) is lock_for_path(first)
    assert lock_for_path(first) is lock_for_path(second)
    assert lock_for_path(first) is not lock_for_path(other)


def test_store_instances_share_lock_for_same_document(tmp_path):
    document_dir = tmp_path / ("d" * 64)
    document_dir.mkdir()
    assert UserGlossaryStore(document_dir)._lock is UserGlossaryStore(document_dir)._lock
