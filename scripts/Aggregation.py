from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union


PathLike = Union[str, Path]


@dataclass
class SourceCandidate:
    """Original candidate information that contributed to one aggregated meaning."""

    candidate_index: int
    parse_index: Optional[int]
    ccg_id: Optional[str]
    canonical_semantics: str
    score: float
    original_score: Optional[float]


@dataclass
class AggregatedCandidate:
    """One sentence-level meaning after exact-match aggregation."""

    candidate_index: int
    canonical_semantics: str
    aggregated_score: float
    score: float
    source_count: int
    source_candidates: List[SourceCandidate] = field(default_factory=list)


@dataclass
class SentenceAggregationResult:
    sentence_index: int
    sentence_id: str
    surface: str
    total_input_candidates: int
    eligible_candidates: int
    skipped_candidates: int
    skip_reason_counts: Dict[str, int]
    normalization_total: float
    score_sum: float
    candidates: List[AggregatedCandidate] = field(default_factory=list)


@dataclass
class AggregationResult:
    source_json: str
    sentences: List[SentenceAggregationResult]
    source_metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> Dict[str, int]:
        total_input_candidates = sum(sentence.total_input_candidates for sentence in self.sentences)
        eligible_candidates = sum(sentence.eligible_candidates for sentence in self.sentences)
        aggregated_candidates = sum(len(sentence.candidates) for sentence in self.sentences)
        return {
            "total_sentences": len(self.sentences),
            "total_input_candidates": total_input_candidates,
            "eligible_candidates": eligible_candidates,
            "aggregated_candidates": aggregated_candidates,
            "skipped_candidates": total_input_candidates - eligible_candidates,
        }

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "source_json": self.source_json,
            "summary": self.summary,
            "sentences": [asdict(sentence) for sentence in self.sentences],
        }
        if self.source_metadata:
            payload["source_metadata"] = self.source_metadata
        return payload


def load_input(json_path: PathLike) -> Dict[str, Any]:
    with Path(json_path).open("r", encoding="utf-8") as fin:
        return json.load(fin)


def save_result(result: AggregationResult, output_json_path: PathLike) -> None:
    output_path = Path(output_json_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fout:
        json.dump(result.to_dict(), fout, ensure_ascii=False, indent=2)


def aggregate_json(input_json_path: PathLike) -> AggregationResult:
    data = load_input(input_json_path)
    return aggregate_data(data, source_json=str(input_json_path))


def aggregate_data(data: Mapping[str, Any], source_json: str = "") -> AggregationResult:
    """
    Aggregate identical meanings per sentence and normalize scores so that
    the per-sentence score sum becomes 1.

    Supported input schemas:
      1) The JSON produced by Canonicalization.py in this project.
      2) A simplified schema whose candidates already contain `semantics` and `score`.

    For STL_conversion.py output, only candidates with `kept == True`, `converted == True`,
    and a non-empty `stl` string are aggregated.
    For generic input, a candidate is aggregated when it has a non-empty `stl` (or fallback
    semantics string) and a valid positive score.
    """

    sentences_data = data.get("sentences")
    if not isinstance(sentences_data, list):
        raise ValueError("Input JSON must contain a top-level 'sentences' list.")

    source_metadata = {
        key: value for key, value in data.items() if key not in {"sentences", "summary", "source_json"}
    }

    sentences: List[SentenceAggregationResult] = []
    for sentence_index, sentence_data in enumerate(sentences_data):
        if not isinstance(sentence_data, Mapping):
            raise ValueError(f"Each sentence must be a JSON object, but got: {type(sentence_data)!r}")
        sentences.append(aggregate_sentence(sentence_data, sentence_index=sentence_index))

    return AggregationResult(
        source_json=source_json,
        sentences=sentences,
        source_metadata=source_metadata,
    )


def aggregate_sentence(sentence_data: Mapping[str, Any], sentence_index: int) -> SentenceAggregationResult:
    sentence_id = str(sentence_data.get("sentence_id") or f"s{sentence_index}")
    surface = str(sentence_data.get("surface") or "")
    input_candidates = sentence_data.get("candidates") or []

    if not isinstance(input_candidates, list):
        raise ValueError(
            f"Sentence {sentence_id} has invalid 'candidates': expected list, got {type(input_candidates)!r}"
        )

    grouped: MutableMapping[str, AggregatedCandidate] = {}
    skip_reason_counts: Dict[str, int] = {}
    eligible_candidates = 0

    for candidate_index, candidate in enumerate(input_candidates):
        parsed, skip_reason = _parse_candidate(candidate, candidate_index)
        if parsed is None:
            skip_reason_counts[skip_reason] = skip_reason_counts.get(skip_reason, 0) + 1
            continue

        eligible_candidates += 1
        semantics = parsed.canonical_semantics
        if semantics not in grouped:
            grouped[semantics] = AggregatedCandidate(
                candidate_index=len(grouped),
                canonical_semantics=semantics,
                aggregated_score=0.0,
                score=0.0,
                source_count=0,
                source_candidates=[],
            )

        aggregated = grouped[semantics]
        aggregated.aggregated_score += parsed.score
        aggregated.source_count += 1
        aggregated.source_candidates.append(parsed)

    normalization_total = sum(candidate.aggregated_score for candidate in grouped.values())
    candidates = list(grouped.values())

    if normalization_total > 0.0:
        for aggregated in candidates:
            aggregated.score = aggregated.aggregated_score / normalization_total
        if candidates:
            correction = 1.0 - sum(candidate.score for candidate in candidates)
            candidates[-1].score += correction
    else:
        for aggregated in candidates:
            aggregated.score = 0.0

    score_sum = sum(candidate.score for candidate in candidates)

    return SentenceAggregationResult(
        sentence_index=_safe_int(sentence_data.get("sentence_index"), default=sentence_index),
        sentence_id=sentence_id,
        surface=surface,
        total_input_candidates=len(input_candidates),
        eligible_candidates=eligible_candidates,
        skipped_candidates=len(input_candidates) - eligible_candidates,
        skip_reason_counts=skip_reason_counts,
        normalization_total=normalization_total,
        score_sum=score_sum,
        candidates=candidates,
    )


def _parse_candidate(candidate: Any, candidate_index: int) -> Tuple[Optional[SourceCandidate], str]:
    if not isinstance(candidate, Mapping):
        return None, "invalid_candidate_type"

    if "kept" in candidate and not bool(candidate.get("kept")):
        return None, "not_kept"

    if "converted" in candidate and not bool(candidate.get("converted")):
        return None, "not_converted"

    semantics = candidate.get("stl")
    if semantics is None:
        semantics = candidate.get("canonical_semantics")
    if semantics is None:
        semantics = candidate.get("semantics")
    if not isinstance(semantics, str) or not semantics.strip():
        return None, "missing_stl"
    semantics = semantics.strip()

    score_value = candidate.get("score")
    try:
        score = float(score_value)
    except (TypeError, ValueError):
        return None, "invalid_score"

    if math.isnan(score) or math.isinf(score) or score <= 0.0:
        return None, "invalid_score"

    original_score_value = candidate.get("original_score")
    if original_score_value is None:
        original_score_value = candidate.get("log_score")
    original_score = _maybe_float(original_score_value)

    parse_index = candidate.get("ccg_index")
    if parse_index is None:
        parse_index = candidate.get("parse_index")

    return (
        SourceCandidate(
            candidate_index=candidate_index,
            parse_index=_safe_int(parse_index),
            ccg_id=_maybe_str(candidate.get("ccg_id")),
            canonical_semantics=semantics,
            score=score,
            original_score=original_score,
        ),
        "",
    )


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _maybe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _maybe_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate identical meanings per sentence and normalize their scores so that "
            "the per-sentence score sum becomes 1."
        )
    )
    parser.add_argument("input_json", help="Input JSON file. Typically the output of Canonicalization.py.")
    parser.add_argument("output_json", help="Output JSON file.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    result = aggregate_json(args.input_json)
    save_result(result, args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
