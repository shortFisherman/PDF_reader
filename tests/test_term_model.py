"""P0-02 术语数据模型：规范化、字段校验与共享错误语义。"""

import pytest

from pdf_reader.term_model import (
    CANDIDATE_SCHEMA_VERSION,
    LEGACY_CUMULATIVE_STRATEGY,
    PROTECTED_AUTHORITATIVE_FILENAMES,
    USER_GLOSSARY_SCHEMA_VERSION,
    AuthoritativeTerm,
    CandidateEntry,
    GlossaryRevisionConflictError,
    TermStoreError,
    normalize_source_key,
    validate_strategy_version,
    validate_term_text,
)


def test_normalize_source_key_lowercases_and_collapses_whitespace():
    assert (
        normalize_source_key("  Atopic Dermatitis\n\tPractice   Parameter ") == "atopic dermatitis practice parameter"
    )
    assert normalize_source_key("AD") == "ad"
    assert normalize_source_key("  ad ") == "ad"


def test_validate_term_text_rejects_empty_and_control_characters():
    for value in ("", "   ", "\n", "a\rb", "a\x00b"):
        with pytest.raises(TermStoreError):
            validate_term_text(value, "source")
    assert validate_term_text("  TCS  ", "source") == "TCS"


def test_validate_strategy_version_rejects_empty_and_control_characters():
    for value in ("", "   ", "auto\n1", "auto\r1", "auto\x001"):
        with pytest.raises(TermStoreError, match="strategy_version"):
            validate_strategy_version(value)
    assert validate_strategy_version(" legacy-cumulative-csv/1 ") == "legacy-cumulative-csv/1"


def test_authoritative_term_source_key_property():
    term = AuthoritativeTerm(source=" Atopic Dermatitis ", target="特应性皮炎", scope="document")
    assert term.source_key == "atopic dermatitis"


def test_candidate_entry_defaults_are_safe():
    entry = CandidateEntry(source="AD")
    assert entry.status == "candidate"
    assert entry.targets == []
    assert entry.accepted_target is None
    assert entry.rejected_targets == []


def test_schema_versions_are_pinned():
    assert USER_GLOSSARY_SCHEMA_VERSION == 1
    assert CANDIDATE_SCHEMA_VERSION == 1
    assert LEGACY_CUMULATIVE_STRATEGY == "legacy-cumulative-csv/1"


def test_protected_filenames_cover_authoritative_and_compile_products():
    assert {
        "user_glossary.csv",
        "effective_glossary.csv",
        "glossary.csv",
        "term_candidates.json",
    } == set(PROTECTED_AUTHORITATIVE_FILENAMES)
    assert "cumulative_glossary.csv" not in PROTECTED_AUTHORITATIVE_FILENAMES


def test_revision_conflict_error_has_expected_and_actual():
    exc = GlossaryRevisionConflictError("revision conflict", expected=3, actual=4)
    assert exc.expected == 3
    assert exc.actual == 4
