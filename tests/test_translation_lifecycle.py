from pathlib import Path
from unittest.mock import MagicMock, patch

from translation_lifecycle import finish_translation


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
