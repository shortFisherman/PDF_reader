import csv
from pathlib import Path
from unittest.mock import MagicMock, patch

from translation_lifecycle import finish_translation, merge_glossary_only


def test_finish_translation_mono_non_none():
    mock_replace = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = Path("/tmp/mono.pdf")
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = None

    with (
        patch("translation_lifecycle.merge_after_translate"),
        patch("translation_lifecycle.debug_trace.log_glossary_merge"),
    ):
        finish_translation(result, mock_replace, Path("/tmp/cache"))

    mock_replace.assert_called_once_with(str(Path("/tmp/mono.pdf")))


def test_finish_translation_mono_none_dual_fallback():
    mock_replace = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = None
    result.dual_pdf_path = Path("/tmp/dual.pdf")
    result.auto_extracted_glossary_path = None

    with (
        patch("translation_lifecycle.merge_after_translate"),
        patch("translation_lifecycle.debug_trace.log_glossary_merge"),
    ):
        finish_translation(result, mock_replace, Path("/tmp/cache"))

    mock_replace.assert_called_once_with(str(Path("/tmp/dual.pdf")))


def test_finish_translation_both_none_skip_replace():
    mock_replace = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = None
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = None

    with (
        patch("translation_lifecycle.merge_after_translate"),
        patch("translation_lifecycle.debug_trace.log_glossary_merge"),
    ):
        finish_translation(result, mock_replace, Path("/tmp/cache"))

    mock_replace.assert_not_called()


def test_finish_translation_auto_extracted_present():
    mock_replace = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = Path("/tmp/m.pdf")
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = Path("/tmp/g.csv")

    with (
        patch("translation_lifecycle.merge_after_translate") as mock_merge,
        patch("translation_lifecycle.debug_trace.log_glossary_merge"),
    ):
        finish_translation(result, mock_replace, Path("/tmp/cache"))

    mock_replace.assert_called_once_with(str(Path("/tmp/m.pdf")))
    mock_merge.assert_called_once_with(
        Path("/tmp/cache") / "cumulative_glossary.csv",
        Path("/tmp/g.csv"),
    )


def test_finish_translation_auto_extracted_none():
    mock_replace = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = Path("/tmp/m.pdf")
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = None

    with (
        patch("translation_lifecycle.merge_after_translate") as mock_merge,
        patch("translation_lifecycle.debug_trace.log_glossary_merge"),
    ):
        finish_translation(result, mock_replace, Path("/tmp/cache"))

    mock_replace.assert_called_once_with(str(Path("/tmp/m.pdf")))
    mock_merge.assert_called_once_with(
        Path("/tmp/cache") / "cumulative_glossary.csv",
        None,
    )


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

    merge_glossary_only(mock_result, glossary_cache)

    with open(cumulative_file, newline="", encoding="utf-8") as f:
        rows = {r["source"]: r["target"] for r in csv.DictReader(f)}
    assert rows.get("alpha") == "阿尔法"
    assert rows.get("beta") == "贝塔"
