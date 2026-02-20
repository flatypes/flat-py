import ast
from copy import deepcopy
from enum import Enum
from typing import Callable, Optional, Tuple, Any

from flat.py.isla_extensions import EBNF_DIRECT_CHILD, EBNF_KTH_CHILD
from flat.selectors import *


def negate(cond: ast.expr) -> ast.expr:
    """Logical negation of a condition."""
    return ast.UnaryOp(ast.Not(), cond)


def cnf(cond: ast.expr) -> list[ast.expr]:
    """Convert a condition into conjunctive normal form. Return the list of conjuncts."""
    match cond:
        case ast.BoolOp(ast.And(), operands):  # p and q
            return [c for e in operands for c in cnf(e)]
        case ast.UnaryOp(ast.Not(), ast.BoolOp(ast.Or(), operands)):  # not (p or q) = (not p) and (not q)
            return [c for e in operands for c in cnf(negate(e))]
        case atomic:
            return [atomic]


class FreeVarCollector(ast.NodeVisitor):
    def __call__(self, tree: ast.expr) -> frozenset[str]:
        """Collect the set of free variable names in an expression."""
        self._free: set[str] = set()
        self._bound: list[list[str]] = []
        self.visit(tree)
        return frozenset(self._free)

    def visit_Name(self, node: ast.Name):
        if all(node.id not in bound for bound in self._bound):
            self._free.add(node.id)

    def visit_Lambda(self, node: ast.Lambda):
        bound = [arg.arg for arg in node.args.args]
        self._bound.append(bound)
        self.visit(node.body)
        self._bound.pop()


free_vars: Callable[[ast.expr], frozenset[str]] = FreeVarCollector()


class Substitution(ast.NodeTransformer):
    def __call__(self, tree: ast.expr, subst_map: dict[str, ast.expr]) -> ast.expr:
        """Substitute free vars in an expression."""
        self._subst_map = subst_map
        self._bound: list[list[str]] = []
        node = deepcopy(tree)
        self.visit(node)
        return node

    def visit_Name(self, node: ast.Name) -> ast.expr:
        if node.id in self._subst_map and all(node.id not in bound for bound in self._bound):
            return self._subst_map[node.id]
        return node

    def visit_Lambda(self, node: ast.Lambda) -> ast.expr:
        bound = [arg.arg for arg in node.args.args]
        self._bound.append(bound)
        body = self.visit(node.body)
        self._bound.pop()
        node.body = body
        return node


subst: Callable[[ast.expr, dict[str, ast.expr]], ast.expr] = Substitution()


class ISLaType(Enum):
    Formula = 0
    Int = 1
    String = 2


class ISLaConvertor:
    def __init__(self, env: dict[str, Any]) -> None:
        self._env: dict[str, Any] = env
        self.this: str = '_'
        self.ty_ctx: dict[str, ISLaType] = {}

    def __call__(self, expr: ast.expr, this: str) -> Optional[str]:
        """Convert an expression to a well-typed ISLa formula."""
        self.this = this
        self.ty_ctx = {}
        result = self.to_isla(expr)
        if result:
            return result[0]
        return None

    def to_isla(self, expr: ast.expr) -> Optional[Tuple[str, ISLaType]]:
        match expr:
            # constants
            case ast.Constant(True):
                return 'true', ISLaType.Formula
            case ast.Constant(False):
                return 'false', ISLaType.Formula
            case ast.Constant(int() as n):
                return str(n), ISLaType.Int
            case ast.Constant(str()):
                return '"' + ast.unparse(expr)[1:-1] + '"', ISLaType.String  # NOTE: isla uses double quote

            # bound variables
            case ast.Name(x) if x in self.ty_ctx:
                return x, self.ty_ctx[x]

            # boolean expressions
            case ast.BoolOp(op, operands):
                match op:
                    case ast.And():
                        connective = ' and '
                    case ast.Or():
                        connective = ' or '
                    case _:
                        assert False
                results = [self.to_isla(e) for e in operands]
                if all(isinstance(result, tuple) and result[1] == ISLaType.Formula for result in results):
                    formulae = [f for f, _ in results]  # type: ignore
                    return '(' + connective.join(formulae) + ')', ISLaType.Formula
            case ast.UnaryOp(ast.Not(), operand):
                match self.to_isla(operand):
                    case (formula, ISLaType.Formula):
                        return f'(not {formula})', ISLaType.Formula

            # arithmetic expressions, string concat (+)
            case ast.BinOp(left, op, right):
                match op:
                    case ast.Add():
                        smt_op = '+'
                    case ast.Sub():
                        smt_op = '-'
                    case ast.Mult():
                        smt_op = '*'
                    case ast.Div():
                        smt_op = '/'
                    case ast.Mod():
                        smt_op = '%'
                    case _:  # unsupported
                        return None
                match self.to_isla(left), self.to_isla(right):
                    case (lhs, ISLaType.Int), (rhs, ISLaType.Int):
                        return f'({smt_op} {lhs} {rhs})', ISLaType.Int
                    case ((lhs, ISLaType.String), (rhs, ISLaType.String)) if smt_op == '+':
                        return f'(str.++ {lhs} {rhs})', ISLaType.String
            case ast.UnaryOp(op, operand):
                match op, self.to_isla(operand):
                    case ast.UAdd(), (formula, ISLaType.Int):
                        return formula, ISLaType.Int  # type: ignore
                    case ast.USub(), (formula, ISLaType.Int):
                        return f'(- 0 {formula})', ISLaType.Int

            # comparison expressions, string comparison (<=), string contains (in)
            case ast.Compare(left, [op], [right]):
                match op:
                    case ast.Eq():
                        smt_op = '='
                    case ast.Lt():
                        smt_op = '<'
                    case ast.LtE():
                        smt_op = '<='
                    case ast.Gt():
                        smt_op = '>'
                    case ast.GtE():
                        smt_op = '>='
                    case ast.In():
                        smt_op = 'in'
                    case _:  # unsupported
                        return None
                match self.to_isla(left), self.to_isla(right):
                    case (lhs, ISLaType.Int), (rhs, ISLaType.Int) if smt_op != 'in':
                        return f'({smt_op} {lhs} {rhs})', ISLaType.Formula
                    case (lhs, ISLaType.String), (rhs, ISLaType.String):
                        match smt_op:
                            case '<':
                                return f'((<= {lhs} {rhs}) and not (= {lhs} {rhs}))', ISLaType.Formula
                            case '>':
                                return f'(not (<= {lhs} {rhs}))', ISLaType.Formula
                            case '>=':
                                return f'(not (<= {lhs} {rhs}) or (= {lhs} {rhs}))', ISLaType.Formula
                            case 'in':
                                return f'(str.contains {rhs} {lhs})', ISLaType.Formula
                            case _:
                                return f'({smt_op} {lhs} {rhs})', ISLaType.Formula

            # string char at
            case ast.Subscript(receiver, ast.Constant(int() as index)):
                match self.to_isla(receiver):
                    case string, ISLaType.String:
                        return f'(str.at {string} {index})', ISLaType.String
            # substring
            case ast.Subscript(receiver, ast.Slice(lower, upper, step=None)):
                match self.to_isla(receiver):
                    case string, ISLaType.String:
                        match lower:
                            case ast.Constant(int() as index):
                                offset = index
                            case None:
                                offset = 0
                            case _:  # unsupported
                                return None
                        match upper:
                            case ast.Constant(int() as index):
                                length = f'(- {index} {offset})'
                            case None:
                                length = f'(str.len {string})'
                            case _:  # unsupported
                                return None
                        return f'(str.substr {string} {offset} {length})', ISLaType.String

            # string and builtin functions
            case ast.Call(ast.Name(fun, ctx=ast.Load()), args, keywords=[]):
                match fun, args:
                    case 'len', [receiver]:
                        match self.to_isla(receiver):
                            case string, ISLaType.String:
                                return f'(str.len {string})', ISLaType.Int
                    case 'ord', [receiver]:
                        match self.to_isla(receiver):
                            case string, ISLaType.String:
                                return f'(str.to_code {string})', ISLaType.Int
                    case 'chr', [receiver]:
                        match self.to_isla(receiver):
                            case integer, ISLaType.Int:
                                return f'(str.from_code {integer})', ISLaType.String
                    case 'int', [receiver]:
                        match self.to_isla(receiver):
                            case string, ISLaType.String:
                                # SMTLib: string cannot contain '-'.
                                # Python: allow '-'.
                                return f'(str.to.int {string})', ISLaType.Int
                    case 'str', [receiver]:
                        match self.to_isla(receiver):
                            case integer, ISLaType.Int:
                                # SMTLib: integer is non-negative.
                                # Python: allow negative value.
                                return f'(str.from_int {integer})', ISLaType.String
                    case 'select', [_, ast.Constant(str() as path), ast.Name(w)] if w == self.this:
                        return xpath_to_isla_expr(xpath_parser.parse(path), 'start'), ISLaType.String
                    case 'selected_all' | 'selected_any', \
                         [ast.Lambda(ast.arguments([], [ast.arg(x)], None, [], [], None, []), cond),
                          xpath, ast.Name(w)] if w == self.this:
                        path = eval(ast.unparse(xpath), {}, self._env)
                        assert isinstance(path, XPath)
                        self.ty_ctx[x] = ISLaType.String
                        result = self.to_isla(cond)
                        del self.ty_ctx[x]
                        if result and result[1] == ISLaType.Formula:
                            formula = xpath_to_isla_formula(path, fun == 'selected_all', x, result[0])
                            return formula, ISLaType.Formula

            case ast.Call(ast.Attribute(receiver, fun, ctx=ast.Load()), args, keywords=[]):
                match fun, args:
                    case 'startswith', [s]:
                        match self.to_isla(receiver), self.to_isla(s):
                            case (string, ISLaType.String), (prefix, ISLaType.String):
                                return f'(str.prefixof {prefix} {string})', ISLaType.Formula
                    case 'endswith', [s]:
                        match self.to_isla(receiver), self.to_isla(s):
                            case (string, ISLaType.String), (suffix, ISLaType.String):
                                return f'(str.suffixof {suffix} {string})', ISLaType.Formula
                    case 'find' | 'index', _:  # `index` raises error if the pattern is not found
                        if len(args) not in [1, 2]:  # unsupported
                            return None
                        match self.to_isla(receiver), self.to_isla(args[0]):
                            case (string, ISLaType.String), (pattern, ISLaType.String):
                                if len(args) == 2:
                                    match self.to_isla(args[1]):
                                        case start, ISLaType.Int:
                                            pass  # start assigned
                                        case _:
                                            return None
                                else:
                                    start = '0'
                                return f'(str.indexof {string} {pattern} {start})', ISLaType.Int
                    case 'replace', [s1, s2, ast.Constant(1)]:  # count = 1: replace the first occurrence only
                        match self.to_isla(receiver), self.to_isla(s1), self.to_isla(s2):
                            case (string, ISLaType.String), (old, ISLaType.String), (new, ISLaType.String), ():
                                return f'(str.replace {string} {old} {new})', ISLaType.String
                    case 'replace', [s1, s2]:  # no count: replace all occurrences
                        match self.to_isla(receiver), self.to_isla(s1), self.to_isla(s2):
                            case (string, ISLaType.String), (old, ISLaType.String), (new, ISLaType.String), ():
                                # SMTLib: if `old` is empty, the result is the original `string`.
                                # Python: the result is to insert `new` everywhere like a delimiter.
                                return f'(str.replace_all {string} {old} {new})', ISLaType.String
                    case 'isdigit', []:
                        match self.to_isla(receiver):
                            case string, ISLaType.String:
                                # SMTLib: require the string to be a singleton.
                                # Python: test all characters in the string.
                                return f'(str.is_digit {string})', ISLaType.Formula

        # otherwise
        return None


def xpath_to_isla_formula(path: XPath, is_universal: bool, atomic_binder: str, atomic_cond: str) -> str:
    formula = atomic_cond
    quantifier = 'forall' if is_universal else 'exists'
    connective = 'implies' if is_universal else 'and'
    binders = [p.of for p in path.selectors[:-1]] + [atomic_binder]
    for selector, x, scope in zip(reversed(path.selectors), reversed(binders), reversed(['start'] + binders[:-1])):
        match selector:
            case XPathSelectDirectAt(symbol, pos):
                formula = (f'(exists <{symbol}> {x} in {scope}: '
                           f'({EBNF_KTH_CHILD}({x}, {scope}, "{pos}") and {formula}))')
            case XPathSelectAllDirect(symbol):
                formula = (f'({quantifier} <{symbol}> {x} in {scope}: '
                           f'({EBNF_DIRECT_CHILD.name}({x}, {scope}) {connective} {formula}))')
            case XPathSelectAllIndirect(symbol):
                formula = f'({quantifier} <{symbol}> {x} in {scope}: {formula})'
    return formula


def xpath_to_isla_expr(path: XPath, start: str) -> str:
    expr = start
    for selector in path.selectors:
        match selector:
            case XPathSelectDirectAt(symbol, pos):
                expr += f'.<{symbol}>[{pos}]'
            case XPathSelectAllDirect(symbol):
                expr += f'.<{symbol}>[1]'  # by default, pos = 1
            case XPathSelectAllIndirect(symbol):
                expr += f'..<{symbol}>'
    return expr
