"""P1-02 候选后置过滤：普通词、源文证据、边界匹配与确定性。"""

from __future__ import annotations

import pytest

from pdf_reader.candidate_filter import (
    CANDIDATE_FILTER_VERSION,
    CANDIDATE_STRATEGY_VERSION,
    MAX_EVIDENCE_LENGTH,
    MAX_SOURCE_CHARS,
    MAX_SOURCE_WORDS,
    FilteredCandidate,
    _clean_source,
    filter_candidates,
)
from pdf_reader.term_extraction import STRATEGY_VERSION, TermCandidate


def _filter(
    source: str,
    target: str,
    sent: str,
    chunks: list[tuple[int, str]],
) -> FilteredCandidate:
    result = filter_candidates([TermCandidate(source, target)], sent, chunks)
    assert len(result) == 1
    return result[0]


def test_ad_matches_standalone_but_not_inside_other_words():
    sent = "adherence was reviewed; adverse events were listed; the shadow of doubt remained. AD is treated separately."
    kept = _filter("AD", "阿尔茨海默病", sent, [(1, sent)])
    assert kept.reason is None
    assert kept.pages == (1,)
    assert kept.evidence
    assert "AD" in kept.evidence[0]

    only_inside = "adherence and adverse events cast a shadow."
    rejected = _filter("AD", "阿尔茨海默病", only_inside, [(1, only_inside)])
    assert rejected.reason == "no_source_match"


@pytest.mark.parametrize("sent", ["αADβ", "ADβ", "αAD", "AD_adjacent", "AD_related"])
def test_unicode_word_boundary_rejects_inside_unicode_or_underscore_words(sent):
    rejected = _filter("AD", "阿尔茨海默病", sent, [(1, sent)])
    assert rejected.reason == "no_source_match"


@pytest.mark.parametrize("sent", ["AD", "AD-related terms", "(AD)", "AD is here."])
def test_unicode_word_boundary_keeps_standalone_and_hyphen_context(sent):
    kept = _filter("AD", "阿尔茨海默病", sent, [(1, sent)])
    assert kept.reason is None


def test_match_is_case_insensitive_and_folds_internal_whitespace():
    sent = "atopic  dermatitis\nand other terms."
    kept = _filter("Atopic Dermatitis", "特应性皮炎", sent, [(1, sent)])
    assert kept.reason is None


def test_source_cleanup_strips_punctuation_and_folds_whitespace():
    sent = "Benefits appear often."
    rejected = _filter("— benefits.", "获益", sent, [(1, sent)])
    assert rejected.reason == "common_word"


def test_kept_candidate_source_is_cleaned():
    sent = "Pembrolizumab was administered."
    kept = _filter("  Pembrolizumab  ", "帕博利珠单抗", sent, [(1, sent)])
    assert kept.reason is None
    assert kept.source == "Pembrolizumab"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("— benefits.", "benefits"),
        ("“AD”", "AD"),
        ("（TCS）", "TCS"),
        ("• AD", "AD"),
        ("[TBD]", "TBD"),
        ("CD4+", "CD4+"),
        (".NET", ".NET"),
        ("C++", "C++"),
    ],
)
def test_conservative_cleanup_preserves_semantic_edge_symbols(raw, expected):
    assert _clean_source(raw) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [("CD4+", "CD4+"), (".NET", ".NET"), ("C++", "C++")],
)
def test_semantic_edge_symbol_terms_kept_without_rewrite(source, expected):
    sent = f"{source} is discussed."
    kept = _filter(source, "中文译法", sent, [(1, sent)])
    assert kept.reason is None
    assert kept.source == expected


@pytest.mark.parametrize(
    "source",
    [
        "The patient benefits from treatment.",
        "The patient benefits",
        "This study shows benefit?",
    ],
)
def test_complete_sentence_rejected(source):
    sent = f"context {source} context"
    assert _filter(source, "患者获益", sent, [(1, sent)]).reason == "complete_sentence"


@pytest.mark.parametrize(
    "source",
    [
        "Patients benefit from treatment.",
        "Patients benefit from treatment",
        "Patients benefit",
        "Studies show improvement",
    ],
)
def test_obvious_subject_verb_sentences_rejected(source):
    assert _filter(source, "患者获益", source, [(1, source)]).reason == "complete_sentence"


@pytest.mark.parametrize(
    "source",
    [
        "Staphylococcus aureus.",
        "chronic spontaneous urticaria.",
        "C.O.P.D.",
        "AD?",
    ],
)
def test_medical_phrases_with_trailing_punctuation_kept(source):
    sent = f"The guideline mentions {source} more than once."
    kept = _filter(source, "中文译法", sent, [(1, sent)])
    assert kept.reason is None
    assert kept.source == source[:-1]


@pytest.mark.parametrize(
    "source",
    [
        "European Society of Cardiology guideline",
        "chronic spontaneous urticaria",
        "Atopic Dermatitis Practice Parameter",
    ],
)
def test_guideline_and_disease_phrases_not_misjudged_as_sentences(source):
    sent = f"The text mentions {source} here."
    assert _filter(source, "中文译法", sent, [(1, sent)]).reason is None


def test_word_and_char_limits():
    long = " ".join(f"W{i}" for i in range(MAX_SOURCE_WORDS + 1))
    sent = f"context {long} context"
    assert _filter(long, "译法", sent, [(1, sent)]).reason == "too_many_words"

    huge = "X" * (MAX_SOURCE_CHARS + 1)
    assert _filter(huge, "译法", huge, [(1, huge)]).reason == "too_long"


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("123", "numeric"),
        ("12.5", "numeric"),
        ("10%", "numeric"),
        ("x = 5", "formula"),
        ("T^2", "formula"),
        ("T_max", "formula"),
        ("x", "variable"),
        ("A", "variable"),
        ("Page 12", "page_number"),
        ("p. 12", "page_number"),
        ("[TBD]", "placeholder"),
        ("???", "placeholder"),
    ],
)
def test_structural_rejections(source, reason):
    sent = f"context {source} context"
    assert _filter(source, "译法", sent, [(1, sent)]).reason == reason


@pytest.mark.parametrize("source", ["x+y", "x + y", "a/b", "a * b", "x+y+z"])
def test_binary_operator_formulas_rejected(source):
    sent = f"context {source} context"
    assert _filter(source, "译法", sent, [(1, sent)]).reason == "formula"


@pytest.mark.parametrize("source", ["CD4+", "C++", "IL-6", "H1N1", "CD4+T"])
def test_medical_and_technical_tokens_not_formulas(source):
    sent = f"{source} is discussed."
    kept = _filter(source, "中文译法", sent, [(1, sent)])
    assert kept.reason is None
    assert kept.source == source


@pytest.mark.parametrize(
    "source",
    [
        "benefits",
        "cost",
        "confusion",
        "education",
        "burden",
        "gaining control",
        "patient",
        "quality",
    ],
)
def test_common_terms_rejected(source):
    sent = f"{source} is mentioned in the text."
    assert _filter(source, "获益", sent, [(1, sent)]).reason == "common_word"


def test_target_without_han_rejected():
    sent = "AD is mentioned here."
    assert _filter("AD", "Alzheimer", sent, [(1, sent)]).reason == "bad_target"
    assert _filter("AD", "", sent, [(1, sent)]).reason == "bad_target"


@pytest.mark.parametrize("target", ["中文译法", "\u3400", "\uf900"])
def test_han_detection_covers_extension_a_and_compatibility(target):
    sent = "AD appears here."
    assert _filter("AD", target, sent, [(1, sent)]).reason is None


def test_hallucinated_source_rejected():
    sent = "No trace of the claimed term here."
    assert _filter("nonexistentterm", "不存在的术语", sent, [(1, sent)]).reason == "no_source_match"


@pytest.mark.parametrize(
    "source",
    [
        "pembrolizumab",
        "atopic dermatitis",
        "chronic spontaneous urticaria",
        "IL-6",
        "p53",
        "hemoglobin A1c",
        "TCS",
        "C.O.P.D",
        "AD",
    ],
)
def test_typical_medical_terms_kept(source):
    target = "目标译法"
    sent = f"The guideline discusses {source} at length."
    assert _filter(source, target, sent, [(1, sent)]).reason is None


def test_evidence_bounded_folded_and_collected_per_hit_page():
    page1 = "Long context before " + ("W" * 300) + " AD term appears here. " + ("X" * 300)
    page3 = "Another page with AD on it."
    chunks = [(1, page1), (3, page3)]
    sent = "\n".join(text for _, text in chunks)
    kept = _filter("AD", "阿尔茨海默病", sent, chunks)
    assert kept.reason is None
    assert kept.pages == (1, 3)
    assert len(kept.evidence) == 2
    assert all(len(snippet) <= MAX_EVIDENCE_LENGTH for snippet in kept.evidence)
    assert all("\n" not in snippet and "  " not in snippet for snippet in kept.evidence)
    assert all("AD" in snippet for snippet in kept.evidence)


def test_cross_page_spanning_match_rejected_without_evidence():
    chunks = [(1, "chronic spontaneous"), (2, "urticaria guidelines.")]
    sent = "chronic spontaneous\nurticaria guidelines."
    rejected = _filter("chronic spontaneous urticaria", "慢性自发性荨麻疹", sent, chunks)
    assert rejected.reason == "no_evidence_page"


def test_duplicate_page_chunks_produce_deduped_pages_and_bounded_evidence():
    chunks = [(1, "AD appears here."), (1, "AD appears again."), (2, "AD on page two.")]
    sent = "\n".join(text for _, text in chunks)
    kept = _filter("AD", "阿尔茨海默病", sent, chunks)
    assert kept.pages == (1, 2)
    assert len(kept.evidence) == 2


def test_deterministic_output_across_runs_and_page_order():
    chunks = [(2, "AD appears here."), (1, "TCS and AD appear here.")]
    sent = "\n".join(text for _, text in chunks)
    candidates = [
        TermCandidate("AD", "阿尔茨海默病"),
        TermCandidate("TCS", "外用糖皮质激素"),
        TermCandidate("benefits", "获益"),
    ]
    first = filter_candidates(candidates, sent, chunks)
    second = filter_candidates(candidates, sent, chunks)
    assert first == second
    assert first[0].pages == (1, 2)
    assert first[0].evidence[0] == "TCS and AD appear here."
    assert first[0].evidence[1] == "AD appears here."


def test_single_bad_candidate_does_not_fail_batch():
    sent = "AD and TCS are discussed."
    result = filter_candidates(
        [TermCandidate("hallucinated", "幻觉术语"), TermCandidate("AD", "阿尔茨海默病")],
        sent,
        [(1, sent)],
    )
    kept = [item for item in result if item.reason is None]
    rejected = [item for item in result if item.reason is not None]
    assert len(kept) == 1
    assert kept[0].source == "AD"
    assert [item.reason for item in rejected] == ["no_source_match"]


def test_filter_version_is_explicit_and_enters_strategy_version():
    assert CANDIDATE_FILTER_VERSION == "candidate-filter/1"
    assert CANDIDATE_STRATEGY_VERSION == f"{STRATEGY_VERSION}+{CANDIDATE_FILTER_VERSION}"
