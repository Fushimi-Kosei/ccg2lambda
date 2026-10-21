from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent


def _find_script(filename_candidates: Sequence[str]) -> Path:
    for filename in filename_candidates:
        path = SCRIPT_DIR / filename
        if path.exists():
            return path
    searched = ", ".join(str(SCRIPT_DIR / name) for name in filename_candidates)
    raise FileNotFoundError(f"Required script not found. Looked for: {searched}")


def _run_script(script_path: Path, *args: str) -> None:
    command = [sys.executable, str(script_path), *args]
    subprocess.run(command, check=True)


def _load_json(json_path: Path) -> Dict[str, Any]:
    with json_path.open("r", encoding="utf-8") as fin:
        data = json.load(fin)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {json_path}, but got {type(data)!r}.")
    return data


def _candidate_to_minimal(candidate: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    stl = candidate.get("stl")
    if not isinstance(stl, str) or not stl.strip():
        stl = candidate.get("canonical_semantics")
    if not isinstance(stl, str) or not stl.strip():
        source_candidates = candidate.get("source_candidates")
        if isinstance(source_candidates, list) and source_candidates:
            first = source_candidates[0]
            if isinstance(first, Mapping):
                fallback = first.get("stl")
                if not isinstance(fallback, str) or not fallback.strip():
                    fallback = first.get("canonical_semantics")
                if isinstance(fallback, str) and fallback.strip():
                    stl = fallback

    if not isinstance(stl, str) or not stl.strip():
        return None

    score_value = candidate.get("score")
    try:
        score = float(score_value)
    except (TypeError, ValueError):
        return None

    return {
        "stl": stl.strip(),
        "score": score,
    }


def _extract_minimal_output(aggregation_output: Mapping[str, Any]) -> Dict[str, Any]:
    sentences = aggregation_output.get("sentences")
    if not isinstance(sentences, list):
        raise ValueError("Aggregation output does not contain a valid top-level 'sentences' list.")

    result_sentences = []
    for sentence in sentences:
        if not isinstance(sentence, Mapping):
            raise ValueError(f"Invalid sentence entry in aggregation output: {type(sentence)!r}")

        sentence_text = sentence.get("surface")
        if not isinstance(sentence_text, str):
            sentence_text = ""

        candidates = sentence.get("candidates")
        if not isinstance(candidates, list):
            raise ValueError("Each sentence in aggregation output must contain a 'candidates' list.")

        minimal_candidates = []
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                minimal = _candidate_to_minimal(candidate)
                if minimal is not None:
                    minimal_candidates.append(minimal)

        result_sentences.append(
            {
                "sentence": sentence_text,
                "candidates": minimal_candidates,
            }
        )

    return {"sentences": result_sentences}


def build_minimal_stl_json(input_xml: Path) -> Dict[str, Any]:
    canonicalization_script = _find_script(["Canonicalization.py"])
    stl_conversion_script = _find_script(["STL_conversion.py", "stl_conversion.py"])
    aggregation_script = _find_script(["Aggregation.py"])

    with tempfile.TemporaryDirectory(prefix="stl_json_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        canonicalized_json = tmp_dir / "canonicalized.json"
        stl_json = tmp_dir / "stl_converted.json"
        aggregated_json = tmp_dir / "aggregated.json"

        _run_script(canonicalization_script, str(input_xml), str(canonicalized_json))
        _run_script(stl_conversion_script, str(canonicalized_json), str(stl_json))
        _run_script(aggregation_script, str(stl_json), str(aggregated_json))

        aggregation_output = _load_json(aggregated_json)

    return _extract_minimal_output(aggregation_output)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run Canonicalization.py, STL_conversion.py, and Aggregation.py in sequence and "
            "print a minimal JSON that contains only each input sentence and its final STL "
            "candidates with final normalized scores."
        )
    )
    parser.add_argument("input_xml", help="Input XML file produced by ccg2lambda/depccg.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    output = build_minimal_stl_json(Path(args.input_xml))
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
