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
import importlib
import importlib.util
import os
import re
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from lxml import etree

try:  # pragma: no cover - optional dependency in the user's environment
    from ccg2lambda_tools import build_ccg_tree as _external_build_ccg_tree
except Exception:  # pragma: no cover
    _external_build_ccg_tree = None

try:  # pragma: no cover - optional dependency in the user's environment
    from knowledge import get_tokens_from_xml_node as _external_get_tokens_from_xml_node
except Exception:  # pragma: no cover
    _external_get_tokens_from_xml_node = None

try:  # pragma: no cover - optional dependency in the user's environment
    from semantic_index import find_node_by_id as _external_find_node_by_id
except Exception:  # pragma: no cover
    _external_find_node_by_id = None


# ---------------------------------------------------------------------------
# Visualization settings from the original implementation
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


# ---------------------------------------------------------------------------
# Fallback helpers used when the full ccg2lambda package is not available
# ---------------------------------------------------------------------------


def _fallback_find_node_by_id(node_id: Optional[str], tree: Optional[etree._Element]) -> Optional[etree._Element]:
    if node_id is None or tree is None:
        return None
    for node in tree.iter():
        if node.get('id') == node_id:
            return node
    return None



def _fallback_get_tokens_from_xml_node(node: etree._Element) -> List[etree._Element]:
    if node is None:
        return []
    if node.tag == 'tokens':
        return list(node.xpath('./token'))
    return list(node.xpath('./tokens/token'))



def _fallback_build_ccg_tree(xml_node: etree._Element) -> etree._Element:
    """
    Reconstruct a nested tree from Jigg/depccg style flat <span> nodes.

    The original visualization code expects each span's children to be nested XML
    elements. depccg often stores spans flat and references children through the
    @child attribute, so we rebuild that structure here.
    """
    if xml_node is None:
        raise ValueError('xml_node must not be None')

    original_spans = list(xml_node.xpath('./span'))
    if not original_spans:
        return xml_node

    cloned_by_id: Dict[str, etree._Element] = {}
    for span in original_spans:
        cloned = etree.Element(span.tag)
        for key, value in span.attrib.items():
            if key != 'child':
                cloned.set(key, value)
        if span.text and span.text.strip():
            cloned.text = span.text
        span_id = span.get('id')
        if span_id:
            cloned_by_id[span_id] = cloned

    for span in original_spans:
        parent_id = span.get('id')
        if not parent_id or parent_id not in cloned_by_id:
            continue
        parent = cloned_by_id[parent_id]
        for child_id in (span.get('child') or '').split():
            child = cloned_by_id.get(child_id)
            if child is not None:
                parent.append(child)

    root_id = xml_node.get('root')
    if root_id and root_id in cloned_by_id:
        return cloned_by_id[root_id]

    for span in original_spans:
        if span.get('root') == 'true':
            span_id = span.get('id')
            if span_id and span_id in cloned_by_id:
                return cloned_by_id[span_id]

    first_span_id = original_spans[0].get('id')
    if first_span_id and first_span_id in cloned_by_id:
        return cloned_by_id[first_span_id]
    return original_spans[0]



def build_ccg_tree(xml_node: etree._Element) -> etree._Element:
    if _external_build_ccg_tree is not None:
        return _external_build_ccg_tree(xml_node)
    return _fallback_build_ccg_tree(xml_node)



def get_tokens_from_xml_node(node: etree._Element) -> List[etree._Element]:
    if _external_get_tokens_from_xml_node is not None:
        return _external_get_tokens_from_xml_node(node)
    return _fallback_get_tokens_from_xml_node(node)



def find_node_by_id(node_id: Optional[str], tree: Optional[etree._Element]) -> Optional[etree._Element]:
    if _external_find_node_by_id is not None:
        return _external_find_node_by_id(node_id, tree)
    return _fallback_find_node_by_id(node_id, tree)


# ---------------------------------------------------------------------------
# STL pipeline loading helpers
# ---------------------------------------------------------------------------


def _module_path(module_name: str) -> Path:
    return Path(__file__).resolve().with_name(module_name + '.py')


@lru_cache(maxsize=8)
def _load_local_module(module_name: str):
    try:
        return importlib.import_module(module_name)
    except Exception:
        pass

    module_file = _module_path(module_name)
    if not module_file.exists():
        raise ImportError('Required module not found: {0}'.format(module_file))

    unique_name = '_visualization_tools_{0}'.format(module_name)
    spec = importlib.util.spec_from_file_location(unique_name, str(module_file))
    if spec is None or spec.loader is None:
        raise ImportError('Unable to load module spec for {0}'.format(module_file))

    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module



def _to_plain_data(value):
    if hasattr(value, 'to_dict'):
        return value.to_dict()
    return value


@lru_cache(maxsize=8)
def _run_pipeline_from_xml_path(xml_path: str) -> Dict[str, object]:
    canonicalization = _load_local_module('Canonicalization')
    aggregation = _load_local_module('Aggregation')
    stl_conversion = _load_local_module('STL_conversion')

    canonical_data = _to_plain_data(canonicalization.canonicalize_xml(xml_path))

    try:
        aggregated_data = _to_plain_data(
            aggregation.aggregate_data(canonical_data, source_json=str(xml_path))
        )
    except TypeError:
        aggregated_data = _to_plain_data(aggregation.aggregate_data(canonical_data))

    try:
        stl_data = _to_plain_data(
            stl_conversion.convert_data(aggregated_data, source_json=str(xml_path))
        )
    except TypeError:
        stl_data = _to_plain_data(stl_conversion.convert_data(aggregated_data))

    return {
        'canonical': canonical_data,
        'aggregated': aggregated_data,
        'stl': stl_data,
    }



def _extract_xml_path_from_root(root: etree._ElementTree) -> Tuple[str, Optional[str]]:
    url = getattr(getattr(root, 'docinfo', None), 'URL', None)
    if url and os.path.exists(url):
        return url, None

    xml_bytes = etree.tostring(root, encoding='utf-8', xml_declaration=True)
    fd, tmp_path = tempfile.mkstemp(prefix='visualize_', suffix='.xml')
    with os.fdopen(fd, 'wb') as fout:
        fout.write(xml_bytes)
    return tmp_path, tmp_path


# ---------------------------------------------------------------------------
# General HTML helpers
# ---------------------------------------------------------------------------


def _format_score(score) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return '-'
    text = '{0:.12f}'.format(value).rstrip('0').rstrip('.')
    return text if text else '0'



def _escape_or_dash(value) -> str:
    if value is None:
        return '-'
    text = str(value)
    return html.escape(text) if text else '-'



def _convert_phi_subscripts_to_html(stl_text: Optional[str]) -> str:
    if stl_text is None:
        return '-'
    escaped = html.escape(str(stl_text))

    def replace(match: re.Match[str]) -> str:
        label = match.group(1)
        if label.startswith('{') and label.endswith('}'):
            label = label[1:-1]
        return 'Φ<sub>{0}</sub>'.format(html.escape(label))

    return re.sub(r'Φ_(\{[^{}]+\}|[A-Za-z0-9]+)', replace, escaped)



def _sentence_display_label(local_index: int) -> str:
    return '文 {0}'.format(local_index + 1)



def _sentence_old_style_label(local_index: int, num_sentences: int) -> str:
    if local_index < num_sentences - 1:
        return 'Premise {0}'.format(local_index)
    return 'Conclusion'



def _match_semantics_to_ccgs(
    ccg_nodes: Sequence[etree._Element],
    semantics_nodes: Sequence[etree._Element],
) -> Dict[int, Optional[etree._Element]]:
    ccg_id_to_index: Dict[str, int] = {}
    for index, ccg_node in enumerate(ccg_nodes):
        ccg_id = ccg_node.get('id')
        if ccg_id:
            ccg_id_to_index[ccg_id] = index

    matched: Dict[int, Optional[etree._Element]] = {i: None for i in range(len(ccg_nodes))}
    unmatched_positions: List[int] = list(range(len(ccg_nodes)))
    fallback_semantics: List[etree._Element] = []

    for semantics_node in semantics_nodes:
        ccg_id = semantics_node.get('ccg_id')
        if ccg_id and ccg_id in ccg_id_to_index and matched[ccg_id_to_index[ccg_id]] is None:
            index = ccg_id_to_index[ccg_id]
            matched[index] = semantics_node
            if index in unmatched_positions:
                unmatched_positions.remove(index)
        else:
            fallback_semantics.append(semantics_node)

    for index, semantics_node in zip(unmatched_positions, fallback_semantics):
        matched[index] = semantics_node

    return matched


# ---------------------------------------------------------------------------
# Original MathML rendering helpers
# ---------------------------------------------------------------------------


def get_fraction_mathml(numerator, denominator, line_thickness=3,
                   rule='', upwards=kUpwardsTree):
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
        surf = '' if token is None else (token.get('surf') or token.get('base') or '')
        surf_mathml = get_surface_mathml(surf)
        pos = '' if token is None else (token.get('pos') or '')
        pos_mathml = get_pos_mathml(pos)
        entity = None if token is None else token.get('entity')
        if entity is not None:
            entity_mathml = get_entity_mathml(entity)
            pos_mathml = pos_mathml + "<mtext>,</mtext><mspace width='.1em'/>" + entity_mathml
        if token is not None:
            for key in ('pos1', 'pos2', 'pos3'):
                pos_x = token.get(key)
                if pos_x not in (None, '*'):
                    pos_x_mathml = get_pos_mathml(pos_x)
                    pos_mathml = pos_mathml + "<mspace width='.1em'/>" + pos_x_mathml
        if pos == '.':
            mathml_str = get_fraction_mathml(category_mathml, surf_mathml, '0')
        else:
            mathml_pos_str = get_fraction_mathml(category_mathml, pos_mathml, '0')
            mathml_str = get_fraction_mathml(mathml_pos_str, surf_mathml, '0')
    elif len(ccg_node) == 1:
        mathml_str_child = convert_node_to_mathml(ccg_node[0], sem_tree, tokens)
        rule = ccg_node.get('rule') or ''
        mathml_str = get_fraction_mathml(category_mathml, mathml_str_child, '3', rule)
    else:
        mathml_str_children = ''
        for child in ccg_node:
            mathml_str_children += convert_node_to_mathml(child, sem_tree, tokens)
        rule = ccg_node.get('rule') or ''
        mathml_str = get_fraction_mathml(category_mathml, mathml_str_children, '3', rule)
    if sem_tree is not None and kDisplaySemantics:
        span_id = ccg_node.get('id')
        sem_node = find_node_by_id(span_id, sem_tree)
        if sem_node is not None and sem_node.get('sem') is not None:
            semantics_mathml = get_semantics_mathml(sem_node.get('sem'))
            mathml_str = get_fraction_mathml(semantics_mathml, mathml_str, '0')
    return mathml_str



def get_surf_from_xml_node(node):
    tokens = node.xpath(
        "./tokens/token[not(@surf='*')]/@surf | ./tokens/token[@surf='*']/@base"
    )
    return ' '.join(tokens)


# ---------------------------------------------------------------------------
# STL / tree-detail rendering helpers
# ---------------------------------------------------------------------------


def _canonical_candidate_map(sentence_data: Optional[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    result: Dict[str, Dict[str, object]] = {}
    if not sentence_data:
        return result
    for candidate in sentence_data.get('candidates', []) or []:
        ccg_id = candidate.get('ccg_id')
        if ccg_id is not None:
            result[str(ccg_id)] = candidate
    return result



def _stl_source_map(sentence_data: Optional[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    result: Dict[str, Dict[str, object]] = {}
    if not sentence_data:
        return result
    for stl_candidate in sentence_data.get('candidates', []) or []:
        for source_candidate in stl_candidate.get('source_candidates', []) or []:
            ccg_id = source_candidate.get('ccg_id')
            if ccg_id is None:
                continue
            result[str(ccg_id)] = {
                'stl_candidate': stl_candidate,
                'source_candidate': source_candidate,
            }
    return result



def _render_bool(value: Optional[bool]) -> str:
    if value is True:
        return "<span class='status-yes'>はい</span>"
    if value is False:
        return "<span class='status-no'>いいえ</span>"
    return '-'



def _render_reason_list(reasons: Optional[Sequence[str]]) -> str:
    if not reasons:
        return '-'
    return '<br/>'.join(html.escape(str(reason)) for reason in reasons)



def _render_formula_text(value: Optional[str], *, is_stl: bool = False) -> str:
    if value is None or value == '':
        return '-'
    if is_stl:
        return _convert_phi_subscripts_to_html(value)
    return '<code>{0}</code>'.format(html.escape(str(value)))



def _build_tree_detail_table(
    ccg_node: etree._Element,
    canonical_candidate: Optional[Dict[str, object]],
    stl_mapping: Optional[Dict[str, object]],
) -> str:
    tree_id = ccg_node.get('id') or '-'
    raw_score = ccg_node.get('score')
    kept_value = canonical_candidate.get('kept') if canonical_candidate is not None else None

    rows: List[Tuple[str, str]] = [
        ('構文木 ID', html.escape(str(tree_id))),
        ('構文木スコア', _escape_or_dash(raw_score)),
    ]

    if canonical_candidate is not None:
        rows.extend([
            ('意味導出 status', _escape_or_dash(canonical_candidate.get('semantics_status'))),
            ('Canonicalization 後スコア', _format_score(canonical_candidate.get('score'))),
            ('抽出意味', _render_formula_text(canonical_candidate.get('original_semantics'))),
            ('正規化意味', _render_formula_text(canonical_candidate.get('canonical_semantics'))),
            ('保持', _render_bool(kept_value)),
            ('除去理由', _render_reason_list(canonical_candidate.get('reasons'))),
        ])
    else:
        rows.extend([
            ('意味導出 status', '-'),
            ('Canonicalization 後スコア', '-'),
            ('抽出意味', '-'),
            ('正規化意味', '-'),
            ('保持', '-'),
            ('除去理由', 'Canonicalization の対応候補が見つかりませんでした。'),
        ])

    if stl_mapping is not None:
        stl_candidate = stl_mapping.get('stl_candidate', {})
        source_candidate = stl_mapping.get('source_candidate', {})
        rows.extend([
            ('集約前スコア和', _format_score(stl_candidate.get('aggregated_score'))),
            ('集約・正規化後スコア', _format_score(stl_candidate.get('score'))),
            ('同一意味に集約された構文木数', _escape_or_dash(stl_candidate.get('source_count'))),
            ('STL 変換成功', _render_bool(stl_candidate.get('converted'))),
            ('STL', _render_formula_text(stl_candidate.get('stl'), is_stl=True)),
            ('STL 警告', _render_reason_list(stl_candidate.get('warnings'))),
            ('集約元構文木内スコア', _format_score(source_candidate.get('score'))),
        ])
    else:
        rows.extend([
            ('集約前スコア和', '-'),
            ('集約・正規化後スコア', '-'),
            ('同一意味に集約された構文木数', '-'),
            ('STL 変換成功', '-'),
            ('STL', '-'),
            ('STL 警告', '-'),
            ('集約元構文木内スコア', '-'),
        ])

    row_html = ''.join(
        "<tr><th>{0}</th><td>{1}</td></tr>".format(html.escape(label), value)
        for label, value in rows
    )
    return "<table class='tree-detail-table'>{0}</table>".format(row_html)



def _build_tree_block(
    sentence_label_old: str,
    sentence_surface: str,
    ccg_tree_id: str,
    ccg_tree: Optional[etree._Element],
    sem_tree: Optional[etree._Element],
    tokens: etree._Element,
    detail_table_html: str,
    error_message: Optional[str] = None,
) -> str:
    heading = "<p class='tree-heading'>{0}, tree {1}: {2}</p>".format(
        html.escape(sentence_label_old),
        html.escape(ccg_tree_id),
        html.escape(sentence_surface),
    )
    if error_message is not None:
        body = "<p class='parse-error'>{0}</p>".format(html.escape(error_message))
    else:
        body = (
            "<math xmlns='http://www.w3.org/1998/Math/MathML'>\n"
            + convert_node_to_mathml(ccg_tree, sem_tree, tokens)
            + "</math>\n"
        )
    return "<div class='tree-block'>{0}{1}{2}</div>".format(heading, body, detail_table_html)



def _build_stl_summary(sentence_stl_data: Optional[Dict[str, object]]) -> str:
    if not sentence_stl_data:
        return (
            "<section class='stl-summary'>"
            "<h3>STL とスコア</h3>"
            "<p>この文に対する STL 候補は生成されませんでした。</p>"
            "</section>"
        )

    candidates = [
        candidate
        for candidate in (sentence_stl_data.get('candidates') or [])
        if candidate.get('converted') and candidate.get('stl')
    ]
    candidates.sort(key=lambda cand: float(cand.get('score') or 0.0), reverse=True)

    if not candidates:
        return (
            "<section class='stl-summary'>"
            "<h3>STL とスコア</h3>"
            "<p>STL に変換できた候補はありませんでした。</p>"
            "</section>"
        )

    rows = []
    for rank, candidate in enumerate(candidates, start=1):
        source_tree_ids = []
        for source_candidate in candidate.get('source_candidates', []) or []:
            ccg_id = source_candidate.get('ccg_id')
            if ccg_id is not None:
                source_tree_ids.append(str(ccg_id))
        rows.append(
            "<tr>"
            "<td>{rank}</td>"
            "<td>{score}</td>"
            "<td class='formula-cell'>{stl}</td>"
            "<td>{source_count}</td>"
            "<td>{tree_ids}</td>"
            "</tr>".format(
                rank=rank,
                score=html.escape(_format_score(candidate.get('score'))),
                stl=_convert_phi_subscripts_to_html(candidate.get('stl')),
                source_count=html.escape(str(candidate.get('source_count') or 0)),
                tree_ids=html.escape(', '.join(source_tree_ids)) if source_tree_ids else '-',
            )
        )

    return """
<section class='stl-summary'>
  <h3>STL とスコア</h3>
  <table class='stl-table'>
    <thead>
      <tr>
        <th>順位</th>
        <th>スコア</th>
        <th>STL</th>
        <th>集約された構文木数</th>
        <th>構文木 ID</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</section>
""".format(rows=''.join(rows))



def _build_pipeline_error_html(error_message: str) -> str:
    return """
<section class='pipeline-error'>
  <h2>STL 変換の実行に失敗しました</h2>
  <pre>{0}</pre>
</section>
""".format(html.escape(error_message))


# ---------------------------------------------------------------------------
# Document / root conversion
# ---------------------------------------------------------------------------


def _convert_doc_to_mathml_with_count(
    doc: etree._Element,
    use_gold_trees: bool = False,
    pipeline_bundle: Optional[Dict[str, object]] = None,
    sentence_offset: int = 0,
) -> Tuple[str, int]:
    """
    Convert one XML <document> to HTML/MathML.

    The tree visualization itself follows the previous per-tree format:
      "Premise/Conclusion, tree <id>: <surface>" + MathML tree.

    In addition, each tree now gets an HTML detail table, and each sentence gets
    an STL summary produced by Canonicalization -> Aggregation -> STL_conversion.
    """
    sentences = list(doc.xpath('./sentences/sentence'))
    num_sentences = len(sentences)
    html_parts: List[str] = []

    canonical_sentences = []
    stl_sentences = []
    if pipeline_bundle:
        canonical_sentences = (pipeline_bundle.get('canonical', {}) or {}).get('sentences', []) or []
        stl_sentences = (pipeline_bundle.get('stl', {}) or {}).get('sentences', []) or []

    for local_index, sentence in enumerate(sentences):
        global_index = sentence_offset + local_index
        sentence_display_label = _sentence_display_label(global_index)
        sentence_old_label = _sentence_old_style_label(local_index, num_sentences)
        sentence_surface = get_surf_from_xml_node(sentence)

        html_parts.append("<section class='sentence-section'>")
        html_parts.append("<h2>{0}</h2>".format(html.escape(sentence_display_label)))

        ccg_nodes = list(sentence.xpath('./ccg'))
        semantics_nodes = list(sentence.xpath('./semantics'))
        matched_semantics = _match_semantics_to_ccgs(ccg_nodes, semantics_nodes)
        tokens_nodes = sentence.xpath('./tokens')
        tokens = tokens_nodes[0] if tokens_nodes else etree.Element('tokens')
        gold_tree_index = int(sentence.get('gold_tree', '-1'))

        canonical_sentence = canonical_sentences[global_index] if global_index < len(canonical_sentences) else None
        stl_sentence = stl_sentences[global_index] if global_index < len(stl_sentences) else None
        canonical_by_ccg_id = _canonical_candidate_map(canonical_sentence)
        stl_by_ccg_id = _stl_source_map(stl_sentence)

        selected_indices: Iterable[int]
        if use_gold_trees and 0 <= gold_tree_index < len(ccg_nodes):
            selected_indices = [gold_tree_index]
        else:
            selected_indices = range(len(ccg_nodes))

        for ccg_index in selected_indices:
            ccg_node = ccg_nodes[ccg_index]
            ccg_tree_id = ccg_node.get('id') or str(ccg_index)
            visible_tree_id = ccg_tree_id + (' (gold)' if gold_tree_index == ccg_index and use_gold_trees else '')

            canonical_candidate = canonical_by_ccg_id.get(ccg_tree_id)
            stl_mapping = stl_by_ccg_id.get(ccg_tree_id)
            detail_table_html = _build_tree_detail_table(ccg_node, canonical_candidate, stl_mapping)

            try:
                ccg_tree = build_ccg_tree(ccg_node)
                sem_node = matched_semantics.get(ccg_index)
                sem_tree = build_ccg_tree(sem_node) if sem_node is not None else None
                html_parts.append(
                    _build_tree_block(
                        sentence_old_label,
                        sentence_surface,
                        visible_tree_id,
                        ccg_tree,
                        sem_tree,
                        tokens,
                        detail_table_html,
                    )
                )
            except Exception as exc:
                html_parts.append(
                    _build_tree_block(
                        sentence_old_label,
                        sentence_surface,
                        visible_tree_id,
                        None,
                        None,
                        tokens,
                        detail_table_html,
                        error_message='Syntactic parse error. Visualization skipped. ({0})'.format(exc),
                    )
                )

        html_parts.append(_build_stl_summary(stl_sentence))
        html_parts.append("</section>")

    verbatim_strings = doc.xpath('./proof/master_theorem/theorems/theorem/coq_script/text()')
    if verbatim_strings:
        html_parts.append("<p>Script piped to coq</p>")
        for vb_str in verbatim_strings:
            html_parts.append("<pre>{0}</pre>".format(html.escape(vb_str)))

    return '\n'.join(html_parts), num_sentences



def wrap_mathml_in_html(mathml_str: str) -> str:
    html_str = """<!DOCTYPE html>
<html lang='ja'>
<head>
  <meta charset='UTF-8'/>
  <title>CCG to Lambda conversion</title>
  <style>
    body {
      font-size: 1em;
      line-height: 1.5;
      margin: 1.2rem;
    }
    .sentence-section {
      margin-bottom: 2.5rem;
      padding-bottom: 1.5rem;
      border-bottom: 1px solid #ccc;
    }
    .tree-block {
      margin: 1.1rem 0 1.8rem 0;
    }
    .tree-heading {
      font-weight: bold;
      margin: 0.6rem 0 0.4rem 0;
    }
    math {
      display: block;
      margin: 0.4rem 0 0.8rem 0;
      overflow-x: auto;
    }
    .tree-detail-table,
    .stl-table {
      border-collapse: collapse;
      width: 100%;
      margin-top: 0.5rem;
    }
    .tree-detail-table th,
    .tree-detail-table td,
    .stl-table th,
    .stl-table td {
      border: 1px solid #ccc;
      padding: 0.35rem 0.55rem;
      vertical-align: top;
      text-align: left;
    }
    .tree-detail-table th {
      width: 15rem;
      background: #f7f7f7;
    }
    .stl-table th {
      background: #f7f7f7;
    }
    .formula-cell,
    .tree-detail-table code {
      word-break: break-word;
    }
    .status-yes {
      font-weight: bold;
    }
    .status-no {
      font-weight: bold;
    }
    .pipeline-error {
      border: 1px solid #d99;
      background: #fff6f6;
      padding: 1rem;
      margin-bottom: 1.5rem;
    }
    .parse-error {
      color: #a00;
      font-weight: bold;
    }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
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
    Convert an XML root to a single HTML document.

    The output is a single HTML file, grouped by sentence. Inside each sentence,
    each parse tree is rendered in the previous per-tree format and supplemented
    with score/details tables. STL candidates are shown sentence by sentence.
    """
    xml_path, tmp_path = _extract_xml_path_from_root(root)
    pipeline_bundle: Optional[Dict[str, object]] = None
    pipeline_error_html = ''
    try:
        pipeline_bundle = _run_pipeline_from_xml_path(str(xml_path))
    except Exception as exc:
        pipeline_error_html = _build_pipeline_error_html(str(exc))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    doc_html_parts: List[str] = []
    sentence_offset = 0
    for doc_ind, doc in enumerate(root.xpath('./document')):
        doc_id = doc.get('id') or str(doc_ind)
        doc_html_parts.append("<section class='document-section' data-doc-id='{0}'>".format(html.escape(str(doc_id))))
        inner_html, consumed_sentences = _convert_doc_to_mathml_with_count(
            doc,
            use_gold_trees=use_gold_trees,
            pipeline_bundle=pipeline_bundle,
            sentence_offset=sentence_offset,
        )
        doc_html_parts.append(inner_html)
        doc_html_parts.append("</section>")
        sentence_offset += consumed_sentences

    body_html = pipeline_error_html + '\n'.join(doc_html_parts)
    return wrap_mathml_in_html(body_html)


def convert_doc_to_mathml(doc, use_gold_trees=False):
    html_body, _ = _convert_doc_to_mathml_with_count(doc, use_gold_trees=use_gold_trees)
    return html_body


# Backward-compatible helper retained because some code may still import it.
def convert_doc_to_mathml_(doc, verbatim_strings=None, use_gold_trees=False):
    html_body = convert_doc_to_mathml(doc, use_gold_trees=use_gold_trees)
    return wrap_mathml_in_html(html_body)
