"""P0-02 术语数据模型：规范化、字段校验与共享错误语义。"""

from datetime import UTC, datetime

import pytest

from pdf_reader.term_model import (
    CANDIDATE_SCHEMA_VERSION,
    CANDIDATE_SCHEMA_VERSION_V1,
    LEGACY_CUMULATIVE_STRATEGY,
    PROTECTED_AUTHORITATIVE_FILENAMES,
    USER_GLOSSARY_SCHEMA_VERSION,
    AuthoritativeTerm,
    CandidateEntry,
    GlossaryRevisionConflictError,
    TargetSuggestion,
    TermStoreError,
    normalize_source_key,
    rank_target_suggestions,
    summarize_candidate_entry,
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
    assert CANDIDATE_SCHEMA_VERSION_V1 == 1
    assert CANDIDATE_SCHEMA_VERSION == 2
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


def test_target_suggestion_tracks_distinct_page_count_and_last_observed_at():
    observed_at = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
    suggestion = TargetSuggestion(
        target="译法",
        observations=3,
        pages=(1, 3, 3),
        evidence=("e",),
        last_observed_at=observed_at,
    )
    assert suggestion.distinct_page_count == 2
    assert suggestion.last_observed_at == observed_at


def test_rank_target_suggestions_orders_accepted_then_unrejected_then_rejected():
    now = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
    entry = CandidateEntry(
        source="TCS",
        status="candidate",
        targets=[
            TargetSuggestion(target="普通A", observations=1, pages=(1,), last_observed_at=now),
            TargetSuggestion(target="普通B", observations=10, pages=(1, 2), last_observed_at=now),
            TargetSuggestion(target="高票", observations=50, pages=(1,), last_observed_at=now),
            TargetSuggestion(target="拒绝R", observations=100, pages=(1, 2, 3), last_observed_at=now),
        ],
        rejected_targets=["拒绝R"],
    )
    ranked = rank_target_suggestions(entry)
    assert [suggestion.target for suggestion in ranked] == ["普通B", "高票", "普通A", "拒绝R"]


def test_rank_target_suggestions_accepted_target_first_even_with_lower_stats():
    now = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
    entry = CandidateEntry(
        source="AD",
        status="accepted",
        accepted_target="用户确认",
        targets=[
            TargetSuggestion(target="用户确认", observations=1, pages=(), last_observed_at=now),
            TargetSuggestion(
                target="高票建议",
                observations=99,
                pages=tuple(range(1, 20)),
                last_observed_at=now,
            ),
        ],
    )
    ranked = rank_target_suggestions(entry)
    assert [suggestion.target for suggestion in ranked] == ["用户确认", "高票建议"]


def test_rank_target_suggestions_uses_lexicographic_tiebreak():
    now = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
    entry = CandidateEntry(
        source="AD",
        targets=[
            TargetSuggestion(target="target-b", observations=1, pages=(1,), last_observed_at=now),
            TargetSuggestion(target="target-a", observations=1, pages=(1,), last_observed_at=now),
        ],
    )
    ranked = rank_target_suggestions(entry)
    assert [suggestion.target for suggestion in ranked] == ["target-a", "target-b"]


def test_summarize_candidate_entry_exposes_status_suppression_and_rank():
    now = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
    entry = CandidateEntry(
        source="benefits",
        status="rejected",
        first_seen_at=now,
        last_seen_at=now,
        targets=[
            TargetSuggestion(
                target="福利",
                observations=5,
                pages=(1, 2),
                evidence=("e",),
                last_observed_at=now,
            ),
            TargetSuggestion(target="新建议", observations=10, pages=(1,), last_observed_at=now),
        ],
        rejected_targets=["福利"],
    )
    summary = summarize_candidate_entry(entry)
    assert summary.source == "benefits"
    assert summary.source_key == "benefits"
    assert summary.status == "rejected"
    assert summary.accepted_target is None
    assert [item.target for item in summary.targets] == ["新建议", "福利"]

    first, second = summary.targets
    assert first.rank == 1
    assert first.accepted is False
    assert first.rejected is False
    assert first.suppressed is True
    assert first.observations == 10
    assert first.distinct_page_count == 1
    assert first.pages == (1,)
    assert first.last_observed_at == now
    assert second.rank == 2
    assert second.rejected is True
    assert second.suppressed is True
    assert second.observations == 5
    assert second.distinct_page_count == 2
    assert second.pages == (1, 2)
