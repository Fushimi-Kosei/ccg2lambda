from __future__ import annotations

import argparse
import copy
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union


PathLike = Union[str, Path]


# ---------------------------------------------------------------------------
# AST definitions
# ---------------------------------------------------------------------------


class ParseError(ValueError):
    """Raised when the semantics string cannot be parsed."""


class Expr:
    """Base class for all AST nodes."""


@dataclass
class Atom(Expr):
    value: str


@dataclass
class Func(Expr):
    name: str
    args: List[Expr] = field(default_factory=list)


@dataclass
class Unary(Expr):
    op: str
    operand: Expr


@dataclass
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class IntervalSummary:
    lower: str
    upper: str


# ---------------------------------------------------------------------------
# Tokenizer / parser
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    position: int


class SemanticsParser:
    """Recursive-descent parser for the limited semantics language used here."""

    def __init__(self, text: str):
        self.text = text
        self.tokens = self._tokenize(text)
        self.index = 0

    @staticmethod
    def _tokenize(text: str) -> List[Token]:
        tokens: List[Token] = []
        i = 0
        length = len(text)
        while i < length:
            ch = text[i]
            if ch.isspace():
                i += 1
                continue
            if ch in "(),&|-":
                tokens.append(Token(kind=ch, value=ch, position=i))
                i += 1
                continue
            if ch.isdigit():
                start = i
                i += 1
                while i < length and text[i].isdigit():
                    i += 1
                if i < length and text[i] == ".":
                    i += 1
                    while i < length and text[i].isdigit():
                        i += 1
                tokens.append(Token(kind="ATOM", value=text[start:i], position=start))
                continue
            if ch.isalpha() or ch == "_":
                start = i
                i += 1
                while i < length and (text[i].isalnum() or text[i] == "_"):
                    i += 1
                tokens.append(Token(kind="ATOM", value=text[start:i], position=start))
                continue
            raise ParseError(f"Unsupported character {ch!r} at position {i}.")

        tokens.append(Token(kind="EOF", value="", position=length))
        return tokens

    def parse(self) -> Expr:
        expr = self._parse_or()
        self._expect("EOF")
        return expr

    def _current(self) -> Token:
        return self.tokens[self.index]

    def _accept(self, kind: str) -> Optional[Token]:
        token = self._current()
        if token.kind == kind:
            self.index += 1
            return token
        return None

    def _expect(self, kind: str) -> Token:
        token = self._accept(kind)
        if token is None:
            current = self._current()
            raise ParseError(
                f"Expected token {kind!r} at position {current.position}, found {current.kind!r}."
            )
        return token

    def _parse_or(self) -> Expr:
        node = self._parse_and()
        while self._accept("|") is not None:
            node = Binary(op="|", left=node, right=self._parse_and())
        return node

    def _parse_and(self) -> Expr:
        node = self._parse_unary()
        while self._accept("&") is not None:
            node = Binary(op="&", left=node, right=self._parse_unary())
        return node

    def _parse_unary(self) -> Expr:
        if self._accept("-") is not None:
            return Unary(op="-", operand=self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        if self._accept("(") is not None:
            expr = self._parse_or()
            self._expect(")")
            return expr

        token = self._expect("ATOM")
        atom_text = token.value
        if self._accept("(") is not None:
            args: List[Expr] = []
            if self._current().kind != ")":
                while True:
                    args.append(self._parse_or())
                    if self._accept(",") is None:
                        break
            self._expect(")")
            return Func(name=atom_text, args=args)
        return Atom(value=atom_text)


# ---------------------------------------------------------------------------
# Generic AST utilities
# ---------------------------------------------------------------------------


def parse_semantics(text: str) -> Expr:
    return SemanticsParser(text).parse()


def clone_expr(expr: Expr) -> Expr:
    return copy.deepcopy(expr)


def iter_children(expr: Expr) -> Iterable[Expr]:
    if isinstance(expr, Binary):
        yield expr.left
        yield expr.right
    elif isinstance(expr, Unary):
        yield expr.operand
    elif isinstance(expr, Func):
        yield from expr.args


def ascii_precedence(expr: Expr) -> int:
    if isinstance(expr, Binary):
        return 1 if expr.op == "|" else 2
    if isinstance(expr, Unary):
        return 3
    return 4


def _ascii_serialize_func_arg(arg: Expr) -> str:
    text = serialize_ascii(arg)
    if isinstance(arg, Binary):
        return f"({text})"
    return text


def _serialize_ascii_binary_child(parent_op: str, child: Expr, *, is_right_child: bool) -> str:
    base_text = serialize_ascii(child)
    if not isinstance(child, Binary):
        return base_text

    parent_precedence = 1 if parent_op == "|" else 2
    child_precedence = ascii_precedence(child)
    required_precedence = child_precedence < (parent_precedence + (1 if is_right_child else 0))
    required_grouping = child.op != parent_op
    if required_precedence or required_grouping:
        return f"({base_text})"
    return base_text


def serialize_ascii(expr: Expr, parent_precedence: int = 0) -> str:
    if isinstance(expr, Atom):
        return expr.value

    if isinstance(expr, Func):
        if expr.name == "I":
            joined = ",".join(serialize_ascii(arg) for arg in expr.args)
            return f"{expr.name}({joined})"
        joined = ", ".join(_ascii_serialize_func_arg(arg) for arg in expr.args)
        return f"{expr.name}({joined})"

    if isinstance(expr, Unary):
        child = expr.operand
        if isinstance(child, Binary):
            text = f"{expr.op}({serialize_ascii(child)})"
        else:
            text = f"{expr.op}{serialize_ascii(child, ascii_precedence(expr))}"
        if ascii_precedence(expr) < parent_precedence:
            return f"({text})"
        return text

    if isinstance(expr, Binary):
        precedence = ascii_precedence(expr)
        left_text = _serialize_ascii_binary_child(expr.op, expr.left, is_right_child=False)
        right_text = _serialize_ascii_binary_child(expr.op, expr.right, is_right_child=True)
        text = f"{left_text} {expr.op} {right_text}"
        if precedence < parent_precedence:
            return f"({text})"
        return text

    raise TypeError(f"Unsupported expression node: {type(expr)!r}")


def build_parent_map(expr: Expr) -> Dict[int, Optional[Expr]]:
    parent_map: Dict[int, Optional[Expr]] = {id(expr): None}

    def _visit(node: Expr) -> None:
        for child in iter_children(node):
            parent_map[id(child)] = node
            _visit(child)

    _visit(expr)
    return parent_map


def traverse(expr: Expr) -> Iterable[Expr]:
    yield expr
    for child in iter_children(expr):
        yield from traverse(child)


# ---------------------------------------------------------------------------
# SAME substitution support
# ---------------------------------------------------------------------------


_NUMERIC_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


def _parse_decimal(text: str) -> Optional[Decimal]:
    stripped = text.strip()
    if not _NUMERIC_RE.fullmatch(stripped):
        return None
    try:
        return Decimal(stripped)
    except InvalidOperation:
        return None


def _format_decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _combine_min(a: str, b: str) -> str:
    da = _parse_decimal(a)
    db = _parse_decimal(b)
    if da is not None and db is not None:
        return _format_decimal(da if da <= db else db)
    if a == b:
        return a
    return f"min({a}, {b})"


def _combine_max(a: str, b: str) -> str:
    da = _parse_decimal(a)
    db = _parse_decimal(b)
    if da is not None and db is not None:
        return _format_decimal(da if da >= db else db)
    if a == b:
        return a
    return f"max({a}, {b})"


def _combine_sum(a: str, b: str) -> str:
    da = _parse_decimal(a)
    db = _parse_decimal(b)
    if da is not None and db is not None:
        return _format_decimal(da + db)
    if a == "0":
        return b
    if b == "0":
        return a
    return f"({a}+{b})"


def _is_same_atom(expr: Expr) -> bool:
    return isinstance(expr, Atom) and expr.value == "SAME"


def _contains_same_for_target(expr: Expr) -> bool:
    if _is_same_atom(expr):
        return True
    if isinstance(expr, Unary):
        return _contains_same_for_target(expr.operand)
    if isinstance(expr, Binary):
        return _contains_same_for_target(expr.left) or _contains_same_for_target(expr.right)
    if isinstance(expr, Func):
        if expr.name == "I":
            return any(_contains_same_for_target(arg) for arg in expr.args)
        # Do not descend into other function calls here, so nested functions that
        # contain SAME are handled by those nested functions themselves.
        return False
    return False


def _replace_same_in_target_arg(expr: Expr, replacement: Expr) -> Expr:
    if _is_same_atom(expr):
        return clone_expr(replacement)
    if isinstance(expr, Unary):
        expr.operand = _replace_same_in_target_arg(expr.operand, replacement)
        return expr
    if isinstance(expr, Binary):
        expr.left = _replace_same_in_target_arg(expr.left, replacement)
        expr.right = _replace_same_in_target_arg(expr.right, replacement)
        return expr
    if isinstance(expr, Func) and expr.name == "I":
        expr.args = [_replace_same_in_target_arg(arg, replacement) for arg in expr.args]
        return expr
    return expr


def is_same_target_function(expr: Expr) -> bool:
    return isinstance(expr, Func) and any(_contains_same_for_target(arg) for arg in expr.args)


def collect_same_targets(expr: Expr) -> List[Tuple[int, Func]]:
    targets: List[Tuple[int, Func]] = []

    def _visit(node: Expr, depth: int) -> None:
        if isinstance(node, Func) and is_same_target_function(node):
            targets.append((depth, node))
        for child in iter_children(node):
            _visit(child, depth + 1)

    _visit(expr, 0)
    # Process inner targets first, as requested in the specification.
    targets.sort(key=lambda item: item[0], reverse=True)
    return targets


def _find_interval_node(expr: Expr) -> Optional[Func]:
    if isinstance(expr, Func) and expr.name == "I" and len(expr.args) >= 2:
        return expr
    if isinstance(expr, Func):
        for arg in expr.args:
            found = _find_interval_node(arg)
            if found is not None:
                return found
        return None
    if isinstance(expr, Unary):
        return _find_interval_node(expr.operand)
    if isinstance(expr, Binary):
        found = _find_interval_node(expr.left)
        if found is not None:
            return found
        return _find_interval_node(expr.right)
    return None


def interval_summary(expr: Expr) -> Optional[IntervalSummary]:
    if isinstance(expr, Binary) and expr.op in {"&", "|"}:
        left = interval_summary(expr.left)
        right = interval_summary(expr.right)
        if left is None:
            return right
        if right is None:
            return left
        return IntervalSummary(
            lower=_combine_min(left.lower, right.lower),
            upper=_combine_max(left.upper, right.upper),
        )

    if isinstance(expr, Unary):
        return interval_summary(expr.operand)

    if isinstance(expr, Func):
        if expr.name in {"F", "G"}:
            interval_node = _find_interval_node(expr.args[0]) if expr.args else None
            if interval_node is None:
                return None
            return IntervalSummary(
                lower=serialize_ascii(interval_node.args[0]),
                upper=serialize_ascii(interval_node.args[1]),
            )

        if expr.name == "SEQ" and len(expr.args) >= 2:
            first = interval_summary(expr.args[0])
            second = interval_summary(expr.args[1])
            if first is None:
                return second
            if second is None:
                return first
            return IntervalSummary(
                lower=first.lower,
                upper=_combine_sum(first.upper, second.upper),
            )

        if expr.name == "I" and len(expr.args) >= 2:
            return IntervalSummary(
                lower=serialize_ascii(expr.args[0]),
                upper=serialize_ascii(expr.args[1]),
            )

    return None


def infer_same_interval(target: Func, parent_map: Mapping[int, Optional[Expr]]) -> Optional[IntervalSummary]:
    """Infer SAME only from expressions directly coordinated with the target.

    We look for the nearest binary coordinator (& or |) for which the SAME-target
    function itself is an immediate child, and build I(min,max) only from that
    sibling side. We intentionally do not continue climbing outer coordinators,
    because SAME must be resolved from the function(s) that are in direct
    coordination with the target.
    """
    child: Expr = target
    parent = parent_map.get(id(child))

    while parent is not None:
        if isinstance(parent, Binary) and parent.op in {"&", "|"}:
            sibling = parent.right if parent.left is child else parent.left
            return interval_summary(sibling)
        child = parent
        parent = parent_map.get(id(child))

    return None


def substitute_same(expr: Expr, warnings: List[str]) -> Expr:
    parent_map = build_parent_map(expr)
    targets = collect_same_targets(expr)

    for _, target in targets:
        inferred = infer_same_interval(target, parent_map)
        if inferred is None:
            warnings.append(
                f"SAME の時間区間を推定できなかったため、そのまま保持しました: {serialize_ascii(target)}"
            )
            continue
        replacement = Func(name="I", args=[Atom(inferred.lower), Atom(inferred.upper)])
        for index, arg in enumerate(target.args):
            if _contains_same_for_target(arg):
                target.args[index] = _replace_same_in_target_arg(arg, replacement)

    return expr


# ---------------------------------------------------------------------------
# SEQ transformation
# ---------------------------------------------------------------------------


def _contains_func_name(expr: Expr, name: str) -> bool:
    if isinstance(expr, Func):
        if expr.name == name:
            return True
        return any(_contains_func_name(arg, name) for arg in expr.args)
    if isinstance(expr, Unary):
        return _contains_func_name(expr.operand, name)
    if isinstance(expr, Binary):
        return _contains_func_name(expr.left, name) or _contains_func_name(expr.right, name)
    return False


def _flatten_seq_terms(expr: Expr) -> List[Expr]:
    if isinstance(expr, Func) and expr.name == "SEQ":
        items: List[Expr] = []
        for arg in expr.args:
            items.extend(_flatten_seq_terms(arg))
        return items
    return [expr]


def _build_right_associated_seq(items: List[Expr]) -> Expr:
    if not items:
        raise ValueError("Cannot rebuild a SEQ chain from an empty list.")
    node: Expr = items[-1]
    for item in reversed(items[:-1]):
        node = Func(name="SEQ", args=[item, node])
    return node


def right_associate_seq(expr: Expr) -> Expr:
    if isinstance(expr, Binary):
        expr.left = right_associate_seq(expr.left)
        expr.right = right_associate_seq(expr.right)
        return expr

    if isinstance(expr, Unary):
        expr.operand = right_associate_seq(expr.operand)
        return expr

    if isinstance(expr, Func):
        expr.args = [right_associate_seq(arg) for arg in expr.args]
        if expr.name != "SEQ":
            return expr

        items = _flatten_seq_terms(expr)
        if len(items) == 1:
            return items[0]
        return _build_right_associated_seq(items)

    return expr


def _is_convertible_seq_head(expr: Expr) -> bool:
    return (
        isinstance(expr, Func)
        and expr.name == "F"
        and len(expr.args) >= 2
        and _find_interval_node(expr.args[0]) is not None
    )


def _is_convertible_seq_tail(expr: Expr) -> bool:
    return not _contains_func_name(expr, "SEQ")


def convert_seq(expr: Expr, warnings: List[str]) -> Expr:
    if isinstance(expr, Binary):
        expr.left = convert_seq(expr.left, warnings)
        expr.right = convert_seq(expr.right, warnings)
        return expr

    if isinstance(expr, Unary):
        expr.operand = convert_seq(expr.operand, warnings)
        return expr

    if isinstance(expr, Func):
        expr.args = [convert_seq(arg, warnings) for arg in expr.args]
        if expr.name != "SEQ":
            return expr

        if not expr.args:
            warnings.append("空の SEQ 関数が見つかりました。")
            return expr

        if len(expr.args) == 1:
            return expr.args[0]

        if len(expr.args) != 2:
            warnings.append(
                f"2引数以外の SEQ は変換できなかったため、そのまま保持しました: {serialize_ascii(expr)}"
            )
            return expr

        first, second = expr.args
        if not _is_convertible_seq_head(first) or not _is_convertible_seq_tail(second):
            warnings.append(
                f"SEQ を指定の規則で変換できなかったため、そのまま保持しました: {serialize_ascii(expr)}"
            )
            return expr

        interval = clone_expr(first.args[0])
        body = clone_expr(first.args[1])
        continuation = clone_expr(second)
        return Func(name="F", args=[interval, Binary(op="&", left=body, right=continuation)])

    return expr


# ---------------------------------------------------------------------------
# Merge identical F/G + I under & or |
# ---------------------------------------------------------------------------


def _flatten_binary_chain(expr: Expr, op: str) -> List[Expr]:
    if isinstance(expr, Binary) and expr.op == op:
        return _flatten_binary_chain(expr.left, op) + _flatten_binary_chain(expr.right, op)
    return [expr]


def _rebuild_binary_chain(items: List[Expr], op: str) -> Expr:
    if not items:
        raise ValueError("Cannot rebuild a binary chain from an empty list.")
    node = items[0]
    for item in items[1:]:
        node = Binary(op=op, left=node, right=item)
    return node


def _extract_temporal_merge_key(expr: Expr) -> Optional[Tuple[str, str]]:
    if not isinstance(expr, Func) or expr.name not in {"F", "G"} or len(expr.args) < 2:
        return None
    interval_node = _find_interval_node(expr.args[0])
    if interval_node is None:
        return None
    return (expr.name, serialize_ascii(interval_node))


def merge_identical_temporal_functions(expr: Expr) -> Expr:
    if isinstance(expr, Binary):
        expr.left = merge_identical_temporal_functions(expr.left)
        expr.right = merge_identical_temporal_functions(expr.right)

        if expr.op not in {"&", "|"}:
            return expr

        items = _flatten_binary_chain(expr, expr.op)
        merged_items: List[Expr] = []
        key_to_index: Dict[Tuple[str, str], int] = {}
        merged_any = False

        for item in items:
            key = _extract_temporal_merge_key(item)
            if key is None:
                merged_items.append(item)
                continue

            if key not in key_to_index:
                key_to_index[key] = len(merged_items)
                merged_items.append(item)
                continue

            existing = merged_items[key_to_index[key]]
            if not isinstance(existing, Func) or len(existing.args) < 2 or not isinstance(item, Func) or len(item.args) < 2:
                merged_items.append(item)
                continue

            existing.args[1] = Binary(op=expr.op, left=existing.args[1], right=item.args[1])
            merged_any = True

        if not merged_any:
            return expr
        if len(merged_items) == 1:
            return merged_items[0]
        return _rebuild_binary_chain(merged_items, expr.op)

    if isinstance(expr, Unary):
        expr.operand = merge_identical_temporal_functions(expr.operand)
        return expr

    if isinstance(expr, Func):
        expr.args = [merge_identical_temporal_functions(arg) for arg in expr.args]
        return expr

    return expr


# ---------------------------------------------------------------------------
# STL rendering
# ---------------------------------------------------------------------------


def _is_atomic_stl_body(expr: Expr) -> bool:
    return isinstance(expr, (Atom, Func)) and not isinstance(expr, Binary) and not (
        isinstance(expr, Func) and expr.name == "SEQ"
    )


def _stl_precedence(expr: Expr) -> int:
    if isinstance(expr, Binary):
        return 1 if expr.op == "|" else 2
    if isinstance(expr, Unary):
        return 3
    return 4


def _maybe_parenthesize_stl(expr: Expr, text: str, parent_precedence: int) -> str:
    if _stl_precedence(expr) < parent_precedence:
        return f"({text})"
    return text


def _render_stl_binary_child(parent_op: str, child: Expr, *, is_right_child: bool) -> str:
    base_text = render_stl(child)
    if not isinstance(child, Binary):
        return base_text

    parent_precedence = 1 if parent_op == "|" else 2
    child_precedence = _stl_precedence(child)
    required_precedence = child_precedence < (parent_precedence + (1 if is_right_child else 0))
    required_grouping = child.op != parent_op
    if required_precedence or required_grouping:
        return f"({base_text})"
    return base_text


def _interval_bounds_text(interval_expr: Expr) -> Optional[Tuple[str, str]]:
    if isinstance(interval_expr, Func) and interval_expr.name == "I" and len(interval_expr.args) >= 2:
        return (serialize_ascii(interval_expr.args[0]), serialize_ascii(interval_expr.args[1]))
    interval_node = _find_interval_node(interval_expr)
    if interval_node is None:
        return None
    return (serialize_ascii(interval_node.args[0]), serialize_ascii(interval_node.args[1]))


def _render_ap_inner(expr: Expr, parent_precedence: int = 0) -> str:
    if isinstance(expr, Atom):
        return f"Φ_{expr.value}"

    if isinstance(expr, Unary) and expr.op == "-":
        child = expr.operand
        if isinstance(child, Binary):
            child_text = _render_ap_inner(child)
            text = f"￢({child_text})"
        else:
            text = f"￢{_render_ap_inner(child, 3)}"
        if 3 < parent_precedence:
            return f"({text})"
        return text

    if isinstance(expr, Binary) and expr.op in {"&", "|"}:
        precedence = 1 if expr.op == "|" else 2
        op_text = "∨" if expr.op == "|" else "∧"

        left_text = _render_ap_inner(expr.left, precedence)
        if isinstance(expr.left, Binary) and expr.left.op != expr.op:
            left_text = f"({left_text})"

        right_text = _render_ap_inner(expr.right, precedence)
        if isinstance(expr.right, Binary) and expr.right.op != expr.op:
            right_text = f"({right_text})"

        text = f"{left_text} {op_text} {right_text}"
        if precedence < parent_precedence:
            return f"({text})"
        return text

    return serialize_ascii(expr)


def _ap_to_stl(expr: Func) -> str:
    if len(expr.args) == 1:
        inner = _render_ap_inner(expr.args[0])
        if isinstance(expr.args[0], Binary) and expr.args[0].op in {"&", "|"}:
            return f"({inner})"
        return inner
    labels = ", ".join(_render_ap_inner(arg) for arg in expr.args)
    return f"Φ({labels})"


def render_stl(expr: Expr, parent_precedence: int = 0) -> str:
    if isinstance(expr, Atom):
        return expr.value

    if isinstance(expr, Unary):
        if isinstance(expr.operand, Binary):
            child_text = render_stl(expr.operand)
            text = f"￢({child_text})"
        else:
            child_text = render_stl(expr.operand, _stl_precedence(expr))
            text = f"￢{child_text}"
        return _maybe_parenthesize_stl(expr, text, parent_precedence)

    if isinstance(expr, Binary):
        precedence = _stl_precedence(expr)
        op_text = "∧" if expr.op == "&" else "∨"
        left_text = _render_stl_binary_child(expr.op, expr.left, is_right_child=False)
        right_text = _render_stl_binary_child(expr.op, expr.right, is_right_child=True)
        text = f"{left_text} {op_text} {right_text}"
        return _maybe_parenthesize_stl(expr, text, parent_precedence)

    if isinstance(expr, Func):
        if expr.name == "AP":
            return _ap_to_stl(expr)

        if expr.name in {"F", "G"} and len(expr.args) >= 2:
            bounds = _interval_bounds_text(expr.args[0])
            if bounds is not None:
                interval_text = f"[{bounds[0]},{bounds[1]}]"
            else:
                interval_text = f"[{serialize_ascii(expr.args[0])}]"
            body = expr.args[1]
            body_text = render_stl(body)
            if isinstance(body, Binary):
                return f"{expr.name}{interval_text}({body_text})"
            return f"{expr.name}{interval_text}{body_text}"

        if expr.name == "I" and len(expr.args) >= 2:
            return f"I({serialize_ascii(expr.args[0])},{serialize_ascii(expr.args[1])})"

        joined = ", ".join(render_stl(arg) for arg in expr.args)
        return f"{expr.name}({joined})"

    raise TypeError(f"Unsupported expression node: {type(expr)!r}")


# ---------------------------------------------------------------------------
# End-to-end conversion
# ---------------------------------------------------------------------------


def convert_semantics_string(semantics: str) -> Dict[str, Any]:
    warnings: List[str] = []
    parsed = parse_semantics(semantics)

    normalized = serialize_ascii(parsed)

    same_resolved_ast = substitute_same(clone_expr(parsed), warnings)
    same_resolved = serialize_ascii(same_resolved_ast)

    seq_ready_ast = right_associate_seq(clone_expr(same_resolved_ast))
    seq_converted_ast = convert_seq(seq_ready_ast, warnings)
    seq_converted = serialize_ascii(seq_converted_ast)

    merged_ast = merge_identical_temporal_functions(clone_expr(seq_converted_ast))
    merged = serialize_ascii(merged_ast)

    if _contains_func_name(merged_ast, "SEQ"):
        warnings.append("SEQ が残っているため STL に変換できませんでした。")
        stl = None
    else:
        stl = render_stl(merged_ast)

    return {
        "input_semantics": semantics,
        "normalized_semantics": normalized,
        "same_resolved_semantics": same_resolved,
        "seq_converted_semantics": seq_converted,
        "converted_semantics": merged,
        "stl": stl,
        "warnings": warnings,
    }


def load_input(json_path: PathLike) -> Dict[str, Any]:
    with Path(json_path).open("r", encoding="utf-8") as fin:
        return json.load(fin)


def save_output(data: Mapping[str, Any], output_json_path: PathLike) -> None:
    output_path = Path(output_json_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fout:
        json.dump(dict(data), fout, ensure_ascii=False, indent=2)


def _extract_candidate_semantics(candidate: Mapping[str, Any]) -> Optional[str]:
    for key in ("canonical_semantics", "semantics", "meaning"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def convert_sentence(sentence_data: Mapping[str, Any], sentence_index: int) -> Dict[str, Any]:
    sentence_id = str(sentence_data.get("sentence_id") or f"s{sentence_index}")
    surface = str(sentence_data.get("surface") or "")
    input_candidates = sentence_data.get("candidates") or []

    if not isinstance(input_candidates, list):
        raise ValueError(
            f"Sentence {sentence_id} has invalid 'candidates': expected list, got {type(input_candidates)!r}"
        )

    output_candidates: List[Dict[str, Any]] = []
    converted_count = 0
    warning_count = 0

    for candidate_index, candidate in enumerate(input_candidates):
        if not isinstance(candidate, Mapping):
            raise ValueError(
                f"Sentence {sentence_id} candidate {candidate_index} must be a JSON object, "
                f"got {type(candidate)!r}"
            )

        output_candidate: Dict[str, Any] = dict(candidate)
        semantics = _extract_candidate_semantics(candidate)
        if semantics is None:
            output_candidate.update(
                {
                    "input_semantics": None,
                    "normalized_semantics": None,
                    "same_resolved_semantics": None,
                    "seq_converted_semantics": None,
                    "converted_semantics": None,
                    "stl": None,
                    "warnings": ["意味が存在しないため STL 変換を行いませんでした。"],
                    "converted": False,
                }
            )
            warning_count += 1
            output_candidates.append(output_candidate)
            continue

        try:
            transformed = convert_semantics_string(semantics)
        except ParseError as exc:
            output_candidate.update(
                {
                    "input_semantics": semantics,
                    "normalized_semantics": None,
                    "same_resolved_semantics": None,
                    "seq_converted_semantics": None,
                    "converted_semantics": None,
                    "stl": None,
                    "warnings": [f"構文解析に失敗したため STL 変換を行いませんでした: {exc}"],
                    "converted": False,
                }
            )
            warning_count += 1
            output_candidates.append(output_candidate)
            continue

        output_candidate.update(transformed)
        output_candidate["converted"] = transformed["stl"] is not None
        if transformed["warnings"] or not output_candidate["converted"]:
            warning_count += 1
        if output_candidate["converted"]:
            converted_count += 1
        output_candidates.append(output_candidate)

    return {
        "sentence_index": int(sentence_data.get("sentence_index", sentence_index)),
        "sentence_id": sentence_id,
        "surface": surface,
        "candidates": output_candidates,
        "total_input_candidates": len(input_candidates),
        "converted_candidates": converted_count,
        "warning_candidates": warning_count,
    }


def convert_data(data: Mapping[str, Any], source_json: str = "") -> Dict[str, Any]:
    sentences_data = data.get("sentences")
    if not isinstance(sentences_data, list):
        raise ValueError("Input JSON must contain a top-level 'sentences' list.")

    source_metadata = {
        key: value for key, value in data.items() if key not in {"sentences", "summary", "source_json"}
    }

    output_sentences = [
        convert_sentence(sentence_data, sentence_index)
        for sentence_index, sentence_data in enumerate(sentences_data)
    ]

    total_candidates = sum(sentence["total_input_candidates"] for sentence in output_sentences)
    converted_candidates = sum(sentence["converted_candidates"] for sentence in output_sentences)
    warning_candidates = sum(sentence["warning_candidates"] for sentence in output_sentences)

    return {
        "source_json": source_json,
        "summary": {
            "total_sentences": len(output_sentences),
            "total_candidates": total_candidates,
            "converted_candidates": converted_candidates,
            "warning_candidates": warning_candidates,
        },
        "settings": {
            "same_allowed_context_operators": ["&", "|"],
            "merged_temporal_functions": ["F", "G"],
        },
        "sentences": output_sentences,
        "source_metadata": source_metadata,
    }


def convert_json(input_json_path: PathLike) -> Dict[str, Any]:
    data = load_input(input_json_path)
    return convert_data(data, source_json=str(input_json_path))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert aggregated meanings into STL sentence by sentence. "
            "The converter performs SAME substitution, SEQ expansion, "
            "temporal-function merging, and final STL rendering."
        )
    )
    parser.add_argument("input_json", help="Input JSON file. Typically the output of Aggregation.py.")
    parser.add_argument("output_json", help="Output JSON file.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    result = convert_json(args.input_json)
    save_output(result, args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
