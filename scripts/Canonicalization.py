from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional, Sequence, Tuple, Union

from lxml import etree


PathLike = Union[str, Path]

# Matches identifiers that look like function/predicate names in expressions such as
# F(...), AP(...), foo(...), 停止(...)
FUNCTION_CALL_RE = re.compile(r"(?u)([^\W\d]\w*)\s*(?=\()")
NUMERIC_LITERAL_RE = re.compile(r"\d+")

DEFAULT_ALLOWED_FUNCTIONS: Tuple[str, ...] = ("F", "G", "I", "AP", "SEQ")
DEFAULT_SCORE_THRESHOLD = 0


@dataclass
class MeaningCandidate:
    """A sentence-level candidate aligned to one parse tree (<ccg> node)."""

    sentence_index: int
    sentence_id: str
    surface: str
    ccg_index: int
    ccg_id: str
    semantics_index: Optional[int]
    semantics_status: Optional[str]
    root_span_id: Optional[str]
    original_semantics: Optional[str]
    canonical_semantics: Optional[str]
    original_score: Optional[float]
    score: Optional[float]
    detected_functions: List[str] = field(default_factory=list)
    disallowed_functions: List[str] = field(default_factory=list)
    kept: bool = False
    reasons: List[str] = field(default_factory=list)


@dataclass
class SentenceCanonicalizationResult:
    sentence_index: int
    sentence_id: str
    surface: str
    candidates: List[MeaningCandidate] = field(default_factory=list)

    @property
    def kept_candidates(self) -> List[MeaningCandidate]:
        return [candidate for candidate in self.candidates if candidate.kept]


@dataclass
class CanonicalizationResult:
    source_xml: str
    allowed_functions: List[str]
    score_threshold: float
    sentences: List[SentenceCanonicalizationResult]

    @property
    def summary(self) -> Dict[str, int]:
        total_candidates = sum(len(sentence.candidates) for sentence in self.sentences)
        kept_candidates = sum(
            1 for sentence in self.sentences for candidate in sentence.candidates if candidate.kept
        )
        return {
            "total_sentences": len(self.sentences),
            "total_candidates": total_candidates,
            "kept_candidates": kept_candidates,
            "removed_candidates": total_candidates - kept_candidates,
        }

    def to_dict(self) -> Dict[str, object]:
        return {
            "source_xml": self.source_xml,
            "settings": {
                "allowed_functions": list(self.allowed_functions),
                "score_threshold": self.score_threshold,
            },
            "summary": self.summary,
            "sentences": [asdict(sentence) for sentence in self.sentences],
        }


@dataclass
class ParsedCall:
    name: str
    args: List[str]


class ParseError(ValueError):
    pass


class Expr:
    pass


@dataclass
class AtomExpr(Expr):
    value: str


@dataclass
class FuncExpr(Expr):
    name: str
    args: List[Expr]


@dataclass
class UnaryExpr(Expr):
    op: str
    operand: Expr


@dataclass
class BinaryExpr(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    position: int


class _ExprParser:
    def __init__(self, text: str):
        self.text = text
        self.tokens = self._tokenize(text)
        self.index = 0

    @staticmethod
    def _tokenize(text: str) -> List[Token]:
        tokens: List[Token] = []
        i = 0
        while i < len(text):
            ch = text[i]
            if ch.isspace():
                i += 1
                continue
            if ch in '(),&|-':
                tokens.append(Token(ch, ch, i))
                i += 1
                continue
            if ch.isdigit():
                start = i
                i += 1
                while i < len(text) and text[i].isdigit():
                    i += 1
                if i < len(text) and text[i] == '.':
                    i += 1
                    while i < len(text) and text[i].isdigit():
                        i += 1
                tokens.append(Token('ATOM', text[start:i], start))
                continue
            if ch.isalpha() or ch == '_':
                start = i
                i += 1
                while i < len(text) and (text[i].isalnum() or text[i] == '_'):
                    i += 1
                tokens.append(Token('ATOM', text[start:i], start))
                continue
            raise ParseError(f'Unsupported character {ch!r} at position {i}.')
        tokens.append(Token('EOF', '', len(text)))
        return tokens

    def _current(self) -> Token:
        return self.tokens[self.index]

    def _accept(self, kind: str) -> Optional[Token]:
        tok = self._current()
        if tok.kind == kind:
            self.index += 1
            return tok
        return None

    def _expect(self, kind: str) -> Token:
        tok = self._accept(kind)
        if tok is None:
            cur = self._current()
            raise ParseError(f'Expected {kind!r} at position {cur.position}, found {cur.kind!r}.')
        return tok

    def parse(self) -> Expr:
        expr = self._parse_or()
        self._expect('EOF')
        return expr

    def _parse_or(self) -> Expr:
        node = self._parse_and()
        while self._accept('|') is not None:
            node = BinaryExpr('|', node, self._parse_and())
        return node

    def _parse_and(self) -> Expr:
        node = self._parse_unary()
        while self._accept('&') is not None:
            node = BinaryExpr('&', node, self._parse_unary())
        return node

    def _parse_unary(self) -> Expr:
        if self._accept('-') is not None:
            return UnaryExpr('-', self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        if self._accept('(') is not None:
            expr = self._parse_or()
            self._expect(')')
            return expr
        tok = self._expect('ATOM')
        if self._accept('(') is not None:
            args: List[Expr] = []
            if self._current().kind != ')':
                while True:
                    args.append(self._parse_or())
                    if self._accept(',') is None:
                        break
            self._expect(')')
            return FuncExpr(tok.value, args)
        return AtomExpr(tok.value)


def _parse_expression(text: str) -> Expr:
    return _ExprParser(text).parse()


def _serialize_expr(expr: Expr) -> str:
    if isinstance(expr, AtomExpr):
        return expr.value
    if isinstance(expr, FuncExpr):
        return f"{expr.name}({', '.join(_serialize_expr(a) for a in expr.args)})"
    if isinstance(expr, UnaryExpr):
        child = _serialize_expr(expr.operand)
        if isinstance(expr.operand, BinaryExpr):
            return f"-{child if child.startswith('(') else '(' + child + ')'}"
        return f"-{child}"
    if isinstance(expr, BinaryExpr):
        left = _serialize_expr(expr.left)
        right = _serialize_expr(expr.right)
        if isinstance(expr.left, BinaryExpr) and expr.left.op != expr.op:
            left = f"({left})"
        if isinstance(expr.right, BinaryExpr) and expr.right.op != expr.op:
            right = f"({right})"
        return f"{left} {expr.op} {right}"
    raise TypeError(type(expr))


def _collect_calls(expr: Expr, out: List[ParsedCall]) -> None:
    if isinstance(expr, FuncExpr):
        out.append(ParsedCall(expr.name, [_serialize_expr(arg) for arg in expr.args]))
        for arg in expr.args:
            _collect_calls(arg, out)
    elif isinstance(expr, UnaryExpr):
        _collect_calls(expr.operand, out)
    elif isinstance(expr, BinaryExpr):
        _collect_calls(expr.left, out)
        _collect_calls(expr.right, out)


def parse_function_calls(expression: str) -> Optional[List[ParsedCall]]:
    try:
        expr = _parse_expression(expression)
    except ParseError:
        return None
    out: List[ParsedCall] = []
    _collect_calls(expr, out)
    return out


def _expr_contains_only_allowed_fg_forms(expr: Expr) -> bool:
    if isinstance(expr, AtomExpr):
        return expr.value == 'SAME'
    if isinstance(expr, UnaryExpr):
        return expr.op == '-' and _expr_contains_only_allowed_fg_forms(expr.operand)
    if isinstance(expr, BinaryExpr):
        return _expr_contains_only_allowed_fg_forms(expr.left) and _expr_contains_only_allowed_fg_forms(expr.right)
    if isinstance(expr, FuncExpr):
        return expr.name in {'AP', 'I'}
    return False


def _fg_direct_arg_is_allowed(arg_text: str) -> bool:
    stripped = (arg_text or '').strip()
    if not stripped:
        return False
    try:
        expr = _parse_expression(stripped)
    except ParseError:
        return False
    return _expr_contains_only_allowed_fg_forms(expr)


def _contains_standalone_I(expr: Expr, inside_fg_arguments: bool = False) -> bool:
    if isinstance(expr, AtomExpr):
        return False
    if isinstance(expr, UnaryExpr):
        return _contains_standalone_I(expr.operand, inside_fg_arguments)
    if isinstance(expr, BinaryExpr):
        return _contains_standalone_I(expr.left, inside_fg_arguments) or _contains_standalone_I(
            expr.right, inside_fg_arguments
        )
    if isinstance(expr, FuncExpr):
        if expr.name == 'I' and not inside_fg_arguments:
            return True
        next_inside = inside_fg_arguments or expr.name in {'F', 'G'}
        return any(_contains_standalone_I(arg, next_inside) for arg in expr.args)
    return False


def load_xml(xml_path: PathLike) -> etree._ElementTree:
    parser = etree.XMLParser(remove_blank_text=True)
    return etree.parse(str(xml_path), parser)


def save_result(result: CanonicalizationResult, output_json_path: PathLike) -> None:
    output_path = Path(output_json_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fout:
        json.dump(result.to_dict(), fout, ensure_ascii=False, indent=2)


def canonicalize_xml(
    xml_path: PathLike,
    allowed_functions: Sequence[str] = DEFAULT_ALLOWED_FUNCTIONS,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> CanonicalizationResult:
    """
    Read a ccg2lambda/depccg semantic XML file and keep only candidates that satisfy:
      1) after underscore removal, every detected function call name is in allowed_functions
      2) exp(score) >= score_threshold

    The function returns sentence-grouped results aligned with each <ccg> tree.
    """

    tree = load_xml(xml_path)
    sentences = tree.findall(".//sentence")
    results = [
        canonicalize_sentence(
            sentence_node,
            sentence_index=sentence_index,
            allowed_functions=allowed_functions,
            score_threshold=score_threshold,
        )
        for sentence_index, sentence_node in enumerate(sentences)
    ]
    return CanonicalizationResult(
        source_xml=str(xml_path),
        allowed_functions=list(allowed_functions),
        score_threshold=score_threshold,
        sentences=results,
    )


def canonicalize_sentence(
    sentence_node: etree._Element,
    sentence_index: int,
    allowed_functions: Sequence[str] = DEFAULT_ALLOWED_FUNCTIONS,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> SentenceCanonicalizationResult:
    """Canonicalize one <sentence> node."""

    sentence_id = sentence_node.get("id") or f"s{sentence_index}"
    surface = _extract_surface(sentence_node)
    ccg_nodes = sentence_node.findall("./ccg")
    semantics_nodes = sentence_node.findall("./semantics")

    matched_semantics = _match_semantics_to_ccgs(ccg_nodes, semantics_nodes)

    candidates: List[MeaningCandidate] = []
    for ccg_index, ccg_node in enumerate(ccg_nodes):
        ccg_id = ccg_node.get("id") or f"{sentence_id}_ccg{ccg_index}"
        semantics_index, semantics_node = matched_semantics.get(ccg_index, (None, None))
        candidates.append(
            _canonicalize_candidate(
                sentence_index=sentence_index,
                sentence_id=sentence_id,
                surface=surface,
                ccg_index=ccg_index,
                ccg_id=ccg_id,
                ccg_node=ccg_node,
                semantics_index=semantics_index,
                semantics_node=semantics_node,
                allowed_functions=allowed_functions,
                score_threshold=score_threshold,
            )
        )

    return SentenceCanonicalizationResult(
        sentence_index=sentence_index,
        sentence_id=sentence_id,
        surface=surface,
        candidates=candidates,
    )


def _extract_surface(sentence_node: etree._Element) -> str:
    token_surfaces = sentence_node.xpath("./tokens/token/@surf")
    if token_surfaces:
        return " ".join(token_surfaces)

    token_bases = sentence_node.xpath("./tokens/token/@base")
    if token_bases:
        return " ".join(token_bases)

    token_text = [token.text for token in sentence_node.findall("./tokens/token") if token.text]
    if token_text:
        return " ".join(token_text)

    return ""


def _match_semantics_to_ccgs(
    ccg_nodes: Sequence[etree._Element],
    semantics_nodes: Sequence[etree._Element],
) -> Dict[int, Tuple[Optional[int], Optional[etree._Element]]]:
    """
    Match <semantics> nodes to <ccg> nodes.

    Preferred strategy:
      - Use semantics/@ccg_id when it exists.
      - Fallback to remaining semantics in document order.
    """

    ccg_id_to_index: Dict[str, int] = {}
    for index, ccg_node in enumerate(ccg_nodes):
        ccg_id = ccg_node.get("id")
        if ccg_id:
            ccg_id_to_index[ccg_id] = index

    semantics_by_ccg_id: Dict[str, Deque[Tuple[int, etree._Element]]] = defaultdict(deque)
    fallback_semantics: Deque[Tuple[int, etree._Element]] = deque()

    for semantics_index, semantics_node in enumerate(semantics_nodes):
        ccg_id = semantics_node.get("ccg_id")
        if ccg_id and ccg_id in ccg_id_to_index:
            semantics_by_ccg_id[ccg_id].append((semantics_index, semantics_node))
        else:
            fallback_semantics.append((semantics_index, semantics_node))

    matched: Dict[int, Tuple[Optional[int], Optional[etree._Element]]] = {}
    for ccg_index, ccg_node in enumerate(ccg_nodes):
        ccg_id = ccg_node.get("id")
        if ccg_id and semantics_by_ccg_id.get(ccg_id):
            matched[ccg_index] = semantics_by_ccg_id[ccg_id].popleft()
        elif fallback_semantics:
            matched[ccg_index] = fallback_semantics.popleft()
        else:
            matched[ccg_index] = (None, None)

    return matched


def _canonicalize_candidate(
    *,
    sentence_index: int,
    sentence_id: str,
    surface: str,
    ccg_index: int,
    ccg_id: str,
    ccg_node: etree._Element,
    semantics_index: Optional[int],
    semantics_node: Optional[etree._Element],
    allowed_functions: Sequence[str],
    score_threshold: float,
) -> MeaningCandidate:
    candidate = MeaningCandidate(
        sentence_index=sentence_index,
        sentence_id=sentence_id,
        surface=surface,
        ccg_index=ccg_index,
        ccg_id=ccg_id,
        semantics_index=semantics_index,
        semantics_status=(semantics_node.get("status") if semantics_node is not None else None),
        root_span_id=(semantics_node.get("root") if semantics_node is not None else None),
        original_semantics=None,
        canonical_semantics=None,
        original_score=None,
        score=None,
        detected_functions=[],
        disallowed_functions=[],
        kept=False,
        reasons=[],
    )

    score_text = ccg_node.get("score")
    if score_text is None:
        candidate.reasons.append("missing_score")
    else:
        try:
            candidate.original_score = float(score_text)
            candidate.score = math.exp(candidate.original_score)
        except (TypeError, ValueError, OverflowError):
            candidate.reasons.append("invalid_score")

    if semantics_node is None:
        candidate.reasons.append("missing_semantics")
        return candidate

    status = (semantics_node.get("status") or "").lower().strip()
    if status and status != "success":
        candidate.reasons.append(f"semantics_status:{status}")
        return candidate

    root_span = _find_root_span(semantics_node)
    if root_span is None:
        candidate.reasons.append("missing_root_span")
        return candidate

    candidate.root_span_id = root_span.get("id") or candidate.root_span_id
    final_semantics = root_span.get("sem")
    if not final_semantics:
        candidate.reasons.append("missing_final_semantics")
        return candidate

    candidate.original_semantics = final_semantics.strip()
    candidate.canonical_semantics = remove_underscores(candidate.original_semantics)

    call_infos = parse_function_calls(candidate.canonical_semantics)
    if call_infos is None:
        candidate.reasons.append("malformed_semantics")
        return candidate

    candidate.detected_functions = sorted({call.name for call in call_infos})
    allowed_set = set(allowed_functions)
    candidate.disallowed_functions = sorted({call.name for call in call_infos if call.name not in allowed_set})
    if candidate.disallowed_functions:
        candidate.reasons.append("disallowed_functions")

    if any(len(call.args) >= 3 for call in call_infos):
        candidate.reasons.append("function_with_arity_gte_3")

    invalid_i_numeric = False
    invalid_i_arity = False
    invalid_fg_direct_args = False
    standalone_i_outside_fg_arguments = False
    parsed_expr = _parse_expression(candidate.canonical_semantics)
    for call in call_infos:
        if call.name == "I":
            if len(call.args) != 2:
                invalid_i_arity = True
            elif not all(re.fullmatch(r"\d+", arg.strip() or "") for arg in call.args):
                invalid_i_numeric = True
        elif call.name in {"F", "G"}:
            for arg in call.args:
                if not _fg_direct_arg_is_allowed(arg):
                    invalid_fg_direct_args = True
                    break
    if _contains_standalone_I(parsed_expr):
        standalone_i_outside_fg_arguments = True

    if invalid_i_numeric:
        candidate.reasons.append("non_numeric_I_arguments")
    if invalid_i_arity:
        candidate.reasons.append("I_arity_not_2")
    if invalid_fg_direct_args:
        candidate.reasons.append("FG_direct_args_contain_disallowed_functions")
    if standalone_i_outside_fg_arguments:
        candidate.reasons.append("standalone_I_outside_FG_arguments")

    if candidate.score is None:
        if "missing_score" not in candidate.reasons and "invalid_score" not in candidate.reasons:
            candidate.reasons.append("missing_score")
    elif candidate.score < score_threshold:
        candidate.reasons.append("score_below_threshold")

    candidate.kept = not candidate.reasons
    return candidate


def _find_root_span(semantics_node: etree._Element) -> Optional[etree._Element]:
    root_span_id = semantics_node.get("root")
    spans = semantics_node.findall("./span")
    if not spans:
        return None

    if root_span_id:
        for span in spans:
            if span.get("id") == root_span_id:
                return span

    # Conservative fallback for malformed inputs that do not set semantics/@root.
    return spans[0]


def remove_underscores(semantics: str) -> str:
    return semantics.replace("_", "").strip()


def find_function_calls(expression: str) -> List[str]:
    return FUNCTION_CALL_RE.findall(expression)


def result_from_json(json_path: PathLike) -> Dict[str, object]:
    with Path(json_path).open("r", encoding="utf-8") as fin:
        return json.load(fin)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract the final semantics of each parse tree from a ccg2lambda XML file, "
            "remove underscores, convert scores with exp(score), and filter out "
            "candidates that contain disallowed function names or whose score is below "
            "the threshold."
        )
    )
    parser.add_argument("input_xml", help="Input XML file produced by ccg2lambda/depccg.")
    parser.add_argument("output_json", help="Output JSON file.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_SCORE_THRESHOLD,
        help=f"Keep only candidates with exp(score) >= threshold (default: {DEFAULT_SCORE_THRESHOLD}).",
    )
    parser.add_argument(
        "--allowed-functions",
        nargs="+",
        default=list(DEFAULT_ALLOWED_FUNCTIONS),
        help=f"Allowed function names after underscore removal (default: {' '.join(DEFAULT_ALLOWED_FUNCTIONS)}).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    result = canonicalize_xml(
        args.input_xml,
        allowed_functions=args.allowed_functions,
        score_threshold=args.threshold,
    )
    save_result(result, args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
