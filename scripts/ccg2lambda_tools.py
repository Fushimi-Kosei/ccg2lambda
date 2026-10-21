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

import copy
import re
import simplejson

from lxml import etree


from logic_parser import lexpr
from normalization import normalize_token
import semantic_index

# ===== ADD: lift lambda arguments out of function arguments =====
import functools
from nltk.sem.logic import ApplicationExpression
from nltk.sem.logic import NegatedExpression
from nltk.sem.logic import BinaryExpression
from nltk.sem.logic import VariableBinderExpression
from nltk.sem.logic import ConstantExpression
from nltk.sem.logic import AbstractVariableExpression
from nltk.sem.logic import Variable
from nltk.sem.logic import LambdaExpression
from nltk.sem.logic import VariableExpression

def _free_var_names(expr):
    try:
        return {str(v) for v in expr.free()}
    except Exception:
        return set()

def _fresh_name(base, avoid):
    if base not in avoid:
        return base
    i = 1
    while f"{base}{i}" in avoid:
        i += 1
    return f"{base}{i}"

def _alpha_rename_lambda(lam, avoid_names):
    """Avoid capturing: rename bound var if needed.

    Note:
      NLTK Expression.replace() requires an Expression as the replacement value,
      so we must use VariableExpression(new_v) (not the bare Variable).
    """
    v = lam.variable
    vname = str(v)
    if vname not in avoid_names:
        return lam
    new_name = _fresh_name(vname, avoid_names)
    new_v = Variable(new_name)
    new_body = lam.term.replace(v, VariableExpression(new_v))
    return LambdaExpression(new_v, new_body)

def _peel_lambdas(expr, avoid_names=None):
    """Peel leading lambda binders and return (vars, body).

    vars: [Variable, ...]  (outer-to-inner order)
    body: Expression       (non-LambdaExpression)

    avoid_names is used to alpha-rename binders to avoid capture when their scope
    is widened (e.g., when lifting lambdas over binary/unary operators).
    """
    avoid_names = set(avoid_names or [])
    vars_ = []
    body = expr
     #Avoid accidental shadowing inside a single lambda chain: \X.\X.P -> \X.\X1.P
    used_in_chain = set()
    while isinstance(body, LambdaExpression):
        lam = _alpha_rename_lambda(body, avoid_names | used_in_chain)
        vars_.append(lam.variable)
        used_in_chain.add(str(lam.variable))
        body = lam.term
    return vars_, body

def lift_lambda_args(expr):
    """Lift unapplied lambda arguments to the outermost position.

    Examples:
      \\x. F(x, \\y. G(y))        ->  \\x y. F(x, G(y))
      (\\X. G(X) & F)              ->  \\X. (G(X) & F)
      (\\X. G(X) & \\X. F(X))    ->  \\X. (G(X) & F(X))
    """
    # Lambda stays at outermost; recurse into body
    if isinstance(expr, LambdaExpression):
        return LambdaExpression(expr.variable, lift_lambda_args(expr.term))

    # Unary operator: negation (-)
    if isinstance(expr, NegatedExpression):
        term = lift_lambda_args(expr.term)

        # -(\\x.B) -> \\x.-B  (also supports multi-arg lambdas)
        if isinstance(term, LambdaExpression):
            lifted_vars, body = _peel_lambdas(term)
            out = type(expr)(body)
            for v in reversed(lifted_vars):
                out = LambdaExpression(v, out)
            return out

        return type(expr)(term)

    # Binary operators: &, |, ->, etc.
    if isinstance(expr, BinaryExpression):
        left = lift_lambda_args(expr.first)
        right = lift_lambda_args(expr.second)

        if isinstance(left, LambdaExpression) or isinstance(right, LambdaExpression):
            # Avoid capturing free vars from the opposite side when widening scope.
            avoid_left = _free_var_names(right)
            avoid_right = _free_var_names(left)

            left_vars, left_body = _peel_lambdas(left, avoid_left)
            right_vars, right_body = _peel_lambdas(right, avoid_right)

            bin_body = type(expr)(left_body, right_body)

            # Merge same-name binders (do not distinguish same unapplied argument names).
            merged_vars = []
            seen_names = set()
            for v in (left_vars + right_vars):
                name = str(v)
                if name not in seen_names:
                    merged_vars.append(v)
                    seen_names.add(name)

            out = bin_body
            for v in reversed(merged_vars):
                out = LambdaExpression(v, out)
            return out

        return type(expr)(left, right)

    # Function application: F(..., \x.B, ...) -> \x. F(..., B, ...)
    # Also: merge same-name unapplied arguments across *multiple* lambda arguments.
    #   H(\X.G(X), \X.F(X))  ->  \X. H(G(X), F(X))
    if isinstance(expr, ApplicationExpression):
        func, args = expr.uncurry()
        func = lift_lambda_args(func)
        args = [lift_lambda_args(a) for a in args]

        # names to avoid capture (free variables outside lifted binders)
        avoid = _free_var_names(func)
        for a in args:
            avoid |= _free_var_names(a)

        lifted_vars = []
        new_args = []

        # Map: original binder name -> canonical lifted Variable
        canon = {}
        used_canon_names = set()

        for a in args:
            if isinstance(a, LambdaExpression):
                # lift multi-arg lambdas too: \x.\y.B
                while isinstance(a, LambdaExpression):
                    orig_name = str(a.variable)

                    # Reuse the canonical binder if the same original name has appeared.
                    if orig_name in canon:
                        target_v = canon[orig_name]
                    else:
                        # Choose a canonical name that won't capture free vars and
                        # won't collide with other (different) binders.
                        cand = orig_name
                        avoid_all = set(avoid) | used_canon_names
                        if cand in avoid_all:
                            cand = _fresh_name(cand, avoid_all)
                        target_v = Variable(cand)
                        canon[orig_name] = target_v
                        used_canon_names.add(str(target_v))
                        lifted_vars.append(target_v)

                    # Alpha-convert this binder to target_v if needed.
                    if str(a.variable) != str(target_v):
                        a = LambdaExpression(
                            target_v,
                            a.term.replace(a.variable, VariableExpression(target_v))
                        )

                    # Drop the binder and continue peeling.
                    a = a.term

                new_args.append(a)
            else:
                new_args.append(a)

        rebuilt = functools.reduce(
            lambda f, a: ApplicationExpression(f, a),
            [func] + new_args
        )
        for v in reversed(lifted_vars):
            rebuilt = LambdaExpression(v, rebuilt)
        return rebuilt

    # Other expressions: leave as-is
    return expr
def postprocess_semantics(expr):
    try:
        return lift_lambda_args(expr).simplify()
    except Exception:
        # 変換に失敗してもパース全体が落ちないように元を返す
        return expr

# ===== END ADD =====


def build_ccg_tree(ccg_xml, root_id=None):
    """
    This function re-arranges the nodes of the XML CCG tree to have
    a tree structure. It will be useful to traverse the tree.
    """
    if ccg_xml == None or len(ccg_xml) == 0:
        return None
    if root_id == None:
        root_id = ccg_xml.get('root')
    root_span = copy.deepcopy(semantic_index.find_node_by_id(root_id, ccg_xml))
    if 'child' not in root_span.attrib:
        return root_span
    children_id = root_span.get('child').split()
    for child_id in children_id:
        child_node = build_ccg_tree(ccg_xml, child_id)
        if child_node != None:
            root_span.append(child_node)
    return root_span

def normalize_tokens(tokens):
    """
    In our format of XML trees, tokens have their own tree,
    which is separated from the syntactic structure. These
    tokens may need some processing for normalization, such
    as prefixing them with an underscore "_", or copying
    into their base form the surface form when the base form
    is absent (base="*"). For now, only the copy to base forms
    from surface forms is implemented:
    """
    for token in tokens:
        if token.get('base', None) == '*':
            token.set('base', token.get('surf', '*'))
        if 'base' in token.attrib and not token.get('base', '').startswith('_'):
            base = token.get('base', '')
            base_normalized = normalize_token(base)
            token.set('base', base_normalized)
        if 'surf' in token.attrib and not token.get('surf', '').startswith('_'):
            surf = token.get('surf', '')
            surf_normalized = normalize_token(surf)
            token.set('surf', surf_normalized)
    return tokens

def assign_semantics_to_ccg(ccg_xml, semantic_index, tree_index=1):
    """
    This is the key function. It builds first an XML tree structure with
    the CCG tree, and then assigns semantics (lambda expressions) to each node
    in post-order (first assigns semantics to children, and then to node).
    It returns a CCG lxml tree structure with a new 'sem' field that
    contains the semantics at each node.
    """
    # If the use of gold trees is requested, we get the gold tree index
    # from the XML attribute 'gold_tree'. Note that in xpath, lists are
    # one-indexed arrays.
    # from pudb import set_trace; set_trace()
    ccg_flat_trees = ccg_xml.xpath('./ccg[{0}]'.format(tree_index))
    if not ccg_flat_trees:
        raise ValueError(
            'No CCG tree found in:\n{0}'.format(
            etree.tostring(
                ccg_xml,
                encoding='utf-8',
                pretty_print=True).decode('utf-8')))
    ccg_flat_tree = copy.deepcopy(ccg_flat_trees[0])
    #   ccg_xml.xpath('./ccg[{0}]'.format(tree_index))[0])
    ccg_tree = build_ccg_tree(ccg_flat_tree)
    tokens = copy.deepcopy(ccg_xml.find('.//tokens'))
    tokens = normalize_tokens(tokens)
    assign_semantics(ccg_tree, semantic_index, tokens)
    return ccg_tree

def is_forward_operation(ccg_tree):
    rule = ccg_tree.get('rule')
    if 'gt' in rule or '>' in rule or (len(rule) > 0 and rule[0] == 'f'):
        return True
    return False

def get_combination_op(ccg_tree):
    """
    As of today, CCG trees as produce by transccg does not signal
    function combination. This code assumes that transccg would insert
    the character 'B' somewhere in the rule, to easy identification of operation.
    """
    rule = ccg_tree.get('rule')
    if 'B' in rule or (len(rule) > 1 and (rule[1] not in ['a', 'p'])):
        return 'function_combination'
    return 'function_application'

def get_num_args(ccg_tree):
    rule = ccg_tree.get('rule')
    num_args = 1
    if '2' in rule:
        num_args = 2
    elif '3' in rule:
        num_args = 3
    return num_args

def type_raise(function, order = 1):
    """
    Produce a higher order function based on "function". The argument "order"
    indicates the number of desired arguments of the new function.
    """
    assert order >= 0, 'The order of the type-raising should be >= 0'
    if isinstance(function, ConstantExpression):
        type_raiser = lexpr(r'\P X.P(X)')
        type_raised_function = type_raiser(function).simplify()
    else:
        if order == 1:
            type_raiser = lexpr(r'\P0 P1 X0.P0(P1(X0))')
        elif order == 2:
            type_raiser = lexpr(r'\P0 P1 X0 X1.P0(P1(X0, X1))')
        elif order == 3:
            type_raiser = lexpr(r'\P0 P1 X0 X1 X2.P0(P1(X0, X1, X2))')
        else:
            assert False, 'Type-raising at order > 3 is not supported'
        type_raised_function = type_raiser(function).simplify()
    return type_raised_function

def combine_children_exprs(ccg_tree, tokens, semantic_index):
    """
    Perform forward/backward function application/combination.
    """
    assert len(ccg_tree) >= 2, \
      'There should be at least two children to combine expressions: {0}'\
      .format(ccg_tree)
    # Assign coq types.
    coq_types_left  = ccg_tree[0].attrib.get('coq_type', "")
    coq_types_right = ccg_tree[1].attrib.get('coq_type', "")
    if coq_types_left and coq_types_right:
        coq_types = coq_types_left + ' ||| ' + coq_types_right
    elif coq_types_left:
        coq_types = coq_types_left 
    else:
        coq_types = coq_types_right
    ccg_tree.set('coq_type', coq_types)
    semantics = semantic_index.get_semantic_representation(ccg_tree, tokens)
    if semantics:
        semantics = postprocess_semantics(semantics)
        ccg_tree.set('sem', str(semantics))
        return None
    # Back-off mechanism in case no semantic templates are available:
    if is_forward_operation(ccg_tree):
        function_index, argument_index = 0, 1
    else:
        function_index, argument_index = 1, 0
    function = lexpr(ccg_tree[function_index].attrib['sem'])
    argument = lexpr(ccg_tree[argument_index].attrib['sem'])
    combination_operation = get_combination_op(ccg_tree)
    if combination_operation == 'function_application':
        evaluation = function(argument).simplify()
    elif combination_operation == 'function_combination':
        num_arguments = get_num_args(ccg_tree)
        type_raised_function = type_raise(function, num_arguments)
        evaluation = type_raised_function(argument).simplify()
    else:
        assert False, 'This node should be a function application or combination'\
                      .format(etree.tostring(ccg_tree, pretty_print=True))
    evaluation = postprocess_semantics(evaluation)
    ccg_tree.set('sem', str(evaluation))
    return None

def assign_semantics(ccg_tree, semantic_index, tokens):
    """
    Visit recursively the CCG tree in depth-first order, assigning lambda expressions
    (semantics) to each node.
    """
    category = ccg_tree.attrib['category']
    if len(ccg_tree) == 0:
        semantics = semantic_index.get_semantic_representation(ccg_tree, tokens)
        semantics = postprocess_semantics(semantics)
        ccg_tree.set('sem', str(semantics))
        return
    if len(ccg_tree) == 1:
        assign_semantics(ccg_tree[0], semantic_index, tokens)
        semantics = semantic_index.get_semantic_representation(ccg_tree, tokens)
        semantics = postprocess_semantics(semantics)
        ccg_tree.set('sem', str(semantics))
        return
    for child in ccg_tree:
        assign_semantics(child, semantic_index, tokens)
    combine_children_exprs(ccg_tree, tokens, semantic_index)
    return
