import csv
from pathlib import Path
from unittest.mock import patch

from glossary_service import merge_after_translate, resolve_glossary_paths


def test_resolve_glossary_paths_returns_none_when_no_cache():
    assert resolve_glossary_paths(None) is None


def test_resolve_glossary_paths_returns_none_when_no_cumulative_file():
    assert resolve_glossary_paths(Path("/nonexistent")) is None


def test_resolve_glossary_paths_returns_path_when_cumulative_exists(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cumulative = cache_dir / "cumulative_glossary.csv"
    with open(cumulative, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "target"])
        w.writerow(["hello", "你好"])

    result = resolve_glossary_paths(cache_dir)
    assert result == [str(cumulative)]


def test_resolve_glossary_paths_returns_none_when_cumulative_empty(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cumulative = cache_dir / "cumulative_glossary.csv"
    cumulative.write_text("")

    assert resolve_glossary_paths(cache_dir) is None


def test_merge_after_translate_delegates_to_merger(tmp_path):
    cumulative = tmp_path / "cumulative.csv"
    auto = tmp_path / "auto.csv"
    cumulative.write_text("")
    auto.write_text("")

    with patch("glossary_service.merge_glossary_csvs") as mock_merge:
        merge_after_translate(cumulative, auto)
        mock_merge.assert_called_once_with(cumulative, auto)


def test_merge_after_translate_swallows_exception(tmp_path):
    cumulative = tmp_path / "cumulative.csv"
    auto = tmp_path / "auto.csv"

    with patch("glossary_service.merge_glossary_csvs", side_effect=Exception("merge failed")):
        merge_after_translate(cumulative, auto)


def test_merge_after_translate_none_paths():
    merge_after_translate(None, None)
