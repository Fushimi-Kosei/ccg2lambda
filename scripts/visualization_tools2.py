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
import math
import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

from lxml import etree

from ccg2lambda_tools import build_ccg_tree
from semantic_index import find_node_by_id

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

_PIPELINE_FUNCTIONS: Optional[Dict[str, Any]] = None
_PHI_RE = re.compile(r'Φ_([A-Za-z0-9]+)')


# ============================================================
# MathML rendering helpers (original behavior preserved)
# ============================================================


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
            surf_mathml = get_surface_mathml('')
            mathml_pos_str = get_fraction_mathml(category_mathml, get_pos_mathml(''), '0')
            mathml_str = get_fraction_mathml(mathml_pos_str, surf_mathml, '0')
        else:
            surf = token.get('surf') or token.get('base') or ''
            surf_mathml = get_surface_mathml(surf)
            pos = token.get('pos') or ''
            pos_mathml = get_pos_mathml(pos)
            entity = token.get('entity')
            if entity is not None:
                entity_mathml = get_entity_mathml(entity)
                pos_mathml = pos_mathml + "<mtext>,</mtext><mspace width='.1em'/>" + entity_mathml
            pos1 = token.get('pos1')
            if not (pos1 is None or pos1 == '*'):
                pos1_mathml = get_pos_mathml(pos1)
                pos_mathml = pos_mathml + "<mspace width='.1em'/>" + pos1_mathml
            pos2 = token.get('pos2')
            if not (pos2 is None or pos2 == '*'):
                pos2_mathml = get_pos_mathml(pos2)
                pos_mathml = pos_mathml + "<mspace width='.1em'/>" + pos2_mathml
            pos3 = token.get('pos3')
            if not (pos3 is None or pos3 == '*'):
                pos3_mathml = get_pos_mathml(pos3)
                pos_mathml = pos_mathml + "<mspace width='.1em'/>" + pos3_mathml
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
            semantics = sem_node.get('sem', '')
            semantics_mathml = get_semantics_mathml(semantics)
            mathml_str = get_fraction_mathml(semantics_mathml, mathml_str, '0')
    return mathml_str



def get_surf_from_xml_node(node):
    tokens = node.xpath("./tokens/token[not(@surf='*')]/@surf | ./tokens/token[@surf='*']/@base")
    return ' '.join(tokens)


# ============================================================
# Pipeline loading and execution
# ============================================================


def _module_file_path(stem: str) -> Path:
    return Path(__file__).resolve().with_name(f"{stem}.py")



def _load_function_from_module(module_stem: str, function_name: str):
    module_path = _module_file_path(module_stem)
    if not module_path.exists():
        raise FileNotFoundError(f"Required module file not found: {module_path}")

    module_name = f"_visualization_pipeline_{module_stem}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec for {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    if not hasattr(module, function_name):
        raise AttributeError(f"{module_path.name} does not define {function_name}()")
    return getattr(module, function_name)



def _load_pipeline_functions() -> Dict[str, Any]:
    global _PIPELINE_FUNCTIONS
    if _PIPELINE_FUNCTIONS is None:
        _PIPELINE_FUNCTIONS = {
            'canonicalize_xml': _load_function_from_module('Canonicalization', 'canonicalize_xml'),
            'aggregate_same_semantics': _load_function_from_module('Aggregation', 'aggregate_same_semantics'),
            'convert_items': _load_function_from_module('STL_conversion', 'convert_items'),
        }
    return _PIPELINE_FUNCTIONS



def _get_element_tree(root_or_tree) -> etree._ElementTree:
    if isinstance(root_or_tree, etree._ElementTree):
        return root_or_tree
    if isinstance(root_or_tree, etree._Element):
        return root_or_tree.getroottree()
    raise TypeError(f"Unsupported XML object type: {type(root_or_tree)!r}")



def _url_to_local_path(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    if os.path.exists(url):
        return url
    parsed = urlparse(url)
    if parsed.scheme == 'file':
        candidate = unquote(parsed.path)
        if os.path.exists(candidate):
            return candidate
    return None



def _resolve_xml_path(root_or_tree) -> Tuple[str, Optional[str]]:
    tree = _get_element_tree(root_or_tree)
    url_path = _url_to_local_path(getattr(tree.docinfo, 'URL', None))
    if url_path is not None:
        return url_path, None

    tmp = tempfile.NamedTemporaryFile(mode='wb', suffix='.xml', delete=False)
    try:
        tree.write(
            tmp,
            encoding='utf-8',
            xml_declaration=True,
            pretty_print=True,
        )
        tmp.close()
    except Exception:
        try:
            tmp.close()
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)
        raise
    return tmp.name, tmp.name



def _build_global_index_map(items: Sequence[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    result: Dict[int, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        global_index = item.get('global_index')
        if isinstance(global_index, int):
            result[global_index] = item
    return result



def _build_member_global_index_map(items: Sequence[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    result: Dict[int, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        member_global_indices = item.get('member_global_indices', [])
        if isinstance(member_global_indices, list):
            for global_index in member_global_indices:
                if isinstance(global_index, int):
                    result[global_index] = item
        global_index = item.get('global_index')
        if isinstance(global_index, int) and global_index not in result:
            result[global_index] = item
    return result



def _append_unique_ints(target: List[int], values: Iterable[Any]) -> None:
    seen = set(target)
    for value in values:
        if isinstance(value, int) and value not in seen:
            target.append(value)
            seen.add(value)



def _append_unique_strings(target: List[str], values: Iterable[Any]) -> None:
    seen = set(target)
    for value in values:
        if isinstance(value, str) and value not in seen:
            target.append(value)
            seen.add(value)



def _sentence_bucket_key_from_item(item: Dict[str, Any], fallback_index: int) -> Tuple[str, Any]:
    sentence_index = item.get('sentence_index')
    if isinstance(sentence_index, int):
        return ('sentence_index', sentence_index)
    sentence_id = item.get('sentence_id')
    if isinstance(sentence_id, str) and sentence_id != '':
        return ('sentence_id', sentence_id)
    global_index = item.get('global_index')
    if isinstance(global_index, int):
        return ('global_index', global_index)
    return ('fallback_index', fallback_index)



def _sentence_display_label(section_or_item: Dict[str, Any], sentence_ordinal: int) -> str:
    sentence_index = section_or_item.get('sentence_index')
    sentence_id = section_or_item.get('sentence_id')
    if isinstance(sentence_index, int):
        base_label = f'Sentence {sentence_index + 1}'
    else:
        base_label = f'Sentence {sentence_ordinal + 1}'
    if isinstance(sentence_id, str) and sentence_id:
        return f'{base_label} (id: {sentence_id})'
    return base_label



def _normalize_scores_to_one(scores: Sequence[float]) -> List[float]:
    if not scores:
        return []
    if len(scores) == 1:
        return [1.0]

    nonnegative = [max(0.0, float(score)) for score in scores]
    total = math.fsum(nonnegative)
    if total <= 0.0 or not math.isfinite(total):
        uniform = 1.0 / len(nonnegative)
        normalized = [uniform for _ in nonnegative]
    else:
        normalized = [score / total for score in nonnegative]

    running = math.fsum(normalized[:-1])
    last = 1.0 - running
    if last < 0.0 and abs(last) < 1e-15:
        last = 0.0
    if last < 0.0:
        clipped = [max(0.0, score) for score in normalized]
        clipped_total = math.fsum(clipped)
        if clipped_total <= 0.0:
            uniform = 1.0 / len(clipped)
            clipped = [uniform for _ in clipped]
        else:
            clipped = [score / clipped_total for score in clipped]
        running = math.fsum(clipped[:-1])
        last = 1.0 - running
        if last < 0.0 and abs(last) < 1e-15:
            last = 0.0
        clipped[-1] = max(0.0, last)
        normalized = clipped
    else:
        normalized[-1] = last

    final_total = math.fsum(normalized)
    if final_total <= 0.0:
        uniform = 1.0 / len(normalized)
        normalized = [uniform for _ in normalized]
        normalized[-1] = 1.0 - math.fsum(normalized[:-1])
    elif abs(final_total - 1.0) > 1e-15:
        normalized = [score / final_total for score in normalized]
        normalized[-1] = 1.0 - math.fsum(normalized[:-1])

    return normalized



def _aggregate_same_stl(
    converted: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[int, Dict[str, Any]]]:
    """
    STL の集約と正規化は文ごとに行う。
    返り値:
      - sentence_sections: 文ごとの STL 集約結果
      - flat_stl_groups: 全文の STL グループを平坦化したもの
      - stl_group_by_global_index: 各元の global_index から属する文内 STL グループへの写像
    """
    sentence_buckets: Dict[Tuple[str, Any], Dict[str, Any]] = {}
    sentence_order: List[Tuple[str, Any]] = []

    for item_index, item in enumerate(converted.get('items', [])):
        if not isinstance(item, dict):
            continue

        bucket_key = _sentence_bucket_key_from_item(item, item_index)
        if bucket_key not in sentence_buckets:
            sentence_buckets[bucket_key] = {
                'sentence_index': item.get('sentence_index'),
                'sentence_id': item.get('sentence_id'),
                'group_order': [],
                'grouped': {},
            }
            sentence_order.append(bucket_key)

        if item.get('conversion_error'):
            continue

        stl = item.get('stl')
        if not isinstance(stl, str) or not stl.strip():
            continue

        sentence_bucket = sentence_buckets[bucket_key]
        grouped = sentence_bucket['grouped']
        group_order = sentence_bucket['group_order']

        if stl not in grouped:
            grouped[stl] = {
                'stl': stl,
                'raw_score_sum': 0.0,
                'score': 0.0,
                'aggregate_item_count': 0,
                'tree_count': 0,
                'member_aggregate_indices': [],
                'member_global_indices': [],
                'member_tree_ids': [],
                'canonical_semantics_list': [],
                'sentence_index': item.get('sentence_index'),
                'sentence_id': item.get('sentence_id'),
            }
            group_order.append(stl)

        group = grouped[stl]
        try:
            group['raw_score_sum'] += float(item.get('score', 0.0))
        except Exception:
            pass

        aggregate_index = item.get('aggregate_index')
        if isinstance(aggregate_index, int) and aggregate_index not in group['member_aggregate_indices']:
            group['member_aggregate_indices'].append(aggregate_index)
            group['aggregate_item_count'] = len(group['member_aggregate_indices'])

        _append_unique_ints(group['member_global_indices'], item.get('member_global_indices', []))

        tree_id = item.get('tree_id')
        if isinstance(tree_id, str) and tree_id not in group['member_tree_ids']:
            group['member_tree_ids'].append(tree_id)

        canonical_semantics = item.get('canonical_semantics')
        if isinstance(canonical_semantics, str):
            _append_unique_strings(group['canonical_semantics_list'], [canonical_semantics])

    sentence_sections: List[Dict[str, Any]] = []
    flat_stl_groups: List[Dict[str, Any]] = []
    stl_group_by_global_index: Dict[int, Dict[str, Any]] = {}

    for sentence_ordinal, bucket_key in enumerate(sentence_order):
        sentence_bucket = sentence_buckets[bucket_key]
        group_order = sentence_bucket['group_order']
        grouped = sentence_bucket['grouped']
        raw_scores = [float(grouped[stl].get('raw_score_sum', 0.0)) for stl in group_order]
        normalized_scores = _normalize_scores_to_one(raw_scores)
        sentence_groups: List[Dict[str, Any]] = []

        for stl_group_index, (stl, normalized_score) in enumerate(zip(group_order, normalized_scores)):
            group = grouped[stl]
            group['score'] = float(normalized_score)
            group['stl_group_index'] = stl_group_index
            group['tree_count'] = len(group['member_global_indices'])
            group['display_label'] = _sentence_display_label(sentence_bucket, sentence_ordinal)
            sentence_groups.append(group)
            flat_stl_groups.append(group)
            for global_index in group['member_global_indices']:
                stl_group_by_global_index[global_index] = group

        sentence_sections.append(
            {
                'sentence_key': bucket_key,
                'sentence_index': sentence_bucket.get('sentence_index'),
                'sentence_id': sentence_bucket.get('sentence_id'),
                'display_label': _sentence_display_label(sentence_bucket, sentence_ordinal),
                'groups': sentence_groups,
                'score_total': math.fsum(float(group.get('score', 0.0)) for group in sentence_groups),
            }
        )

    return sentence_sections, flat_stl_groups, stl_group_by_global_index



def _run_stl_pipeline(root_or_tree) -> Dict[str, Any]:
    functions = _load_pipeline_functions()
    xml_path, temporary_path = _resolve_xml_path(root_or_tree)
    try:
        # Required order and direct hand-off:
        # Canonicalization.py output -> Aggregation.py input
        canonicalized = functions['canonicalize_xml'](xml_path)
        # Aggregation.py output -> STL_conversion.py input
        aggregated = functions['aggregate_same_semantics'](canonicalized)
        converted = functions['convert_items'](aggregated)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)

    stl_sentence_sections, stl_groups, stl_group_by_global_index = _aggregate_same_stl(converted)

    return {
        'canonicalized': canonicalized,
        'aggregated': aggregated,
        'converted': converted,
        'stl_groups': stl_groups,
        'stl_sentence_sections': stl_sentence_sections,
        'stl_group_by_global_index': stl_group_by_global_index,
        'canonical_kept_by_global_index': _build_global_index_map(canonicalized.get('items', [])),
        'canonical_rejected_by_global_index': _build_global_index_map(canonicalized.get('rejected_items', [])),
        'aggregation_rejected_by_global_index': _build_global_index_map(aggregated.get('rejected_items', [])),
        'converted_by_global_index': _build_member_global_index_map(converted.get('items', [])),
    }

# ============================================================
# HTML formatting helpers
# ============================================================


def _format_score(value: Any) -> str:
    if value is None or value == '':
        return '—'
    try:
        return '{0:.12g}'.format(float(value))
    except Exception:
        return html.escape(str(value))



def _format_inline_code(text: Any) -> str:
    if text is None or text == '':
        return '—'
    return "<code class='inline-code'>{0}</code>".format(html.escape(str(text)))



def _format_stl_for_html(stl_text: Any) -> str:
    if stl_text is None or stl_text == '':
        return '—'
    escaped = html.escape(str(stl_text))
    escaped = _PHI_RE.sub(lambda m: 'Φ<sub>{0}</sub>'.format(html.escape(m.group(1))), escaped)
    return "<span class='stl-expression'>{0}</span>".format(escaped)



def _render_row(label: str, value: Any, *, is_html: bool = False) -> str:
    if value is None or value == '':
        return ''
    content = value if is_html else html.escape(str(value))
    return (
        "<div class='panel-row'>"
        "<div class='panel-label'>{0}</div>"
        "<div class='panel-value'>{1}</div>"
        "</div>"
    ).format(html.escape(label), content)



def _render_status_panel(title: str, rows: Sequence[str], *, extra_class: str = '') -> str:
    classes = 'stl-panel'
    if extra_class:
        classes += ' ' + extra_class
    return (
        "<div class='{0}'>"
        "<div class='panel-title'>{1}</div>"
        "{2}"
        "</div>"
    ).format(classes, html.escape(title), ''.join(row for row in rows if row))



def _render_summary_cards(pipeline_context: Dict[str, Any]) -> str:
    canonical_summary = pipeline_context['canonicalized'].get('summary', {})
    aggregation_summary = pipeline_context['aggregated'].get('summary', {})
    conversion_summary = pipeline_context['converted'].get('summary', {})
    sentence_sections = pipeline_context.get('stl_sentence_sections', [])
    total_stl_groups = sum(len(section.get('groups', [])) for section in sentence_sections)

    cards = [
        ('Sentences', _format_score(len(sentence_sections))),
        ('Canonical kept', _format_score(canonical_summary.get('kept'))),
        ('Canonical rejected', _format_score(canonical_summary.get('rejected'))),
        ('Unique semantics', _format_score(aggregation_summary.get('unique_items'))),
        ('Converted semantics', _format_score(conversion_summary.get('converted_items'))),
        ('Conversion errors', _format_score(conversion_summary.get('conversion_errors'))),
        ('Aggregated STL groups', _format_score(total_stl_groups)),
    ]
    return ''.join(
        (
            "<div class='summary-card'>"
            "<div class='summary-label'>{0}</div>"
            "<div class='summary-value'>{1}</div>"
            "</div>"
        ).format(html.escape(label), value)
        for label, value in cards
    )



def _render_aggregated_stl_section(pipeline_context: Dict[str, Any]) -> str:
    sentence_sections = pipeline_context.get('stl_sentence_sections', [])
    if not sentence_sections:
        return (
            "<section class='pipeline-summary'>"
            "<h1>Aggregated STL by sentence</h1>"
            "<p class='pipeline-message'>No sentence-level STL information was produced.</p>"
            "</section>"
        )

    has_any_group = any(section.get('groups') for section in sentence_sections)
    if not has_any_group:
        return (
            "<section class='pipeline-summary'>"
            "<h1>Aggregated STL by sentence</h1>"
            "<div class='summary-grid'>{0}</div>"
            "<p class='pipeline-message'>No successful STL conversion was produced.</p>"
            "</section>"
        ).format(_render_summary_cards(pipeline_context))

    section_blocks: List[str] = []
    for section in sentence_sections:
        groups = section.get('groups', [])
        heading = html.escape(str(section.get('display_label', 'Sentence')))
        if not groups:
            section_blocks.append(
                (
                    "<div class='sentence-stl-block'>"
                    "<h2 class='sentence-stl-heading'>{0}</h2>"
                    "<p class='pipeline-message'>No successful STL conversion was produced for this sentence.</p>"
                    "</div>"
                ).format(heading)
            )
            continue

        rows = []
        for group in groups:
            canonical_semantics_html = '<br/>'.join(
                _format_inline_code(text) for text in group.get('canonical_semantics_list', [])
            ) or '—'
            rows.append(
                "<tr>"
                "<td>{0}</td>"
                "<td>{1}</td>"
                "<td>{2}</td>"
                "<td>{3}</td>"
                "<td>{4}</td>"
                "</tr>".format(
                    html.escape(str(group.get('stl_group_index', 0) + 1)),
                    _format_score(group.get('score')),
                    _format_stl_for_html(group.get('stl')),
                    html.escape(str(group.get('tree_count', 0))),
                    canonical_semantics_html,
                )
            )

        section_blocks.append(
            (
                "<div class='sentence-stl-block'>"
                "<h2 class='sentence-stl-heading'>{0}</h2>"
                "<p class='sentence-stl-total'>Sentence-local normalized score total: {1}</p>"
                "<div class='table-wrap'>"
                "<table class='stl-table'>"
                "<thead>"
                "<tr>"
                "<th>#</th>"
                "<th>Normalized score</th>"
                "<th>STL</th>"
                "<th>Trees</th>"
                "<th>Canonical semantics</th>"
                "</tr>"
                "</thead>"
                "<tbody>{2}</tbody>"
                "</table>"
                "</div>"
                "</div>"
            ).format(
                heading,
                _format_score(section.get('score_total')),
                ''.join(rows),
            )
        )

    return (
        "<section class='pipeline-summary'>"
        "<h1>Aggregated STL by sentence</h1>"
        "<div class='summary-grid'>{0}</div>"
        "{1}"
        "</section>"
    ).format(_render_summary_cards(pipeline_context), ''.join(section_blocks))


def _render_pipeline_summary(pipeline_context: Optional[Dict[str, Any]], pipeline_error: Optional[BaseException]) -> str:
    if pipeline_error is not None:
        return (
            "<section class='pipeline-summary pipeline-summary-error'>"
            "<h1>STL pipeline</h1>"
            "<p class='pipeline-message'>The CCG trees were rendered, but the STL pipeline failed.</p>"
            "<pre class='pipeline-error-text'>{0}</pre>"
            "</section>"
        ).format(html.escape(str(pipeline_error)))
    if pipeline_context is None:
        return ''
    return _render_aggregated_stl_section(pipeline_context)



def _render_tree_annotation(
    global_semantics_index: Optional[int],
    pipeline_context: Optional[Dict[str, Any]],
    has_semantics_tree: bool,
) -> str:
    if not has_semantics_tree:
        return _render_status_panel(
            'STL result',
            ["<div class='panel-note'>No paired &lt;semantics&gt; node was found for this tree.</div>"],
            extra_class='stl-panel-muted',
        )

    if pipeline_context is None or global_semantics_index is None:
        return ''

    canonical_rejected = pipeline_context['canonical_rejected_by_global_index'].get(global_semantics_index)
    if canonical_rejected is not None:
        rows = [
            _render_row('Status', 'Filtered out during canonicalization'),
            _render_row('Reason', canonical_rejected.get('reason')),
            _render_row('Original semantics', _format_inline_code(canonical_rejected.get('original_semantics')), is_html=True),
        ]
        rejected_functions = canonical_rejected.get('rejected_functions')
        if isinstance(rejected_functions, list) and rejected_functions:
            rows.append(_render_row('Rejected functions', ', '.join(html.escape(str(x)) for x in rejected_functions), is_html=True))
        return _render_status_panel('STL result', rows, extra_class='stl-panel-warning')

    aggregation_rejected = pipeline_context['aggregation_rejected_by_global_index'].get(global_semantics_index)
    if aggregation_rejected is not None:
        rows = [
            _render_row('Status', 'Rejected during aggregation'),
            _render_row('Reason', aggregation_rejected.get('reason')),
            _render_row('Canonical semantics', _format_inline_code(aggregation_rejected.get('canonical_semantics')), is_html=True),
            _render_row('Original score', aggregation_rejected.get('raw_score')),
        ]
        return _render_status_panel('STL result', rows, extra_class='stl-panel-warning')

    converted_item = pipeline_context['converted_by_global_index'].get(global_semantics_index)
    if converted_item is None:
        canonical_kept = pipeline_context['canonical_kept_by_global_index'].get(global_semantics_index)
        if canonical_kept is not None:
            rows = [
                _render_row('Status', 'No downstream aggregation / conversion result found'),
                _render_row('Canonical semantics', _format_inline_code(canonical_kept.get('canonical_semantics')), is_html=True),
                _render_row('Score', _format_score(canonical_kept.get('score'))),
            ]
            return _render_status_panel('STL result', rows, extra_class='stl-panel-muted')
        return _render_status_panel(
            'STL result',
            ["<div class='panel-note'>No STL pipeline information was found for this tree.</div>"],
            extra_class='stl-panel-muted',
        )

    rows = [
        _render_row('Canonical semantics', _format_inline_code(converted_item.get('canonical_semantics')), is_html=True),
        _render_row('Normalized score (sentence-local semantics)', _format_score(converted_item.get('score'))),
    ]

    if converted_item.get('conversion_error'):
        rows.append(_render_row('Status', 'STL conversion failed'))
        rows.append(_render_row('Conversion error', converted_item.get('conversion_error')))
        return _render_status_panel('STL result', rows, extra_class='stl-panel-warning')

    stl_group = pipeline_context['stl_group_by_global_index'].get(global_semantics_index)
    if stl_group is not None:
        rows.append(_render_row('Aggregated STL', _format_stl_for_html(stl_group.get('stl')), is_html=True))
        rows.append(_render_row('Normalized score (sentence-local same STL)', _format_score(stl_group.get('score'))))
        rows.append(_render_row('Sentence STL group index', stl_group.get('stl_group_index', 0) + 1))
        rows.append(_render_row('Trees in same STL (same sentence)', stl_group.get('tree_count')))
    else:
        rows.append(_render_row('STL', _format_stl_for_html(converted_item.get('stl')), is_html=True))

    occurrence_count = converted_item.get('occurrence_count')
    if isinstance(occurrence_count, int) and occurrence_count > 1:
        rows.append(_render_row('Merged identical semantics', occurrence_count))

    return _render_status_panel('STL result', rows)

# ============================================================
# HTML shell
# ============================================================


def wrap_mathml_in_html(mathml_str):
    html_str = """\
    <!DOCTYPE html>
    <html lang='en'>
    <head>
      <meta charset='UTF-8'/>
      <title>CCG to Lambda conversion</title>
      <style>
        body {
          font-size: 1em;
          line-height: 1.45;
          margin: 1.25rem auto;
          padding: 0 1rem 2rem 1rem;
          max-width: 1200px;
          color: #222;
          background: #fff;
        }
        .pipeline-summary {
          margin-bottom: 2rem;
          padding: 1rem 1.1rem;
          border: 1px solid #dddddd;
          border-radius: 10px;
          background: #fafafa;
        }
        .pipeline-summary-error {
          background: #fff5f5;
          border-color: #e6b8b8;
        }
        .pipeline-summary h1 {
          margin: 0 0 0.8rem 0;
          font-size: 1.25rem;
        }
        .pipeline-message {
          margin: 0.3rem 0 0 0;
        }
        .pipeline-error-text {
          white-space: pre-wrap;
          word-break: break-word;
          margin: 0.7rem 0 0 0;
        }
        .summary-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 0.75rem;
          margin-bottom: 1rem;
        }
        .summary-card {
          padding: 0.75rem 0.85rem;
          border: 1px solid #e2e2e2;
          border-radius: 8px;
          background: #ffffff;
        }
        .summary-label {
          font-size: 0.9rem;
          color: #555;
          margin-bottom: 0.2rem;
        }
        .summary-value {
          font-size: 1.15rem;
          font-weight: 600;
        }
        .table-wrap {
          overflow-x: auto;
        }
        .stl-table {
          width: 100%;
          border-collapse: collapse;
        }
        .stl-table th,
        .stl-table td {
          border: 1px solid #e3e3e3;
          padding: 0.55rem 0.6rem;
          text-align: left;
          vertical-align: top;
        }
        .stl-table th {
          background: #f2f2f2;
        }
        .sentence-stl-block {
          margin-top: 1.15rem;
        }
        .sentence-stl-heading {
          margin: 0 0 0.4rem 0;
          font-size: 1.05rem;
        }
        .sentence-stl-total {
          margin: 0 0 0.65rem 0;
          color: #555;
        }
        .tree-block {
          margin-bottom: 2rem;
          padding-bottom: 1.25rem;
          border-bottom: 1px solid #e5e5e5;
        }
        .tree-heading {
          font-weight: 600;
          margin: 0 0 0.7rem 0;
        }
        .stl-panel {
          margin-top: 0.9rem;
          padding: 0.85rem 1rem;
          border: 1px solid #dfdfdf;
          border-radius: 8px;
          background: #fbfbfb;
        }
        .stl-panel-warning {
          background: #fff9ef;
          border-color: #eed8a8;
        }
        .stl-panel-muted {
          background: #f7f7f7;
          border-color: #dfdfdf;
          color: #666;
        }
        .panel-title {
          font-weight: 700;
          margin-bottom: 0.5rem;
        }
        .panel-row {
          display: grid;
          grid-template-columns: minmax(170px, 260px) 1fr;
          gap: 0.6rem;
          align-items: start;
          margin-top: 0.35rem;
        }
        .panel-label {
          font-weight: 600;
          color: #333;
        }
        .panel-value {
          white-space: pre-wrap;
          word-break: break-word;
        }
        .panel-note {
          color: #666;
        }
        .inline-code,
        .stl-expression {
          font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", monospace;
        }
        .inline-code {
          white-space: pre-wrap;
          word-break: break-word;
        }
        .stl-expression {
          font-size: 1.04em;
        }
        math {
          overflow-x: auto;
          display: block;
          margin-top: 0.25rem;
        }
      </style>
      <script type="text/javascript"
              src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.1/MathJax.js?config=TeX-AMS-MML_HTMLorMML">
      </script>
    </head>
    <body>
    """
    html_str += mathml_str
    html_str += """\
    </body>
    </html>
    """
    return html_str


# ============================================================
# Document rendering
# ============================================================


def convert_doc_to_mathml(doc, use_gold_trees=False, pipeline_context=None, state=None):
    """
    Convert one XML <document> into presentation MathML and append STL panels.
    Tree order is preserved.
    """
    if state is None:
        state = {'next_semantics_index': 0}

    num_sentences = int(doc.xpath('count(./sentences/sentence)'))
    mathml_str = ""
    for sent_ind, sentence in enumerate(doc.xpath('./sentences/sentence')):
        gold_tree_index = int(sentence.get('gold_tree', -1))
        if sent_ind < num_sentences - 1:
            sentence_label = 'Premise {0}'.format(sent_ind)
        else:
            sentence_label = 'Conclusion'
        sentence_text = get_surf_from_xml_node(sentence)
        ccg_trees = sentence.xpath('./ccg')
        sem_trees = sentence.xpath('./semantics')
        tokens = sentence.xpath('./tokens')
        if not tokens:
            return mathml_str
        tokens = tokens[0]
        assert len(ccg_trees) >= len(sem_trees)

        for i in range(len(ccg_trees)):
            ccg_tree_id = ccg_trees[i].get('id', str(i))
            display_tree_id = ccg_tree_id + ' (gold)' if gold_tree_index == i else ccg_tree_id
            raw_sem_tree = None if i >= len(sem_trees) else sem_trees[i]
            global_semantics_index = None
            if raw_sem_tree is not None:
                global_semantics_index = state.get('next_semantics_index', 0)
                state['next_semantics_index'] = global_semantics_index + 1

            heading_text = '{0}, tree {1}: {2}'.format(sentence_label, display_tree_id, sentence_text)

            try:
                ccg_tree = build_ccg_tree(ccg_trees[i])
            except ValueError:
                mathml_str += (
                    "<section class='tree-block'>"
                    "<p class='tree-heading'>{0}</p>"
                    "<p>Syntactic parse error. Visualization skipped.</p>"
                    "{1}"
                    "</section>"
                ).format(
                    html.escape(heading_text),
                    _render_tree_annotation(global_semantics_index, pipeline_context, raw_sem_tree is not None),
                )
                continue

            sem_tree = None
            if raw_sem_tree is not None:
                try:
                    sem_tree = build_ccg_tree(raw_sem_tree)
                except ValueError:
                    sem_tree = None

            mathml_str += (
                "<section class='tree-block'>"
                "<p class='tree-heading'>{0}</p>"
                "<math xmlns='http://www.w3.org/1998/Math/MathML'>\n"
                "{1}"
                "</math>\n"
                "{2}"
                "</section>\n"
            ).format(
                html.escape(heading_text),
                convert_node_to_mathml(ccg_tree, sem_tree, tokens),
                _render_tree_annotation(global_semantics_index, pipeline_context, raw_sem_tree is not None),
            )

    verbatim_strings = doc.xpath('./proof/master_theorem/theorems/theorem/coq_script/text()')
    verbatim_text = ""
    if verbatim_strings:
        verbatim_text = "<p>Script piped to coq</p>"
        for vb_str in verbatim_strings:
            verbatim_text += "<pre>\n" + html.escape(vb_str) + "\n</pre>\n"
    return '{0}\n{1}'.format(mathml_str, verbatim_text)



def convert_root_to_mathml(root, use_gold_trees=False):
    """
    Convert the XML root / tree into HTML.

    visualize.py can keep calling this function unchanged. Internally, this
    function runs the STL pipeline in the required order:

      Canonicalization.py -> Aggregation.py -> STL_conversion.py

    with direct in-memory hand-off between the three steps.
    """
    pipeline_context = None
    pipeline_error = None
    try:
        pipeline_context = _run_stl_pipeline(root)
    except Exception as exc:
        pipeline_error = exc

    tree = _get_element_tree(root)
    documents = tree.xpath('./document')
    if not documents:
        root_elem = tree.getroot()
        if etree.QName(root_elem.tag).localname == 'document':
            documents = [root_elem]

    doc_mathml_strs = []
    state = {'next_semantics_index': 0}
    for doc in documents:
        doc_mathml_strs.append(
            convert_doc_to_mathml(
                doc,
                use_gold_trees=use_gold_trees,
                pipeline_context=pipeline_context,
                state=state,
            )
        )

    return wrap_mathml_in_html(
        _render_pipeline_summary(pipeline_context, pipeline_error)
        + '\n'.join(doc_mathml_strs)
    )


# ============================================================
# Backward-compatible helper kept for callers that might still import it
# ============================================================


def convert_doc_to_mathml_(doc, verbatim_strings=None, use_gold_trees=False):
    if verbatim_strings is None:
        verbatim_strings = []

    ccg_trees = []
    if use_gold_trees:
        for sentence in doc.xpath('./sentences/sentence'):
            gold_tree_index = int(sentence.get('gold_tree', '0'))
            ccg_trees.append(sentence.xpath('./ccg')[gold_tree_index])
        ccg_trees = [build_ccg_tree(c) for c in ccg_trees]
    else:
        ccg_trees = [build_ccg_tree(c) for c in doc.xpath('./sentences/sentence/ccg[1]')]
    sem_trees = [build_ccg_tree(c) for c in doc.xpath('./sentences/sentence/semantics')]
    if not sem_trees:
        sem_trees = [None] * len(ccg_trees)
    tokens = doc.xpath('./sentences/sentence/tokens')
    assert len(ccg_trees) == len(tokens)
    num_hypotheses = len(ccg_trees) - 1
    sentence_ids = ['Premise {0}: '.format(i + 1) for i in range(num_hypotheses)]
    sentence_ids.append('Conclusion: ')
    mathml_str = ""
    for i in range(len(ccg_trees)):
        sentence_surface = ' '.join(tokens[i].xpath('token/@surf'))
        mathml_str += (
            "<p>" + html.escape(sentence_ids[i] + sentence_surface) + "</p>\n"
            + "<math xmlns='http://www.w3.org/1998/Math/MathML'>"
            + convert_node_to_mathml(ccg_trees[i], sem_trees[i], tokens[i])
            + "</math>"
        )

    verbatim_text = ""
    if verbatim_strings:
        verbatim_text = "<p>Script piped to coq</p>"
        for vb_str in verbatim_strings:
            verbatim_text += "<pre>\n" + html.escape(vb_str) + "\n</pre>\n"

    return wrap_mathml_in_html(mathml_str + verbatim_text)
