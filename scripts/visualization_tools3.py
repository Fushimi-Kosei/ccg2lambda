#!/usr/bin/python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import html
import importlib.util
import math
import os
import re
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

from lxml import etree

# ------------------------------------------------------------
# Public flags kept for backward compatibility with callers.
# The current HTML output intentionally omits tree rendering and
# shows only the STL / score summaries.
# ------------------------------------------------------------

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
# Module loading
# ============================================================


def _candidate_module_paths(stem: str) -> List[Path]:
    here = Path(__file__).resolve().parent
    candidates = [
        here / f"{stem}.py",
        here.parent / f"{stem}.py",
    ]
    unique: List[Path] = []
    seen = set()
    for path in candidates:
        resolved = str(path.resolve())
        if resolved not in seen:
            unique.append(path)
            seen.add(resolved)
    return unique



def _module_file_path(stem: str) -> Path:
    for path in _candidate_module_paths(stem):
        if path.exists():
            return path
    searched = ', '.join(str(p) for p in _candidate_module_paths(stem))
    raise FileNotFoundError(f"Required module file not found for {stem!r}. Searched: {searched}")



def _load_function_from_module(module_stem: str, function_name: str):
    module_path = _module_file_path(module_stem)
    module_name = f"_visualization_pipeline_{module_stem}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec for {module_path}")

    module = importlib.util.module_from_spec(spec)

    # Important: dataclasses inside the pipeline modules require the module
    # to be registered in sys.modules before exec_module().
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


# ============================================================
# XML / sentence helpers
# ============================================================


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



def _sentence_elements(root_or_tree) -> List[etree._Element]:
    tree = _get_element_tree(root_or_tree)
    return tree.xpath("//*[local-name()='sentence']")



def _sentence_surface(sentence_elem: etree._Element) -> str:
    tokens = sentence_elem.xpath(
        "./*[local-name()='tokens']/*[local-name()='token'][not(@surf='*')]/@surf | "
        "./*[local-name()='tokens']/*[local-name()='token'][@surf='*']/@base"
    )
    return ' '.join(token for token in tokens if token)



def _collect_sentence_metadata(root_or_tree) -> List[Dict[str, Any]]:
    metadata: List[Dict[str, Any]] = []
    for sentence_index, sentence in enumerate(_sentence_elements(root_or_tree)):
        metadata.append(
            {
                'sentence_index': sentence_index,
                'sentence_id': sentence.get('id'),
                'surface': _sentence_surface(sentence),
            }
        )
    return metadata



def _sentence_key_from_item(item: Dict[str, Any]) -> Tuple[str, Any]:
    if item.get('sentence_index') is not None:
        return ('sentence_index', item.get('sentence_index'))
    if item.get('sentence_id'):
        return ('sentence_id', item.get('sentence_id'))
    return ('fallback', None)



def _ordered_sentence_keys(
    sentence_meta: Sequence[Dict[str, Any]],
    canonicalized: Dict[str, Any],
) -> List[Tuple[str, Any]]:
    ordered: List[Tuple[str, Any]] = []
    seen = set()

    for meta in sentence_meta:
        key = ('sentence_index', meta['sentence_index'])
        ordered.append(key)
        seen.add(key)

    for bucket_name in ('items', 'rejected_items'):
        for item in canonicalized.get(bucket_name, []) or []:
            if not isinstance(item, dict):
                continue
            key = _sentence_key_from_item(item)
            if key not in seen:
                ordered.append(key)
                seen.add(key)
    return ordered



def _sentence_title(meta: Optional[Dict[str, Any]], fallback_position: int) -> str:
    if meta is None:
        return f"Sentence {fallback_position + 1}"
    title = f"Sentence {meta.get('sentence_index', fallback_position) + 1}"
    if meta.get('sentence_id'):
        title += f" ({meta['sentence_id']})"
    return title


# ============================================================
# STL grouping / normalization
# ============================================================


def _append_unique_strings(target: List[str], values: Iterable[Any]) -> None:
    seen = set(target)
    for value in values:
        if isinstance(value, str) and value not in seen:
            target.append(value)
            seen.add(value)



def _renormalize_weights(weights: Sequence[float]) -> List[float]:
    if not weights:
        return []
    if len(weights) == 1:
        return [1.0]

    total = math.fsum(float(w) for w in weights)
    if not math.isfinite(total) or total <= 0.0:
        uniform = 1.0 / len(weights)
        result = [uniform] * len(weights)
        result[-1] = 1.0 - math.fsum(result[:-1])
        return result

    normalized = [float(w) / total for w in weights]
    running = math.fsum(normalized[:-1])
    last = 1.0 - running
    if last < 0.0 and abs(last) < 1e-15:
        last = 0.0
    normalized[-1] = last
    return normalized



def _aggregate_same_stl(converted: Dict[str, Any]) -> List[Dict[str, Any]]:
    grouped: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

    for item in converted.get('items', []) or []:
        if not isinstance(item, dict):
            continue
        if item.get('conversion_error'):
            continue
        stl = item.get('stl')
        if not isinstance(stl, str) or not stl.strip():
            continue

        if stl not in grouped:
            grouped[stl] = {
                'stl': stl,
                'raw_score_sum': 0.0,
                'display_score': 0.0,
                'canonical_semantics_list': [],
                'aggregate_indices': [],
                'member_global_indices': [],
                'member_sentence_indices': [],
                'occurrence_count': 0,
            }

        group = grouped[stl]
        try:
            group['raw_score_sum'] += float(item.get('score', 0.0))
        except Exception:
            pass

        canonical = item.get('canonical_semantics')
        if isinstance(canonical, str):
            _append_unique_strings(group['canonical_semantics_list'], [canonical])

        aggregate_index = item.get('aggregate_index')
        if isinstance(aggregate_index, int) and aggregate_index not in group['aggregate_indices']:
            group['aggregate_indices'].append(aggregate_index)

        for key in ('member_global_indices', 'member_sentence_indices'):
            values = item.get(key, [])
            if isinstance(values, list):
                current = set(group[key])
                for value in values:
                    if value not in current:
                        group[key].append(value)
                        current.add(value)

        group['occurrence_count'] += 1

    groups = list(grouped.values())
    display_scores = _renormalize_weights([group['raw_score_sum'] for group in groups])
    for index, (group, display_score) in enumerate(zip(groups, display_scores), start=1):
        group['display_score'] = display_score
        group['stl_group_index'] = index
    return groups


# ============================================================
# Pipeline execution
# ============================================================


def _run_sentence_pipeline(
    functions: Dict[str, Any],
    xml_path: str,
    kept_items: List[Dict[str, Any]],
    rejected_items: List[Dict[str, Any]],
    source_summary: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    canonical_subset: Dict[str, Any] = {
        'source_xml': xml_path,
        'allowed_functions': None,
        'summary': source_summary or {},
        'items': kept_items,
        'rejected_items': rejected_items,
    }

    aggregated = functions['aggregate_same_semantics'](canonical_subset)
    converted = functions['convert_items'](aggregated)
    stl_groups = _aggregate_same_stl(converted)

    return {
        'canonicalized': canonical_subset,
        'aggregated': aggregated,
        'converted': converted,
        'stl_groups': stl_groups,
    }



def _run_stl_pipeline(root_or_tree) -> Dict[str, Any]:
    functions = _load_pipeline_functions()
    xml_path, temporary_path = _resolve_xml_path(root_or_tree)

    try:
        canonicalized = functions['canonicalize_xml'](xml_path)
        sentence_meta = _collect_sentence_metadata(root_or_tree)
        ordered_keys = _ordered_sentence_keys(sentence_meta, canonicalized)

        sentence_meta_by_index = {
            meta['sentence_index']: meta for meta in sentence_meta if meta.get('sentence_index') is not None
        }

        sentences: List[Dict[str, Any]] = []
        for fallback_position, key in enumerate(ordered_keys):
            key_name, key_value = key
            kept_items = [
                item for item in canonicalized.get('items', []) or []
                if isinstance(item, dict) and _sentence_key_from_item(item) == key
            ]
            rejected_items = [
                item for item in canonicalized.get('rejected_items', []) or []
                if isinstance(item, dict) and _sentence_key_from_item(item) == key
            ]

            meta = None
            if key_name == 'sentence_index' and key_value in sentence_meta_by_index:
                meta = sentence_meta_by_index[key_value]
            elif isinstance(key_value, str):
                for candidate in sentence_meta:
                    if candidate.get('sentence_id') == key_value:
                        meta = candidate
                        break

            sentence_pipeline = _run_sentence_pipeline(
                functions=functions,
                xml_path=xml_path,
                kept_items=kept_items,
                rejected_items=rejected_items,
                source_summary=canonicalized.get('summary'),
            )

            sentence_pipeline['sentence_key'] = key
            sentence_pipeline['sentence_meta'] = meta
            sentence_pipeline['title'] = _sentence_title(meta, fallback_position)
            sentences.append(sentence_pipeline)

        return {
            'canonicalized': canonicalized,
            'sentences': sentences,
        }
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


# ============================================================
# HTML helpers
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



def _summary_card(label: str, value: Any) -> str:
    return (
        "<div class='summary-card'>"
        "<div class='summary-label'>{0}</div>"
        "<div class='summary-value'>{1}</div>"
        "</div>"
    ).format(html.escape(label), _format_score(value))



def _render_sentence_section(sentence_context: Dict[str, Any]) -> str:
    meta = sentence_context.get('sentence_meta') or {}
    surface = meta.get('surface') or ''
    canonical_items = sentence_context['canonicalized'].get('items', []) or []
    canonical_rejected = sentence_context['canonicalized'].get('rejected_items', []) or []
    aggregated_items = sentence_context['aggregated'].get('items', []) or []
    converted_items = sentence_context['converted'].get('items', []) or []
    successful_converted = [
        item for item in converted_items
        if isinstance(item, dict) and not item.get('conversion_error') and isinstance(item.get('stl'), str) and item.get('stl').strip()
    ]
    stl_groups = sentence_context.get('stl_groups', []) or []
    stl_display_total = math.fsum(float(group.get('display_score', 0.0)) for group in stl_groups)

    cards = ''.join([
        _summary_card('Canonical kept', len(canonical_items)),
        _summary_card('Canonical rejected', len(canonical_rejected)),
        _summary_card('Unique semantics', len(aggregated_items)),
        _summary_card('Successful conversions', len(successful_converted)),
        _summary_card('Aggregated STL', len(stl_groups)),
        _summary_card('Displayed score total', stl_display_total),
    ])

    if not stl_groups:
        table_html = "<p class='pipeline-message'>No successful STL conversion was produced for this sentence.</p>"
    else:
        rows = []
        for group in stl_groups:
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
                    html.escape(str(group.get('stl_group_index', ''))),
                    _format_score(group.get('display_score')),
                    _format_stl_for_html(group.get('stl')),
                    html.escape(str(len(group.get('canonical_semantics_list', [])))),
                    canonical_semantics_html,
                )
            )
        table_html = (
            "<div class='table-wrap'>"
            "<table class='stl-table'>"
            "<thead><tr>"
            "<th>#</th>"
            "<th>Normalized score</th>"
            "<th>STL</th>"
            "<th>Semantics</th>"
            "<th>Canonical semantics</th>"
            "</tr></thead>"
            "<tbody>{0}</tbody>"
            "</table>"
            "</div>"
        ).format(''.join(rows))

    surface_html = (
        "<p class='sentence-surface'><span class='surface-label'>Text:</span> {0}</p>".format(html.escape(surface))
        if surface else ''
    )

    return (
        "<section class='pipeline-summary sentence-summary'>"
        "<h1>{0}</h1>"
        "{1}"
        "<div class='summary-grid'>{2}</div>"
        "{3}"
        "</section>"
    ).format(
        html.escape(sentence_context.get('title', 'Sentence')),
        surface_html,
        cards,
        table_html,
    )



def _render_pipeline_summary(pipeline_context: Optional[Dict[str, Any]], pipeline_error: Optional[BaseException]) -> str:
    if pipeline_error is not None:
        return (
            "<section class='pipeline-summary pipeline-summary-error'>"
            "<h1>STL pipeline</h1>"
            "<p class='pipeline-message'>The STL pipeline failed.</p>"
            "<pre class='pipeline-error-text'>{0}</pre>"
            "</section>"
        ).format(html.escape(str(pipeline_error)))

    if pipeline_context is None:
        return ''

    sentences = pipeline_context.get('sentences', []) or []
    if not sentences:
        return (
            "<section class='pipeline-summary'>"
            "<h1>STL pipeline</h1>"
            "<p class='pipeline-message'>No sentence was found in the input XML.</p>"
            "</section>"
        )

    total_groups = sum(len(sentence.get('stl_groups', []) or []) for sentence in sentences)
    overall_cards = ''.join([
        _summary_card('Sentences', len(sentences)),
        _summary_card('Aggregated STL groups', total_groups),
    ])

    sentence_sections = ''.join(_render_sentence_section(sentence) for sentence in sentences)
    return (
        "<section class='pipeline-summary overall-summary'>"
        "<h1>STL summary</h1>"
        "<div class='summary-grid'>{0}</div>"
        "</section>"
        "{1}"
    ).format(overall_cards, sentence_sections)


# ============================================================
# HTML shell / public entry point
# ============================================================


def wrap_mathml_in_html(body_html: str) -> str:
    head = """<!DOCTYPE html>
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
      margin-bottom: 1.5rem;
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
    .sentence-surface {
      margin: 0 0 0.85rem 0;
      color: #333;
    }
    .surface-label {
      font-weight: 600;
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
    .inline-code,
    .stl-expression {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    }
    .inline-code {
      white-space: pre-wrap;
      word-break: break-word;
    }
    .stl-expression {
      font-size: 1.04em;
    }
  </style>
</head>
<body>
"""
    tail = """
</body>
</html>
"""
    return head + body_html + tail



def convert_root_to_mathml(root, use_gold_trees: bool = False):
    """
    visualize.py can keep calling this function unchanged.

    The function runs the STL pipeline in the required order
      Canonicalization.py -> Aggregation.py -> STL_conversion.py
    with direct in-memory hand-off between the three steps.

    Processing is done sentence by sentence, while the final output is still a
    single HTML document.
    """
    del use_gold_trees  # unused, kept for compatibility

    pipeline_context = None
    pipeline_error = None
    try:
        pipeline_context = _run_stl_pipeline(root)
    except Exception as exc:
        pipeline_error = exc

    return wrap_mathml_in_html(
        _render_pipeline_summary(pipeline_context, pipeline_error)
    )


# Backward-compatible helper name kept for possible imports.
def convert_doc_to_mathml(doc, use_gold_trees: bool = False, pipeline_context=None, state=None):
    del doc, use_gold_trees, pipeline_context, state
    return ''


# Backward-compatible helper name kept for possible imports.
def convert_doc_to_mathml_(doc, verbatim_strings=None, use_gold_trees=False):
    del doc, verbatim_strings, use_gold_trees
    return wrap_mathml_in_html('')
