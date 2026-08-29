import csv
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pdf_reader.glossary_service import merge_after_translate
from pdf_reader.translation_lifecycle import finish_translation, merge_glossary_only


def test_finish_translation_mono_non_none():
    mock_replace = MagicMock()
    mock_merge = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = Path("/tmp/mono.pdf")
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = None

    with patch("pdf_reader.translation_lifecycle.debug_trace.log_glossary_merge"):
        finish_translation(result, mock_replace, mock_merge)

    mock_replace.assert_called_once_with(str(Path("/tmp/mono.pdf")))
    mock_merge.assert_called_once_with(None)


def test_finish_translation_mono_none_dual_fallback():
    mock_replace = MagicMock()
    mock_merge = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = None
    result.dual_pdf_path = Path("/tmp/dual.pdf")
    result.auto_extracted_glossary_path = None

    with patch("pdf_reader.translation_lifecycle.debug_trace.log_glossary_merge"):
        finish_translation(result, mock_replace, mock_merge)

    mock_replace.assert_called_once_with(str(Path("/tmp/dual.pdf")))
    mock_merge.assert_called_once_with(None)


def test_finish_translation_stale_replace_skips_glossary_merge():
    from pdf_reader.state import StaleDocumentError

    mock_replace = MagicMock(side_effect=StaleDocumentError("stale translation result rejected"))
    mock_merge = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = Path("/tmp/stale.pdf")
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = Path("/tmp/stale.csv")

    with pytest.raises(StaleDocumentError):
        finish_translation(result, mock_replace, mock_merge)

    mock_merge.assert_not_called()


def test_finish_translation_both_none_skip_replace():
    mock_replace = MagicMock()
    mock_merge = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = None
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = None

    with patch("pdf_reader.translation_lifecycle.debug_trace.log_glossary_merge"):
        finish_translation(result, mock_replace, mock_merge)

    mock_replace.assert_not_called()
    mock_merge.assert_called_once_with(None)


def test_finish_translation_auto_extracted_present():
    mock_replace = MagicMock()
    mock_merge = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = Path("/tmp/m.pdf")
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = Path("/tmp/g.csv")

    with patch("pdf_reader.translation_lifecycle.debug_trace.log_glossary_merge"):
        finish_translation(result, mock_replace, mock_merge)

    mock_replace.assert_called_once_with(str(Path("/tmp/m.pdf")))
    mock_merge.assert_called_once_with(Path("/tmp/g.csv"))


def test_finish_translation_auto_extracted_none():
    mock_replace = MagicMock()
    mock_merge = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = Path("/tmp/m.pdf")
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = None

    with patch("pdf_reader.translation_lifecycle.debug_trace.log_glossary_merge"):
        finish_translation(result, mock_replace, mock_merge)

    mock_replace.assert_called_once_with(str(Path("/tmp/m.pdf")))
    mock_merge.assert_called_once_with(None)


def test_merge_glossary_only_does_not_replace(tmp_path):
    glossary_cache = tmp_path / "cache"
    glossary_cache.mkdir()
    cumulative_file = glossary_cache / "cumulative_glossary.csv"
    with open(cumulative_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        w.writerow(["alpha", "阿尔法"])

    auto_file = glossary_cache / "auto.csv"
    with open(auto_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        w.writerow(["beta", "贝塔"])

    mock_result = MagicMock()
    mock_result.mono_pdf_path = str(tmp_path / "should_not_be_used.pdf")
    mock_result.dual_pdf_path = None
    mock_result.auto_extracted_glossary_path = str(auto_file)

    merge_glossary_only(mock_result, lambda auto_path: merge_after_translate(cumulative_file, auto_path))

    with open(cumulative_file, newline="", encoding="utf-8") as f:
        rows = {r["source"]: r["target"] for r in csv.DictReader(f)}
    assert rows.get("alpha") == "阿尔法"
    assert rows.get("beta") == "贝塔"
