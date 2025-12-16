import ast
import os.path
from typing import FrozenSet, Sequence

from flat.backend.lang import NT, project
from flat.py.ast_helpers import *
from flat.py.compile_time import *
from flat.py.grammar import *
from flat.py.parser import parse, LANG_SYNTAX
from flat.py.shared import Range, get_range, get_code

__all__ = ['analyze_lang', 'analyze']


def analyze_lang(grammar: str, ctx: Context,
                 *, syntax: str = 'ebnf', name: ast.expr | None = None,
                 start: tuple[int, int] = (0, 0)) -> LangType | AnyType:
    """Analyze a grammar definition. Return a language type if parsing succeed; otherwise, return Any type."""
    assert syntax in LANG_SYNTAX, f"unknown language syntax: {syntax!r}"

    result = parse(grammar, syntax=syntax, file_path=ctx.file_path, start=start)
    if isinstance(result, InvalidSyntax):
        ctx.issue(result)
        return AnyType()

    rules = result
    nonterminals: list[str] = []
    for rule in rules:
        if rule.name.name not in nonterminals:
            nonterminals.append(rule.name.name)
        else:
            ctx.issue(RedefinedRule(ctx.file_path, rule.name.pos))

    desugar = Desugar(ctx, frozenset(nonterminals))
    for rule in rules:
        desugar.visit_rule(rule.name.name, rule.body)

    return LangType(desugar.rules, name)


class Desugar(ExprVisitor):
    def __init__(self, ctx: Context, nonterminals: FrozenSet[str]) -> None:
        super().__init__()
        self.ctx = ctx
        self.nonterminals = nonterminals
        self.rules: dict[str, Sequence[Sequence[str | NT]]] = {}
        self._fresh_count = 0

    def _fresh(self) -> str:
        self._fresh_count += 1
        return f'@{self._fresh_count}'

    def visit_rule(self, name: str, body: Expr) -> None:
        match body:
            case Union(es):
                self.rules[name] = [self.visit(e) for e in es]
            case _:
                self.rules[name] = [self.visit(body)]

    def visit_Lit(self, node: Lit) -> Sequence[str | NT]:
        return [node.value]

    def visit_CharClass(self, node: CharClass) -> Sequence[str | NT]:
        assert node.mode == 'inclusive'
        chars: list[str] = []
        for item in node.items:
            match item:
                case str() as c:
                    chars.append(c)
                case CharRange(c1, c2):
                    if ord(c1) <= ord(c2):
                        for n in range(ord(c1), ord(c2) + 1):
                            chars.append(chr(n))
                    else:
                        self.ctx.issue(EmptyRange(self.ctx.file_path, item.pos))

        if len(chars) == 1:
            return [chars.pop()]

        fresh_id = self._fresh()
        self.rules[fresh_id] = [[c] for c in chars]
        return [NT(fresh_id)]

    def visit_Ref(self, node: Ref) -> Sequence[str | NT]:
        if node.name in self.nonterminals:
            return [NT(node.name)]

        match self.ctx.lookup(node.name):
            case TypeDef(LangType(lang)):
                if 'start' in lang:
                    lang = project(lang, 'start')
                    for name in lang:
                        self.rules[f'{node.name}.{name}'] = lang[name]
                else:
                    self.ctx.issue(NoStartRule(self.ctx.file_path, node.pos))
                return [NT(f'{node.name}.start')]
            case _:
                self.ctx.issue(UndefinedRule(self.ctx.file_path, node.pos))
                return [NT(node.name)]

    def visit_Concat(self, node: Concat) -> Sequence[str | NT]:
        return [s for element in node.elements for s in self.visit(element)]

    def visit_Union(self, node: Union) -> Sequence[str | NT]:
        fresh_id = self._fresh()
        self.visit_rule(fresh_id, node)
        return [NT(fresh_id)]

    def visit_Star(self, node: Star) -> Sequence[str | NT]:
        fresh_id = self._fresh()
        seq = self.visit(node.element)
        self.rules[fresh_id] = [[], seq + [NT(fresh_id)]]  # a* = ε | a a*
        return [NT(fresh_id)]

    def visit_Plus(self, node: Plus) -> Sequence[str | NT]:
        fresh_id = self._fresh()
        seq = self.visit(node.element)
        self.rules[fresh_id] = [seq, seq + [NT(fresh_id)]]  # a+ = a | a a+
        return [NT(fresh_id)]

    def visit_Optional(self, node: Optional) -> Sequence[str | NT]:
        fresh_id = self._fresh()
        seq = self.visit(node.element)
        self.rules[fresh_id] = [[], seq]  # a? = ε | a
        return [NT(fresh_id)]

    def visit_Power(self, node: Power) -> Sequence[str | NT]:
        seq = self.visit(node.element)
        return seq * node.times

    def visit_Loop(self, node: Loop) -> Sequence[str | NT]:
        times = node.times
        seq = self.visit(node.element)
        fresh_id = self._fresh()
        if times.upper:
            if times.lower <= times.upper:
                self.rules[fresh_id] = [seq * k for k in range(0, times.upper - times.lower + 1)]
                # a{,n-m} = a{0} | ... | a{n-m}
                return seq * times.lower + [NT(fresh_id)]  # a{m,n} = a{m} a{,n-m}
            else:
                self.ctx.issue(EmptyRange(self.ctx.file_path, times.pos))
                return []  # empty language
        else:
            self.rules[fresh_id] = [[], seq + [NT(fresh_id)]]  # a* = ε | a a*
            return seq * times.lower + [NT(fresh_id)]  # a{m,} = a{m} a*


b_type_items: FrozenSet[str] = frozenset(['str', 'bool', 'int', 'float', 'complex', 'bytes'])
type_items: FrozenSet[str] = frozenset([*b_type_items, 'typing.Any'])
b_constr_items: FrozenSet[str] = frozenset(['tuple', 'list', 'set', 'dict'])


def analyze(annot: ast.expr, ctx: Context) -> Type:
    """Analyze a type annotation."""
    analyzer = Analyzer(ctx)
    return analyzer.visit(annot)


class Analyzer(ast.NodeVisitor):
    def __init__(self, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx

    def visit_Constant(self, node: ast.Constant) -> Type:
        if node.value is None:
            return none_type

        return AnyType()

    def visit_Name(self, node: ast.Name) -> Type:
        match self.ctx.lookup(node.id):
            case TypeDef(t):
                return t
            case TypeConstrDef(tc):
                return self._check_nil_constr(tc, node)
            case None if node.id in b_type_items:
                return BuiltinType(node.id)

        return AnyType()

    def _check_nil_constr(self, constr: str, name_tree: ast.expr) -> Type:
        match constr:
            case 'flat.py.lang':
                self.ctx.issue(ArityMismatch(constr, 1, 0,
                                             self.ctx.file_path, get_range(name_tree)))
            case 'flat.py.refine':
                self.ctx.issue(ArityMismatch(constr, (2,), 0,
                                             self.ctx.file_path, get_range(name_tree)))
            case 'typing.Literal':
                self.ctx.issue(ArityMismatch(constr, (1,), 0,
                                             self.ctx.file_path, get_range(name_tree)))
            case 'typing.Union':
                # NOTE: mypy interprets this as a bottom type
                self.ctx.issue(ArityMismatch(constr, (2,), 0,
                                             self.ctx.file_path, get_range(name_tree)))
            case 'typing.Optional':
                self.ctx.issue(ArityMismatch(constr, 1, 0,
                                             self.ctx.file_path, get_range(name_tree)))

        return AnyType()

    def visit_Call(self, node: ast.Call) -> Type:
        match node.func:
            case ast.Name(name):
                match self.ctx.lookup(name):
                    case TypeConstrDef('flat.py.lang'):
                        return self._check_lang(node)
                    case TypeConstrDef('flat.py.refine'):
                        return self._check_refine(node)

        return AnyType()

    def _check_lang(self, call: ast.Call) -> Type:
        if len(call.args) != 1:
            self.ctx.issue(ArityMismatch('flat.py.lang', 1, len(call.args),
                                         self.ctx.file_path, get_range(call.func)))
            return AnyType()

        syntax = 'ebnf'
        name: ast.expr | None = None
        for kw in call.keywords:
            if kw.arg == 'syntax':
                match kw.value:
                    case ast.Constant(str() as s) if s in LANG_SYNTAX:
                        syntax = s
                    case _:
                        self.ctx.issue(InvalidValue('syntax', ', '.join(LANG_SYNTAX),
                                                    self.ctx.file_path, get_range(kw.value)))
            elif kw.arg == 'name':
                name = kw.value

        arg = call.args[0]
        match arg:
            case ast.Constant(str() as s):
                if os.path.exists(self.ctx.file_path):
                    arg_code = get_code(self.ctx.file_path, get_range(arg))
                    if arg_code.startswith('"""'):
                        assert arg_code.endswith('"""')
                        quote_len = 3
                    else:
                        assert arg_code.startswith('"') or arg_code.startswith("'")
                        quote_len = 1
                    grammar_source = arg_code[quote_len:-quote_len]
                else:
                    quote_len = 0
                    grammar_source = s
                return analyze_lang(grammar_source, self.ctx, syntax=syntax, name=name,
                                    start=(arg.lineno - 1, arg.col_offset + quote_len))

        self.ctx.issue(InvalidArg('flat.py.lang', 'grammar (a string literal)',
                                  self.ctx.file_path, get_range(arg)))
        return AnyType()

    def _check_refine(self, call: ast.Call) -> Type:
        if len(call.args) < 2:
            self.ctx.issue(ArityMismatch('flat.py.refine', (2,), len(call.args),
                                         self.ctx.file_path, get_range(call.func)))
            return AnyType()

        t = self.visit(call.args[0])
        conds: list[ast.expr] = []
        for arg in call.args[1:]:
            match arg:
                case ast.Constant(str() as s):
                    conds.append(ast.parse(s, mode='eval').body)
                case _:
                    self.ctx.issue(InvalidArg('flat.py.refine', 'condition (a string literal)',
                                              self.ctx.file_path, get_range(arg)))

        return RefinedType(t, conds)

    def visit_Subscript(self, node: ast.Subscript) -> Type:
        match node.value:
            case ast.Name(name):
                match self.ctx.lookup(name):
                    case TypeConstrDef(tc):
                        return self._check_constr(tc, get_type_args(node), get_range(node))
                    case None if name in b_constr_items:
                        return self._check_constr(name, get_type_args(node), get_range(node))
                    case Type() as t:
                        self.ctx.issue(InvalidType(f"type '{t}' does not take arguments",
                                                   self.ctx.file_path, get_range(node)))
                        return AnyType()

        return AnyType()

    def _check_constr(self, constr: str, args: Sequence[ast.expr], type_pos: Range) -> Type:
        match constr:
            case 'flat.py.lang':
                self.ctx.issue(InvalidType(f"expected lang(...)", self.ctx.file_path, type_pos))
                return AnyType()

            case 'flat.py.refine':
                self.ctx.issue(InvalidType(f"expected refine(..., ...)", self.ctx.file_path, type_pos))
                return AnyType()

            case 'tuple':
                variant = False
                fixed_args = args
                if is_ellipsis(args[-1]):
                    variant = True
                    fixed_args = args[:-1]

                elem_types: list[Type] = []
                for arg in fixed_args:
                    if is_ellipsis(arg):
                        self.ctx.issue(InvalidArg(constr, 'type', self.ctx.file_path, get_range(arg)))
                    else:
                        elem_types.append(self.visit(arg))
                return TupleType(elem_types, variant=variant)

            case 'list' | 'set':
                if len(args) != 1:
                    self.ctx.issue(ArityMismatch(constr, 1, len(args), self.ctx.file_path, type_pos))
                    return AnyType()

                elem_type = self.visit(args[0])
                if constr == 'list':
                    return ListType(elem_type)
                else:
                    return SetType(elem_type)

            case 'dict':
                if len(args) != 2:
                    self.ctx.issue(ArityMismatch(constr, 2, len(args), self.ctx.file_path, type_pos))
                    return AnyType()

                key_type = self.visit(args[0])
                value_type = self.visit(args[1])
                return DictType(key_type, value_type)

            case 'typing.Literal':
                values: list[LitValue] = []
                for arg in args:
                    values += self._check_lit_value(arg)
                return LitType(values)

            case 'typing.Union':
                types = [self.visit(e) for e in args]
                return UnionType(types)

            case 'typing.Optional':
                if len(args) != 1:
                    self.ctx.issue(ArityMismatch(constr, 1, len(args), self.ctx.file_path, type_pos))
                    return AnyType()

                typ = self.visit(args[0])
                return UnionType([typ, none_type])

            case _:
                raise NameError(f"Unknown type constructor '{constr}'.")

    def _check_lit_value(self, arg: ast.expr) -> Sequence[LitValue]:
        match arg:
            case ast.Constant(v):
                return [v]
            case ast.UnaryOp(ast.USub(), ast.Constant(v)) if isinstance(v, (int, float, complex)):
                return [-v]

        match self.visit(arg):
            case LitType(vs):
                return vs
            case _:
                self.ctx.issue(InvalidArg('typing.Literal', 'literal value',
                                          self.ctx.file_path, get_range(arg)))
                return []

    def visit_BinOp(self, node: ast.BinOp) -> Type:
        if isinstance(node.op, ast.BitOr):
            args = get_operands(node, ast.BitOr)
            return self._check_constr('typing.Union', args, get_range(node))

        return AnyType()

    def generic_visit(self, node: ast.AST) -> Type:
        return AnyType()
