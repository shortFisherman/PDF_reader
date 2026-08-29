import threading
import time
from pathlib import Path

import pymupdf
import pytest

from state import AppState


def test_app_state_initial():
    state = AppState(Path("/tmp/cache"))
    assert state.is_doc_open() is False
    assert state.page_count == 0
    assert len(state.translated_pages) == 0


def test_open_pdf_creates_cache(sample_pdf, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    from file_hash import sha256

    result = state.open_pdf(str(sample_pdf), sha256)
    assert result["page_count"] == 2
    assert result["hash"] is not None
    assert state.is_doc_open() is True
    state._close_docs()


def test_reopen_closes_old_docs(sample_pdf, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    from file_hash import sha256

    state.open_pdf(str(sample_pdf), sha256)
    state.open_pdf(str(sample_pdf), sha256)
    second_left = state.left_doc
    # After re-open, should have a new document (old one closed)
    assert second_left is not None
    state._close_docs()


def test_translated_pages_tracking(sample_pdf, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    from file_hash import sha256

    state.open_pdf(str(sample_pdf), sha256)
    assert len(state.translated_pages) == 0
    state._close_docs()


def test_glossary_cache_path_no_pdf(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    assert state.glossary_cache_path is None


def test_glossary_cache_path_after_open(sample_pdf, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state = AppState(cache_dir)
    from file_hash import sha256

    state.open_pdf(str(sample_pdf), sha256)
    expected = cache_dir / state.pdf_hash
    assert state.glossary_cache_path == expected
    state._close_docs()


def test_render_page_concurrent_replace_no_crash(app_state, sample_pdf, tmp_path):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id

    translated_pdf = tmp_path / "translated.pdf"
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)
    doc.save(str(translated_pdf))
    doc.close()

    render_started = threading.Event()
    render_can_finish = threading.Event()

    def slow_render_func(doc, page_num, dpi):  # noqa: ANN202, ANN001
        render_started.set()
        render_can_finish.wait(timeout=5)
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes(output="png")

    render_result = [None]
    render_error = [None]

    def render_thread():  # noqa: ANN202
        try:
            render_result[0] = app_state.render_page("right", 0, slow_render_func, 72)
        except Exception as e:
            render_error[0] = e

    def replace_thread():  # noqa: ANN202
        render_started.wait(timeout=5)
        app_state.replace_page(str(translated_pdf), 0, document_id)

    t1 = threading.Thread(target=render_thread)
    t2 = threading.Thread(target=replace_thread)
    t1.start()
    t2.start()

    time.sleep(0.2)
    render_can_finish.set()

    t1.join(timeout=10)
    t2.join(timeout=10)

    assert render_error[0] is None, f"render crashed: {render_error[0]}"
    assert render_result[0] is not None
    assert render_result[0][:4] == b"\x89PNG"


def test_extract_page_returns_path(app_state, sample_pdf, tmp_path):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    def extract_func(doc, page, tmpdir) -> Path:
        out = Path(tmpdir) / f"page_{page}.png"
        out.write_bytes(b"fake-image-data")
        return out

    result = app_state.extract_page(0, tmp_path, extract_func)
    assert result == tmp_path / "page_0.png"
    assert result.read_bytes() == b"fake-image-data"


def test_extract_page_raises_when_no_doc(tmp_path):
    state = AppState(tmp_path / "cache")
    tmp_path.mkdir(exist_ok=True)

    def extract_func(doc, page, tmpdir) -> Path:
        return Path(tmpdir) / "never.txt"

    with pytest.raises(ValueError, match="no document opened"):
        state.extract_page(0, tmp_path, extract_func)


def test_extract_page_holds_lock(app_state, sample_pdf, tmp_path):
    import threading

    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    in_extract = threading.Event()
    extract_can_finish = threading.Event()
    lock_held_in_extract = [False]

    def extract_func(doc, page, tmpdir) -> Path:
        lock_held_in_extract[0] = app_state._lock.locked()
        in_extract.set()
        extract_can_finish.wait(timeout=5)
        return Path(tmpdir) / "result.png"

    result = [None]

    def extract_thread() -> None:
        result[0] = app_state.extract_page(0, tmp_path, extract_func)

    t = threading.Thread(target=extract_thread)
    t.start()
    in_extract.wait(timeout=5)
    assert lock_held_in_extract[0] is True, "lock should be held inside extract_func"
    extract_can_finish.set()
    t.join(timeout=5)
    assert result[0] is not None


def test_concurrent_replace_different_pages(app_state, sample_pdf, tmp_path):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id
    page_count = app_state.page_count
    assert page_count == 2

    translated_pdfs = []
    for i in range(page_count):
        path = tmp_path / f"translated_{i}.pdf"
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((50, 100), f"TRANSLATED_{i}", fontsize=24)
        doc.save(str(path))
        doc.close()
        translated_pdfs.append(path)

    barrier = threading.Barrier(2)
    errors = [None, None]

    def replace_page(idx):  # noqa: ANN202, ANN001
        try:
            barrier.wait(timeout=5)
            app_state.replace_page(str(translated_pdfs[idx]), idx, document_id)
        except Exception as e:
            errors[idx] = e

    threads = [threading.Thread(target=replace_page, args=(i,)) for i in range(page_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors[0] is None, f"replace page 0 failed: {errors[0]}"
    assert errors[1] is None, f"replace page 1 failed: {errors[1]}"

    doc = pymupdf.open(app_state._right_pdf_path)
    assert doc.page_count == 2
    assert "TRANSLATED_0" in doc[0].get_text()
    assert "TRANSLATED_1" in doc[1].get_text()
    doc.close()

    assert 0 in app_state.translated_pages
    assert 1 in app_state.translated_pages


def test_extract_page_normal(app_state, sample_pdf, tmp_path):
    import pdf_extraction
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    extract_tmpdir = tmp_path / "extract"
    extract_tmpdir.mkdir()
    result = app_state.extract_page(0, extract_tmpdir, pdf_extraction.extract_single_page)

    assert result == extract_tmpdir / "page.pdf"
    assert result.exists()


def test_extract_page_under_lock(app_state, sample_pdf, tmp_path):
    import pdf_extraction
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    lock_held_during_extract = [False]

    def track_lock_extract_func(doc, page, tmpdir) -> Path:
        lock_held_during_extract[0] = app_state._lock.locked()
        return pdf_extraction.extract_single_page(doc, page, tmpdir)

    extract_tmpdir = tmp_path / "extract"
    extract_tmpdir.mkdir()
    app_state.extract_page(0, extract_tmpdir, track_lock_extract_func)

    assert lock_held_during_extract[0] is True


def test_concurrent_extract_and_render_serialized(app_state, sample_pdf, tmp_path):
    import threading
    import time

    import pdf_extraction
    from file_hash import sha256 as sha256_func
    from pdf_renderer import render_page

    app_state.open_pdf(str(sample_pdf), sha256_func)

    extract_tmpdir = tmp_path / "extract"
    extract_tmpdir.mkdir()

    extract_started = threading.Event()
    extract_can_finish = threading.Event()

    lock_held = [False]

    def slow_extract_func(doc, page, tmpdir) -> Path:
        lock_held[0] = app_state._lock.locked()
        extract_started.set()
        extract_can_finish.wait(timeout=5)
        return pdf_extraction.extract_single_page(doc, page, tmpdir)

    extract_result = [None]
    extract_error = [None]
    render_result = [None]
    render_error = [None]

    def run_extract() -> None:
        try:
            extract_result[0] = app_state.extract_page(0, extract_tmpdir, slow_extract_func)
        except Exception as e:
            extract_error[0] = e

    def run_render() -> None:
        extract_started.wait(timeout=5)
        try:
            render_result[0] = app_state.render_page("left", 0, render_page, 72)
        except Exception as e:
            render_error[0] = e

    t1 = threading.Thread(target=run_extract)
    t2 = threading.Thread(target=run_render)
    t1.start()
    t2.start()

    # Give extract time to acquire the lock, render should block waiting
    time.sleep(0.2)
    extract_can_finish.set()

    t1.join(timeout=10)
    t2.join(timeout=10)

    assert lock_held[0] is True, "lock should be held inside extract_func"
    assert extract_error[0] is None, f"extract crashed: {extract_error[0]}"
    assert render_error[0] is None, f"render crashed: {render_error[0]}"
    assert extract_result[0] is not None
    assert render_result[0] is not None
    assert isinstance(render_result[0], bytes)
    assert len(render_result[0]) > 0


def test_replace_pages_batch_backfill_and_tracking(app_state, sample_pdf, tmp_path):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id
    page_count = app_state.page_count
    assert page_count == 2

    # 合成 2 页译文 PDF，每页含可区分内容
    translated_pdf = tmp_path / "translated.pdf"
    doc = pymupdf.open()
    for i in range(page_count):
        p = doc.new_page(width=612, height=792)
        p.insert_text((50, 100), f"TRANSLATED_{i}", fontsize=24)
    doc.save(str(translated_pdf))
    doc.close()

    app_state.replace_pages(str(translated_pdf), list(range(page_count)), document_id)

    out = pymupdf.open(app_state._right_pdf_path)
    assert out.page_count == page_count
    assert "TRANSLATED_0" in out[0].get_text()
    assert "TRANSLATED_1" in out[1].get_text()
    out.close()

    assert set(app_state.translated_pages) == {0, 1}


def test_replace_pages_ascending_preserves_other_indices(app_state, sample_pdf, tmp_path):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id

    # 只替换第 1 页（0-based idx=1）
    translated_pdf = tmp_path / "t1.pdf"
    doc = pymupdf.open()
    p = doc.new_page(width=612, height=792)
    p.insert_text((50, 100), "ONLY_PAGE1", fontsize=24)
    doc.save(str(translated_pdf))
    doc.close()

    app_state.replace_pages(str(translated_pdf), [1], document_id)
    out = pymupdf.open(app_state._right_pdf_path)
    assert out.page_count == 2
    assert "ONLY_PAGE1" in out[1].get_text()
    assert 1 in app_state.translated_pages
    assert 0 not in app_state.translated_pages
    out.close()


def test_replace_pages_holds_lock(app_state, sample_pdf, tmp_path, monkeypatch):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    document_id = app_state.translation_snapshot().document_id
    translated_pdf = tmp_path / "t.pdf"
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)
    doc.save(str(translated_pdf))
    doc.close()

    lock_held = [False]
    started = threading.Event()
    can_finish = threading.Event()
    original_delete = pymupdf.Document.delete_page  # noqa: ANN001

    def slow_delete(self, idx):  # noqa: ANN001, ANN202
        lock_held[0] = app_state._lock.locked()
        started.set()
        can_finish.wait(timeout=5)
        return original_delete(self, idx)

    monkeypatch.setattr(pymupdf.Document, "delete_page", slow_delete)

    def replacer():  # noqa: ANN202
        app_state.replace_pages(str(translated_pdf), [0], document_id)

    t = threading.Thread(target=replacer)
    t.start()
    started.wait(timeout=5)
    can_finish.set()
    t.join(timeout=10)
    assert lock_held[0] is True


def test_save_reading_progress_writes_file(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    app_state.save_reading_progress(1)

    progress_file = app_state._reading_progress_path()
    assert progress_file is not None
    assert progress_file.exists()
    import json

    data = json.loads(progress_file.read_text(encoding="utf-8"))
    assert data == {"page": 1}
    app_state._close_docs()


def test_save_reading_progress_no_doc_raises(app_state):
    with pytest.raises(ValueError, match="no document opened"):
        app_state.save_reading_progress(0)


def test_save_reading_progress_out_of_range_raises(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    page_count = app_state.page_count

    with pytest.raises(ValueError, match="page out of range"):
        app_state.save_reading_progress(-1)
    with pytest.raises(ValueError, match="page out of range"):
        app_state.save_reading_progress(page_count)
    app_state._close_docs()


def test_save_reading_progress_leaves_no_tmp_on_failure(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    # 触发越界失败前/后，hash 目录下应无残留 .tmp 文件
    with pytest.raises(ValueError):
        app_state.save_reading_progress(9999)

    cache_subdir = app_state.glossary_cache_path
    tmp_files = list(cache_subdir.glob("reading_progress.json*"))
    assert all("tmp" not in str(p) for p in tmp_files)
    app_state._close_docs()


def test_load_reading_progress_hit(app_state, sample_pdf):
    import json

    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)

    progress_file = app_state._reading_progress_path()
    progress_file.write_text(json.dumps({"page": 1}), encoding="utf-8")

    assert app_state.load_reading_progress() == 1
    app_state._close_docs()


def test_load_reading_progress_missing_returns_none(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    assert app_state.load_reading_progress() is None
    app_state._close_docs()


def test_load_reading_progress_corrupt_returns_none(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    progress_file = app_state._reading_progress_path()
    progress_file.write_text("{not valid json", encoding="utf-8")

    assert app_state.load_reading_progress() is None
    app_state._close_docs()


def test_load_reading_progress_missing_page_key_returns_none(app_state, sample_pdf):
    import json

    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    progress_file = app_state._reading_progress_path()
    progress_file.write_text(json.dumps({"other": 1}), encoding="utf-8")

    assert app_state.load_reading_progress() is None
    app_state._close_docs()


def test_load_reading_progress_out_of_range_clamped_to_zero(app_state, sample_pdf):
    import json

    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    page_count = app_state.page_count

    progress_file = app_state._reading_progress_path()
    progress_file.write_text(json.dumps({"page": page_count + 3}), encoding="utf-8")

    assert app_state.load_reading_progress() == 0
    app_state._close_docs()


def test_load_reading_progress_negative_clamped_to_zero(app_state, sample_pdf):
    import json

    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    progress_file = app_state._reading_progress_path()
    progress_file.write_text(json.dumps({"page": -5}), encoding="utf-8")

    assert app_state.load_reading_progress() == 0
    app_state._close_docs()


def test_open_pdf_response_includes_saved_page_none(app_state, sample_pdf):
    from file_hash import sha256 as sha256_func

    result = app_state.open_pdf(str(sample_pdf), sha256_func)
    assert "saved_page" in result
    assert result["saved_page"] is None
    app_state._close_docs()


def test_open_pdf_response_includes_saved_page_value(app_state, sample_pdf):

    from file_hash import sha256 as sha256_func

    # 先打开写入进度
    app_state.open_pdf(str(sample_pdf), sha256_func)
    app_state.save_reading_progress(1)
    app_state._close_docs()

    # 重新打开，应读到保存的页
    result = app_state.open_pdf(str(sample_pdf), sha256_func)
    assert result["saved_page"] == 1
    app_state._close_docs()


def test_open_pdf_does_not_delete_progress_file(app_state, sample_pdf):

    from file_hash import sha256 as sha256_func

    app_state.open_pdf(str(sample_pdf), sha256_func)
    app_state.save_reading_progress(1)
    progress_file = app_state._reading_progress_path()
    app_state._close_docs()

    # 再次打开（会 _close_docs 重置）后进度文件应仍在
    assert progress_file.exists()
    app_state.open_pdf(str(sample_pdf), sha256_func)
    assert progress_file.exists()
    app_state._close_docs()
