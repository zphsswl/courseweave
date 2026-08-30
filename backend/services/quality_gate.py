"""Deterministic quality gates for LLM-generated knowledge graph records."""
import re
from dataclasses import dataclass, field


GENERIC_CONCEPT_TYPES = {
    "concept",
    "definition",
    "principle",
    "process",
    "formula",
    "method",
    "example",
    "condition",
    "exception",
}

SEMANTIC_RELATION_TYPES = {
    "prerequisite",
    "causes",
    "contrasts_with",
    "equivalent_to",
    "applies_to",
    "supports",
    "conflicts_with",
    "related_to",
}
STRUCTURAL_RELATION_TYPES = {"contains", "part_of", "example_of"}
ALLOWED_RELATION_TYPES = SEMANTIC_RELATION_TYPES | STRUCTURAL_RELATION_TYPES

NOISE_PATTERNS = (
    re.compile(
        r"^(目录|前言|序言|绪论(?:/前言)?|出版说明|编者的话|内容提要|参考文献|练习题|思考题|本章小结|关键词|contents?|preface)$",
        re.IGNORECASE,
    ),
    re.compile(r"^第?\d+页$"),
    re.compile(r"^[\W_]+$"),
    re.compile(r".*(?:\.{4,}|…{2,}|·{4,}).*"),
)

FRONT_MATTER_PATTERN = re.compile(
    r"(?:前言|序言|绪论|目录|出版说明|编者的话|内容提要)",
    re.IGNORECASE,
)
BROKEN_TEXT_PATTERN = re.compile(r"\uFFFD|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


@dataclass
class QualityResult:
    accepted: bool
    score: float
    flags: list[str] = field(default_factory=list)
    evidence_verified: bool = False


def normalize_evidence(text: str) -> str:
    return re.sub(r"\s+", "", text or "").strip().lower()


def has_broken_text(text: str) -> bool:
    """Detect replacement glyphs and hidden PDF control characters."""
    return bool(BROKEN_TEXT_PATTERN.search(text or ""))


def is_front_matter_title(value: str) -> bool:
    """Return True for non-teaching front matter that must not enter the graph."""
    text = re.sub(r"\s+", " ", value or "").strip(" ：:，,。；;、-—")
    text = re.sub(r"^第[一二三四五六七八九十百千\d１２３４５６７８９０]+章\s*", "", text)
    return bool(FRONT_MATTER_PATTERN.search(text))


def is_front_matter_node(node) -> bool:
    return is_front_matter_title(getattr(node, "name", "")) or is_front_matter_title(
        getattr(node, "chapter_title", "")
    )


def quote_exists(source_quote: str, source_text: str) -> bool:
    quote = normalize_evidence(source_quote)
    source = normalize_evidence(source_text)
    return len(quote) >= 8 and quote in source


def validate_node_candidate(candidate: dict, source_text: str) -> QualityResult:
    name = str(candidate.get("name", "")).strip()
    definition = str(candidate.get("definition", "")).strip()
    source_quote = str(candidate.get("source_quote", "")).strip()
    concept_type = str(candidate.get("concept_type") or candidate.get("category") or "concept").strip()
    flags = []
    score = 1.0

    if not 2 <= len(name) <= 80:
        flags.append("invalid_name_length")
        score -= 0.35
    if any(pattern.match(name) for pattern in NOISE_PATTERNS):
        flags.append("noise_term")
        score -= 0.5
    if is_front_matter_title(name):
        flags.append("front_matter")
        score -= 1.0
    if len(name) > 42 or re.search(r"[。！？；]", name) or name.count("，") >= 2:
        flags.append("sentence_as_name")
        score -= 0.5
    if len(definition) < 8:
        flags.append("definition_too_short")
        score -= 0.2
    if normalize_evidence(definition) == normalize_evidence(name):
        flags.append("definition_repeats_name")
        score -= 0.3
    if concept_type not in GENERIC_CONCEPT_TYPES:
        flags.append("unknown_concept_type")
        score -= 0.1

    evidence_verified = quote_exists(source_quote, source_text)
    if not source_quote:
        flags.append("missing_source_quote")
        score -= 0.35
    elif has_broken_text(source_quote):
        flags.append("broken_source_quote")
        score -= 1.0
    elif not evidence_verified:
        flags.append("source_quote_not_found")
        score -= 0.35

    hard_failures = {
        "invalid_name_length", "noise_term", "sentence_as_name",
        "front_matter", "broken_source_quote",
    }
    accepted = not hard_failures.intersection(flags) and score >= 0.45
    return QualityResult(
        accepted=accepted,
        score=max(0.0, min(1.0, score)),
        flags=flags,
        evidence_verified=evidence_verified,
    )


def validate_edge_candidate(edge: dict, source_text: str, known_local_ids: set[str]) -> QualityResult:
    source = str(edge.get("source", ""))
    target = str(edge.get("target", ""))
    relation_type = str(edge.get("relation_type", ""))
    source_quote = str(edge.get("source_quote", "")).strip()
    flags = []
    score = 1.0

    if source == target:
        flags.append("self_loop")
        score -= 1.0
    if source not in known_local_ids or target not in known_local_ids:
        flags.append("unknown_endpoint")
        score -= 1.0
    if relation_type not in ALLOWED_RELATION_TYPES:
        flags.append("unsupported_relation")
        score -= 1.0

    evidence_verified = relation_type in STRUCTURAL_RELATION_TYPES
    if relation_type in SEMANTIC_RELATION_TYPES:
        evidence_verified = quote_exists(source_quote, source_text)
        if not source_quote:
            flags.append("missing_relation_evidence")
            score -= 0.6
        elif not evidence_verified:
            flags.append("relation_evidence_not_found")
            score -= 0.6

    return QualityResult(
        accepted=score >= 0.5,
        score=max(0.0, min(1.0, score)),
        flags=flags,
        evidence_verified=evidence_verified,
    )


def find_source_chunk(source_quote: str, chunks):
    normalized_quote = normalize_evidence(source_quote)
    if normalized_quote:
        for chunk in chunks:
            if normalized_quote in normalize_evidence(chunk.content):
                return chunk
    return chunks[0] if chunks else None
