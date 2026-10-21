#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
#  Copyright 2015 Pascual Martinez-Gomez
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from __future__ import annotations

import html
import importlib.util
import os
import re
import tempfile
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from lxml import etree


# ---------------------------------------------------------------------------
# Optional imports from the original ccg2lambda environment.
# ---------------------------------------------------------------------------

try:  # pragma: no cover - optional dependency
    from ccg2lambda_tools import build_ccg_tree as _external_build_ccg_tree
except Exception:  # pragma: no cover - optional dependency
    _external_build_ccg_tree = None

try:  # pragma: no cover - optional dependency
    from knowledge import get_tokens_from_xml_node as _external_get_tokens_from_xml_node
except Exception:  # pragma: no cover - optional dependency
    _external_get_tokens_from_xml_node = None

try:  # pragma: no cover - optional dependency
    from semantic_index import find_node_by_id as _external_find_node_by_id
except Exception:  # pragma: no cover - optional dependency
    _external_find_node_by_id = None


# ---------------------------------------------------------------------------
# Visualization settings (compatible with the original file)
# ---------------------------------------------------------------------------

kUpwardsTree = True
kDisplaySemantics = True
kDisplayFeatures = True
kFeatureSize = 0.8
kOtherSize = 1.0
kCategoryColor = 'Red'
kFeatureColor = 'Purple'
kSemanticsColor = 'Blue'
kLexicalColor = 'Black'
kEntityColor = 'Green'
kPosColor = 'Green'

PathLike = Union[str, Path]
_NUMERIC_RE = re.compile(r"^\d+(?:\.\d+)?$")
_FUNCTION_CALL_RE = re.compile(r"(?u)([^\W\d]\w*)\s*\(")
_PHI_RE = re.compile(r"Φ_([^\s\)\(∧∨￢,\]]+)")


# ---------------------------------------------------------------------------
# Fallback helpers for environments where the original package is unavailable
# ---------------------------------------------------------------------------


def _fallback_find_node_by_id(node_id: Optional[str], tree: Optional[etree._Element]) -> Optional[etree._Element]:
    if node_id is None or tree is None:
        return None
    for node in tree.iter():
        if node.get('id') == node_id:
            return node
    return None



def _fallback_build_ccg_tree(xml_node: etree._Element) -> etree._Element:
    """
    Rebuild a nested tree from Jigg-style flat <span> nodes.
    """
    if xml_node is None:
        raise ValueError('xml_node must not be None')

    original_spans = list(xml_node.xpath('./span'))
    if not original_spans:
        return xml_node

    cloned_spans: Dict[str, etree._Element] = {}
    for span in original_spans:
        cloned = etree.Element(span.tag)
        for key, value in span.attrib.items():
            if key != 'child':
                cloned.set(key, value)
        if span.text and span.text.strip():
            cloned.text = span.text
        span_id = span.get('id')
        if span_id:
            cloned_spans[span_id] = cloned

    for span in original_spans:
        parent = cloned_spans.get(span.get('id'))
        if parent is None:
            continue
        child_ids = (span.get('child') or '').split()
        for child_id in child_ids:
            child = cloned_spans.get(child_id)
            if child is not None:
                parent.append(child)

    root_id = xml_node.get('root')
    if root_id and root_id in cloned_spans:
        return cloned_spans[root_id]

    for span in original_spans:
        if span.get('root') == 'true':
            span_id = span.get('id')
            if span_id in cloned_spans:
                return cloned_spans[span_id]

    first_id = original_spans[0].get('id')
    if first_id and first_id in cloned_spans:
        return cloned_spans[first_id]
    return original_spans[0]



def build_ccg_tree(xml_node: etree._Element) -> etree._Element:
    if _external_build_ccg_tree is not None:
        return _external_build_ccg_tree(xml_node)
    return _fallback_build_ccg_tree(xml_node)



def get_tokens_from_xml_node(node: etree._Element) -> Iterable[etree._Element]:
    if _external_get_tokens_from_xml_node is not None:
        return _external_get_tokens_from_xml_node(node)
    return node.xpath('./tokens/token')



def find_node_by_id(node_id: Optional[str], tree: Optional[etree._Element]) -> Optional[etree._Element]:
    if _external_find_node_by_id is not None:
        return _external_find_node_by_id(node_id, tree)
    return _fallback_find_node_by_id(node_id, tree)


# ---------------------------------------------------------------------------
# Original MathML rendering helpers
# ---------------------------------------------------------------------------


def get_fraction_mathml(numerator, denominator, line_thickness=3, rule='', upwards=kUpwardsTree):
    if upwards:
        numerator, denominator = denominator, numerator
    mathml_str = (
        "<mfrac linethickness='" + str(line_thickness) + "px'>\n"
        + "  <mrow>" + numerator + "</mrow>\n"
        + "  <mrow>" + denominator + "</mrow>\n"
        + "</mfrac>\n"
    )
    if rule:
        mathml_str = "<mrow><mo>" + html.escape(rule) + "</mo>" + mathml_str + "</mrow>"
    return mathml_str



def get_category_mathml(category):
    cats_feats = re.findall(r'([\w\\/()]+)(\[.+?\])*', category)
    mathml_str = ''
    for cat, feat in cats_feats:
        cat_mathml = (
            "  <mi mathvariant='italic'"
            + " fontsize='" + str(kOtherSize) + "'"
            + " color='" + kCategoryColor + "'>"
            + html.escape(cat)
            + "  </mi>\n"
        )
        if feat != '' and kDisplayFeatures:
            mathml_str += (
                "<msub>\n"
                + cat_mathml
                + "  <mrow>\n"
                + "    <mi mathvariant='italic'"
                + " fontsize='" + str(kFeatureSize) + "'"
                + " color='" + kFeatureColor + "'>"
                + html.escape(feat)
                + "  </mi>\n"
                + "  </mrow>\n"
                + "</msub>\n"
            )
        else:
            mathml_str += cat_mathml
    return mathml_str



def get_surface_mathml(surface):
    return (
        "<mtext "
        + " fontsize='" + str(kOtherSize) + "'"
        + " color='" + kLexicalColor + "'>"
        + html.escape(surface)
        + "</mtext>\n"
    )



def get_entity_mathml(entity):
    return (
        "<mtext "
        + " fontsize='" + str(kOtherSize) + "'"
        + " color='" + kEntityColor + "'>"
        + html.escape(entity)
        + "</mtext>\n"
    )



def get_pos_mathml(pos):
    return (
        "<mtext "
        + " fontsize='" + str(kOtherSize) + "'"
        + " color='" + kPosColor + "'>"
        + html.escape(pos)
        + "</mtext>\n"
    )



def get_semantics_mathml(semantics):
    return (
        "<mtext "
        + " fontsize='" + str(kOtherSize) + "'"
        + " color='" + kSemanticsColor + "'>"
        + html.escape(semantics)
        + "</mtext>\n"
    )



def convert_node_to_mathml(ccg_node, sem_tree, tokens):
    mathml_str = ''
    category = (ccg_node.get('category') or '').strip()
    category_mathml = get_category_mathml(category)
    if len(ccg_node) == 0:
        token_id = ccg_node.get('terminal')
        token = find_node_by_id(token_id, tokens)
        if token is None:
            surf = ''
            pos = ''
            entity = None
        else:
            surf = token.get('surf') or token.get('base') or ''
            pos = token.get('pos') or ''
            entity = token.get('entity')
        surf_mathml = get_surface_mathml(surf)
        pos_mathml = get_pos_mathml(pos)
        if entity is not None:
            entity_mathml = get_entity_mathml(entity)
            pos_mathml = pos_mathml + "<mtext>,</mtext><mspace width='.1em'/>" + entity_mathml
        if token is not None:
            pos1 = token.get('pos1')
            if not (pos1 is None or pos1 == '*'):
                pos_mathml = pos_mathml + "<mspace width='.1em'/>" + get_pos_mathml(pos1)
            pos2 = token.get('pos2')
            if not (pos2 is None or pos2 == '*'):
                pos_mathml = pos_mathml + "<mspace width='.1em'/>" + get_pos_mathml(pos2)
            pos3 = token.get('pos3')
            if not (pos3 is None or pos3 == '*'):
                pos_mathml = pos_mathml + "<mspace width='.1em'/>" + get_pos_mathml(pos3)
        if pos == '.':
            mathml_str = get_fraction_mathml(category_mathml, surf_mathml, '0')
        else:
            mathml_pos_str = get_fraction_mathml(category_mathml, pos_mathml, '0')
            mathml_str = get_fraction_mathml(mathml_pos_str, surf_mathml, '0')
    elif len(ccg_node) == 1:
        mathml_str_child = convert_node_to_mathml(ccg_node[0], sem_tree, tokens)
        rule = ccg_node.get('rule')
        mathml_str = get_fraction_mathml(category_mathml, mathml_str_child, '3', rule)
    elif len(ccg_node) > 0:
        mathml_str_children = ''
        for child in ccg_node:
            mathml_str_children += convert_node_to_mathml(child, sem_tree, tokens)
        rule = ccg_node.get('rule')
        mathml_str = get_fraction_mathml(category_mathml, mathml_str_children, '3', rule)
    if sem_tree is not None and kDisplaySemantics:
        span_id = ccg_node.get('id')
        sem_node = find_node_by_id(span_id, sem_tree)
        if sem_node is not None:
            semantics = sem_node.get('sem') or ''
            semantics_mathml = get_semantics_mathml(semantics)
            mathml_str = get_fraction_mathml(semantics_mathml, mathml_str, '0')
    return mathml_str


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_pipeline_modules() -> Tuple[Any, Any, Any]:
    base_dir = Path(__file__).resolve().parent

    def _load(module_name: str, file_name: str):
        file_path = base_dir / file_name
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f'Could not load {file_name}.')
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    return (
        _load('Canonicalization_local', 'Canonicalization.py'),
        _load('STL_conversion_local', 'STL_conversion.py'),
        _load('Aggregation_local', 'Aggregation.py'),
    )



def _as_tree(root: Union[etree._ElementTree, etree._Element]) -> etree._ElementTree:
    if isinstance(root, etree._ElementTree):
        return root
    return root.getroottree()



def _materialize_root_to_xml(root: Union[etree._ElementTree, etree._Element]) -> Tuple[Path, Optional[Path]]:
    tree = _as_tree(root)
    source_url = tree.docinfo.URL
    if source_url:
        source_path = Path(source_url)
        if source_path.exists():
            return source_path, None

    temp = tempfile.NamedTemporaryFile(delete=False, suffix='.visualize.sem.xml')
    temp_path = Path(temp.name)
    temp.close()
    tree.write(str(temp_path), encoding='utf-8', pretty_print=True, xml_declaration=True)
    return temp_path, temp_path



def _object_to_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, Mapping):
        return dict(obj)
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    raise TypeError(f'Unsupported result object: {type(obj)!r}')



def _build_aggregation_input_from_stl(stl_data: Mapping[str, Any], source_json: str = '') -> Dict[str, Any]:
    sentences: List[Dict[str, Any]] = []
    for sentence_index, sentence in enumerate(stl_data.get('sentences') or []):
        candidates_out: List[Dict[str, Any]] = []
        for candidate in sentence.get('candidates') or []:
            candidate_out = dict(candidate)
            stl_text = candidate.get('stl')
            if _is_final_stl_text(stl_text):
                candidate_out['semantics'] = stl_text
                candidate_out['canonical_semantics'] = stl_text
            else:
                candidate_out['semantics'] = None
                candidate_out['canonical_semantics'] = None
            candidates_out.append(candidate_out)

        sentences.append(
            {
                'sentence_index': int(sentence.get('sentence_index', sentence_index)),
                'sentence_id': sentence.get('sentence_id') or f's{sentence_index}',
                'surface': sentence.get('surface') or '',
                'candidates': candidates_out,
            }
        )

    return {
        'source_json': source_json,
        'settings': {
            'pipeline_order': ['Canonicalization.py', 'STL_conversion.py', 'Aggregation.py'],
            'aggregation_target': 'stl',
        },
        'sentences': sentences,
    }



def _run_pipeline(root: Union[etree._ElementTree, etree._Element]) -> Dict[str, Any]:
    canonicalization_module, stl_module, aggregation_module = _load_pipeline_modules()
    xml_path, temporary_path = _materialize_root_to_xml(root)
    try:
        try:
            canonicalization_result = canonicalization_module.canonicalize_xml(
                xml_path,
                allowed_functions=['F', 'G', 'I', 'AP', 'SEQ'],
            )
        except TypeError:
            canonicalization_result = canonicalization_module.canonicalize_xml(xml_path)
        canonicalization_data = _object_to_dict(canonicalization_result)

        stl_data = stl_module.convert_data(canonicalization_data, source_json=str(xml_path))
        aggregation_input = _build_aggregation_input_from_stl(stl_data, source_json=str(xml_path))
        aggregation_result = aggregation_module.aggregate_data(aggregation_input, source_json=str(xml_path))
        aggregation_data = _object_to_dict(aggregation_result)

        return {
            'canonicalization': canonicalization_data,
            'stl_conversion': stl_data,
            'aggregation': aggregation_data,
        }
    finally:
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Sentence / tree alignment helpers
# ---------------------------------------------------------------------------


def get_surf_from_xml_node(node):
    tokens = node.xpath("./tokens/token[not(@surf='*')]/@surf | ./tokens/token[@surf='*']/@base")
    return ' '.join(tokens)



def _match_semantics_to_ccgs(
    ccg_nodes: Sequence[etree._Element],
    semantics_nodes: Sequence[etree._Element],
) -> Dict[int, Optional[etree._Element]]:
    ccg_id_to_index: Dict[str, int] = {}
    for index, ccg_node in enumerate(ccg_nodes):
        ccg_id = ccg_node.get('id')
        if ccg_id:
            ccg_id_to_index[ccg_id] = index

    matched: Dict[int, Optional[etree._Element]] = {index: None for index in range(len(ccg_nodes))}
    fallback: List[etree._Element] = []

    for semantics_node in semantics_nodes:
        ccg_id = semantics_node.get('ccg_id')
        if ccg_id and ccg_id in ccg_id_to_index and matched[ccg_id_to_index[ccg_id]] is None:
            matched[ccg_id_to_index[ccg_id]] = semantics_node
        else:
            fallback.append(semantics_node)

    fallback_iter = iter(fallback)
    for index in range(len(ccg_nodes)):
        if matched[index] is None:
            matched[index] = next(fallback_iter, None)
    return matched



def _sentence_label(sentence_index: int, num_sentences: int) -> str:
    if sentence_index < num_sentences - 1:
        return f'Premise {sentence_index}'
    return 'Conclusion'



def _safe_get(items: Sequence[Mapping[str, Any]], index: int) -> Mapping[str, Any]:
    if 0 <= index < len(items):
        return items[index]
    return {}



def _candidate_map_by_ccg_id(sentence_data: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    result: Dict[str, Mapping[str, Any]] = {}
    for candidate in sentence_data.get('candidates') or []:
        ccg_id = candidate.get('ccg_id')
        if ccg_id:
            result[str(ccg_id)] = candidate
    return result


# ---------------------------------------------------------------------------
# STL formatting helpers
# ---------------------------------------------------------------------------



def _format_score(value: Any) -> str:
    if value is None:
        return '—'
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return html.escape(str(value))
    return f'{numeric:.10f}'.rstrip('0').rstrip('.') if numeric != 0 else '0'



def _format_bool(value: Any) -> str:
    return 'Yes' if bool(value) else 'No'



def _join_texts(values: Any) -> str:
    if values is None:
        return '—'
    if isinstance(values, (list, tuple)):
        cleaned = [str(v) for v in values if str(v)]
        return ', '.join(cleaned) if cleaned else '—'
    text = str(values)
    return text if text else '—'



def _is_numeric_text(text: str) -> bool:
    return bool(_NUMERIC_RE.fullmatch(text))



def _is_final_stl_text(text: Any) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    candidate = text.strip()
    if 'SAME' in candidate:
        return False
    if _FUNCTION_CALL_RE.search(candidate):
        return False

    for interval in re.findall(r'[FG]\[([^\]]+)\]', candidate):
        parts = [part.strip() for part in interval.split(',')]
        if len(parts) != 2:
            return False
        if not all(_is_numeric_text(part) for part in parts):
            return False
    return True



def _stl_to_html(text: Any) -> str:
    if not isinstance(text, str) or not text.strip():
        return '—'
    escaped = html.escape(text)
    return _PHI_RE.sub(lambda m: f'Φ<sub>{html.escape(m.group(1))}</sub>', escaped)



def _code_or_dash(text: Any, *, stl: bool = False) -> str:
    if not isinstance(text, str) or not text.strip():
        return '—'
    rendered = _stl_to_html(text) if stl else html.escape(text)
    return f"<code>{rendered}</code>"


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------



def _build_tree_detail_table(
    ccg_node: etree._Element,
    canonical_candidate: Mapping[str, Any],
    stl_candidate: Mapping[str, Any],
) -> str:
    raw_stl = stl_candidate.get('stl')
    valid_stl = raw_stl if _is_final_stl_text(raw_stl) else None

    rows = [
        ('構文木 ID', html.escape(str(ccg_node.get('id') or canonical_candidate.get('ccg_id') or '—'))),
        ('構文木スコア', html.escape(str(ccg_node.get('score') or '—'))),
        ('意味導出 status', html.escape(str(canonical_candidate.get('semantics_status') or '—'))),
        ('抽出意味', _code_or_dash(canonical_candidate.get('original_semantics'))),
        ('Canonicalization 後意味', _code_or_dash(canonical_candidate.get('canonical_semantics'))),
        ('Canonicalization 後スコア', html.escape(_format_score(canonical_candidate.get('score')))),
        ('保持されたか', html.escape(_format_bool(canonical_candidate.get('kept')))),
        ('除去理由', html.escape(_join_texts(canonical_candidate.get('reasons')))),
        ('STL 変換結果', _code_or_dash(valid_stl, stl=True) if valid_stl else '変換できませんでした'),
        ('STL 警告', html.escape(_join_texts(stl_candidate.get('warnings')))),
    ]

    table_rows = ''.join(
        f"<tr><th>{label}</th><td>{value}</td></tr>" for label, value in rows
    )
    return f"""
<div class='tree-details'>
  <table class='details-table'>
    <tbody>
      {table_rows}
    </tbody>
  </table>
</div>
"""



def _build_sentence_stl_html(sentence_result: Mapping[str, Any], sentence_label: str) -> str:
    candidates = list(sentence_result.get('candidates') or [])
    ordered_candidates = sorted(
        candidates,
        key=lambda cand: float(cand.get('score') or 0.0),
        reverse=True,
    )

    header = f"""
<section class='stl-summary'>
  <h3>{html.escape(sentence_label)}: STL とスコア</h3>
"""

    if not ordered_candidates:
        return header + "  <p>この文に対する STL 候補は生成されませんでした。</p>\n</section>\n"

    body_rows: List[str] = []
    for rank, candidate in enumerate(ordered_candidates, start=1):
        stl_text = candidate.get('canonical_semantics') or candidate.get('semantics') or candidate.get('stl')
        score_text = _format_score(candidate.get('score'))
        source_count = html.escape(str(candidate.get('source_count') or 0))
        source_candidates = candidate.get('source_candidates') or []
        source_ids = []
        for source_candidate in source_candidates:
            ccg_id = source_candidate.get('ccg_id')
            parse_index = source_candidate.get('parse_index')
            if ccg_id:
                source_ids.append(str(ccg_id))
            elif parse_index is not None:
                source_ids.append(str(parse_index))
        sources_text = ', '.join(source_ids) if source_ids else '—'
        body_rows.append(
            """
      <tr>
        <td>{rank}</td>
        <td>{score}</td>
        <td class='stl-cell'><code>{stl}</code></td>
        <td>{source_count}</td>
        <td>{sources}</td>
      </tr>
""".format(
                rank=rank,
                score=html.escape(score_text),
                stl=_stl_to_html(stl_text),
                source_count=source_count,
                sources=html.escape(sources_text),
            )
        )

    return header + """
  <table class='stl-table'>
    <thead>
      <tr>
        <th>順位</th>
        <th>正規化スコア</th>
        <th>STL</th>
        <th>統合数</th>
        <th>元の構文木</th>
      </tr>
    </thead>
    <tbody>
{rows}
    </tbody>
  </table>
</section>
""".format(rows=''.join(body_rows))



def _build_pipeline_error_html(error_message: str) -> str:
    return """
<section class='pipeline-error'>
  <h2>STL 変換の実行に失敗しました</h2>
  <pre>{message}</pre>
</section>
""".format(message=html.escape(error_message))


# ---------------------------------------------------------------------------
# Document conversion
# ---------------------------------------------------------------------------



def convert_doc_to_mathml(
    doc: etree._Element,
    use_gold_trees: bool = False,
    canonical_sentence_results: Optional[Sequence[Mapping[str, Any]]] = None,
    stl_sentence_results: Optional[Sequence[Mapping[str, Any]]] = None,
    aggregated_sentence_results: Optional[Sequence[Mapping[str, Any]]] = None,
) -> str:
    canonical_sentence_results = list(canonical_sentence_results or [])
    stl_sentence_results = list(stl_sentence_results or [])
    aggregated_sentence_results = list(aggregated_sentence_results or [])

    num_sentences = int(doc.xpath('count(./sentences/sentence)'))
    sentence_nodes = doc.xpath('./sentences/sentence')
    parts: List[str] = []

    for sent_ind, sentence in enumerate(sentence_nodes):
        sentence_label = _sentence_label(sent_ind, num_sentences)
        sentence_text = get_surf_from_xml_node(sentence)
        ccg_trees = sentence.xpath('./ccg')
        semantics_nodes = sentence.xpath('./semantics')
        matched_semantics = _match_semantics_to_ccgs(ccg_trees, semantics_nodes)
        tokens_list = sentence.xpath('./tokens')
        if not tokens_list:
            continue
        tokens = tokens_list[0]

        canonical_sentence = _safe_get(canonical_sentence_results, sent_ind)
        stl_sentence = _safe_get(stl_sentence_results, sent_ind)
        aggregated_sentence = _safe_get(aggregated_sentence_results, sent_ind)
        canonical_map = _candidate_map_by_ccg_id(canonical_sentence)
        stl_map = _candidate_map_by_ccg_id(stl_sentence)

        sentence_parts: List[str] = [
            """
<section class='sentence-section'>
  <h2>{label}: {surface}</h2>
""".format(label=html.escape(sentence_label), surface=html.escape(sentence_text))
        ]

        gold_tree_index = int(sentence.get('gold_tree', -1))
        for tree_index, ccg_tree_node in enumerate(ccg_trees):
            ccg_tree_id = ccg_tree_node.get('id', str(tree_index))
            display_tree_id = ccg_tree_id + (' (gold)' if gold_tree_index == tree_index else '')
            try:
                ccg_tree = build_ccg_tree(ccg_tree_node)
            except ValueError:
                sentence_parts.append(
                    """
<div class='tree-block'>
  <p>{label}, tree {tree_id}: {surface}</p>
  <p>Syntactic parse error. Visualization skipped.</p>
</div>
""".format(
                        label=html.escape(sentence_label),
                        tree_id=html.escape(display_tree_id),
                        surface=html.escape(sentence_text),
                    )
                )
                continue

            sem_tree_node = matched_semantics.get(tree_index)
            sem_tree = build_ccg_tree(sem_tree_node) if sem_tree_node is not None else None
            canonical_candidate = canonical_map.get(ccg_tree_id)
            if canonical_candidate is None:
                candidates = canonical_sentence.get('candidates') or []
                if tree_index < len(candidates):
                    canonical_candidate = candidates[tree_index]
                else:
                    canonical_candidate = {}
            stl_candidate = stl_map.get(ccg_tree_id)
            if stl_candidate is None:
                candidates = stl_sentence.get('candidates') or []
                if tree_index < len(candidates):
                    stl_candidate = candidates[tree_index]
                else:
                    stl_candidate = {}

            sentence_parts.append(
                """
<div class='tree-block'>
  <p>{label}, tree {tree_id}: {surface}</p>
  <math xmlns='http://www.w3.org/1998/Math/MathML'>
{mathml}
  </math>
{details}
</div>
""".format(
                    label=html.escape(sentence_label),
                    tree_id=html.escape(display_tree_id),
                    surface=html.escape(sentence_text),
                    mathml=convert_node_to_mathml(ccg_tree, sem_tree, tokens),
                    details=_build_tree_detail_table(ccg_tree_node, canonical_candidate, stl_candidate),
                )
            )

        sentence_parts.append(_build_sentence_stl_html(aggregated_sentence, sentence_label))
        sentence_parts.append('</section>\n')
        parts.append(''.join(sentence_parts))

    verbatim_strings = doc.xpath('./proof/master_theorem/theorems/theorem/coq_script/text()')
    if verbatim_strings:
        verbatim_text = ["<p>Script piped to coq</p>"]
        for vb_str in verbatim_strings:
            verbatim_text.append('<pre>\n' + html.escape(vb_str) + '\n</pre>\n')
        parts.append(''.join(verbatim_text))

    return ''.join(parts)


# ---------------------------------------------------------------------------
# HTML wrapper
# ---------------------------------------------------------------------------



def wrap_mathml_in_html(mathml_str):
    html_str = """<!DOCTYPE html>
<html lang='ja'>
<head>
  <meta charset='UTF-8'/>
  <title>CCG to Lambda conversion</title>
  <style>
    body {
      font-size: 1em;
      line-height: 1.5;
      margin: 24px;
      font-family: sans-serif;
    }
    math {
      display: block;
      margin: 0.4rem 0 0.8rem 0;
      overflow-x: auto;
    }
    .sentence-section {
      border: 1px solid #d8d8d8;
      border-radius: 8px;
      padding: 1rem 1.2rem;
      margin-bottom: 1.5rem;
    }
    .tree-block {
      padding: 0.6rem 0 1rem 0;
      border-top: 1px solid #ececec;
    }
    .tree-block:first-of-type {
      border-top: none;
    }
    table {
      border-collapse: collapse;
      width: 100%;
      margin: 0.6rem 0 1rem 0;
    }
    th, td {
      border: 1px solid #d8d8d8;
      padding: 0.45rem 0.6rem;
      vertical-align: top;
      text-align: left;
    }
    th {
      background: #f6f6f6;
      width: 18%;
      white-space: nowrap;
    }
    .stl-table th, .stl-table td {
      width: auto;
    }
    .stl-cell {
      font-family: sans-serif;
    }
    code {
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .pipeline-error {
      border: 1px solid #e49b9b;
      background: #fff5f5;
      padding: 1rem;
      border-radius: 8px;
      margin-bottom: 1.5rem;
    }
  </style>
  <script type="text/javascript"
          src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.1/MathJax.js?config=TeX-AMS-MML_HTMLorMML">
  </script>
</head>
<body>
"""
    html_str += mathml_str
    html_str += """
</body>
</html>
"""
    return html_str



def convert_root_to_mathml(root, use_gold_trees=False):
    """
    This function expects an XML root. Then, it converts each document into a
    presentation MathML string, appends STL tables, and wraps them with HTML.

    Pipeline order:
      Canonicalization.py -> STL_conversion.py -> Aggregation.py
    """
    root_tree = _as_tree(root)
    doc_mathml_strs: List[str] = []
    sentence_offset = 0

    try:
        pipeline = _run_pipeline(root_tree)
        canonical_sentences = list(pipeline['canonicalization'].get('sentences') or [])
        stl_sentences = list(pipeline['stl_conversion'].get('sentences') or [])
        aggregated_sentences = list(pipeline['aggregation'].get('sentences') or [])
    except Exception as exc:
        pipeline = None
        canonical_sentences = []
        stl_sentences = []
        aggregated_sentences = []
        doc_mathml_strs.append(_build_pipeline_error_html(str(exc)))

    documents = root_tree.xpath('./document')
    for doc_ind, doc in enumerate(documents):
        sentence_count = int(doc.xpath('count(./sentences/sentence)'))
        doc_mathml_strs.append(
            convert_doc_to_mathml(
                doc,
                use_gold_trees=use_gold_trees,
                canonical_sentence_results=canonical_sentences[sentence_offset: sentence_offset + sentence_count],
                stl_sentence_results=stl_sentences[sentence_offset: sentence_offset + sentence_count],
                aggregated_sentence_results=aggregated_sentences[sentence_offset: sentence_offset + sentence_count],
            )
        )
        sentence_offset += sentence_count

    return wrap_mathml_in_html('\n'.join(doc_mathml_strs))


# TODO: possibly deprecated. Kept for compatibility.
def convert_doc_to_mathml_(doc, verbatim_strings = [], use_gold_trees=False):
    return convert_doc_to_mathml(doc, use_gold_trees=use_gold_trees)
