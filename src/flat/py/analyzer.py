import ast
from typing import FrozenSet, Sequence

from flat.backend.lang import NT, project
from flat.py.ast_helpers import *
from flat.py.compile_time import *
from flat.py.diagnostics import *
from flat.py.grammar import *
from flat.py.parser import grammar_formats, parse

__all__ = ['analyze_lang', 'analyze']


def analyze_lang(grammar_source: str,
                 ctx: Context,
                 *,
                 grammar_format: str = 'ebnf',
                 start_pos: Position = Position(0, 0)) -> LangType | AnyType:
    """Analyze a grammar definition. Return a language type if parsing succeed; otherwise, return Any type."""
    if grammar_format not in grammar_formats:
        ctx.issue(InvalidFormat(Location(ctx.file_path, Range(start_pos, start_pos))))
        return AnyType()

    result = parse(grammar_source, grammar_format=grammar_format, file_path=ctx.file_path, start_pos=start_pos)
    if isinstance(result, InvalidSyntax):
        ctx.issue(result)
        return AnyType()

    rules = result
    nonterminals: list[str] = []
    for rule in rules:
        if rule.name.name not in nonterminals:
            nonterminals.append(rule.name.name)
        else:
            ctx.issue(RedefinedRule(rule.name.name, rule.name.loc))

    desugar = Desugar(ctx, frozenset(nonterminals))
    for rule in rules:
        desugar.visit_rule(rule.name.name, rule.body)

    return LangType(desugar.rules)


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

    def visit_rule(self, id: str, body: Expr) -> None:
        match body:
            case Union(es):
                self.rules[id] = [self.visit(e) for e in es]
            case _:
                self.rules[id] = [self.visit(body)]

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
                        self.ctx.issue(EmptyRange(c1, c2, item.loc))

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
                    for id in lang:
                        self.rules[f'{node.name}.{id}'] = lang[id]
                else:
                    self.ctx.issue(NoStartRule(node.name, node.loc))
                return [NT(f'{node.name}.start')]
            case _:
                self.ctx.issue(UndefinedRule(node.name, node.loc))
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
                self.ctx.issue(EmptyRange(str(times.lower), str(times.upper), times.loc))
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
        else:
            self.ctx.issue(InvalidType(self.ctx.get_loc(node)))
            return AnyType()

    def visit_Name(self, node: ast.Name) -> Type:
        match self.ctx.lookup(node.id):
            case None:
                if node.id in b_type_items:
                    return TypeName(node.id)
                elif node.id in b_constr_items:
                    return self._check_type_call_nil(node.id, node)
                else:
                    self.ctx.issue(UndefinedName(node.id, self.ctx.get_loc(node)))
                    return AnyType()
            case VarDef() | FunDef():
                self.ctx.issue(InvalidType(self.ctx.get_loc(node)))
                return AnyType()
            case TypeDef(t):
                return t
            case TypeConstrDef(id):
                return self._check_type_call_nil(id, node)
            case _:
                return AnyType()

    def _check_type_call_nil(self, fun_id: str, fun_node: ast.expr) -> Type:
        match fun_id:
            case 'tuple':
                return TupleType([AnyType()], variant=True)
            case 'list':
                return ListType(AnyType())
            case 'set':
                return SetType(AnyType())
            case 'dict':
                return DictType(AnyType(), AnyType())
            case 'typing.Literal':
                self.ctx.issue(ArityMismatch(fun_id, 'at least 1', 0, self.ctx.get_loc(fun_node)))
                return AnyType()
            case 'typing.Union':
                # NOTE: mypy interprets this as a bottom type
                self.ctx.issue(ArityMismatch(fun_id, 'at least 2', 0, self.ctx.get_loc(fun_node)))
                return AnyType()
            case 'typing.Optional':
                self.ctx.issue(ArityMismatch(fun_id, '1', 0, self.ctx.get_loc(fun_node)))
                return AnyType()
            case _:
                raise NameError(f"Unknown type constructor '{fun_id}'.")

    def visit_Call(self, node: ast.Call) -> Type:
        match node.func:
            case ast.Name(f):
                match self.ctx.lookup(f):
                    case None:
                        self.ctx.issue(UndefinedName(f, self.ctx.get_loc(node.func)))
                        return AnyType()
                    case TypeConstrDef(id):
                        return self._check_type_call_paren(id, node.args, node.keywords, self.ctx.get_loc(node))

        self.ctx.issue(InvalidType(self.ctx.get_loc(node)))
        return AnyType()

    def _check_type_call_paren(self, fun_id: str, args: list[ast.expr], keywords: list[ast.keyword],
                               loc: Location) -> Type:
        match fun_id, args:
            case 'flat.py.lang', [arg]:
                match arg:
                    case ast.Constant(str() as s):
                        grammar_format = self._get_format(keywords)
                        return analyze_lang(s, self.ctx, grammar_format=grammar_format, start_pos=loc.range.start)
                    case _:
                        self.ctx.issue(InvalidType(self.ctx.get_loc(arg)))
                        return AnyType()
            case 'flat.py.lang', _:
                self.ctx.issue(ArityMismatch('flat.py.lang', '1', len(args), loc))
                return AnyType()
            case 'flat.py.refine', [arg_t, arg_p]:
                t = self.visit(arg_t)
                match arg_p:
                    case ast.Constant(str() as code):
                        p = mk_lambda(['_'], ast.parse(code, mode='eval').body)
                    case p:
                        pass
                return RefinedType(t, p)
            case 'flat.py.refine', _:
                self.ctx.issue(ArityMismatch('flat.py.refine', '2', len(args), loc))
                return AnyType()
            case _:
                raise NameError(f"Unknown type constructor '{fun_id}'.")

    def _get_format(self, keywords: list[ast.keyword]) -> str:
        for kw in keywords:
            if kw.arg == 'format':
                match kw.value:
                    case ast.Constant(str() as s) if s in grammar_formats:
                        return s  # type: ignore
                    case _:
                        self.ctx.issue(InvalidFormat(self.ctx.get_loc(kw.value)))

        return 'ebnf'

    def visit_Subscript(self, node: ast.Subscript) -> Type:
        match node.value:
            case ast.Name(f):
                match self.ctx.lookup(f):
                    case None:
                        if f in b_constr_items:
                            return self._check_type_call_bracket(f, get_type_args(node), self.ctx.get_loc(node))
                        else:
                            self.ctx.issue(UndefinedName(f, self.ctx.get_loc(node.value)))
                            return AnyType()
                    case TypeConstrDef(id):
                        return self._check_type_call_bracket(id, get_type_args(node), self.ctx.get_loc(node))

        self.ctx.issue(InvalidType(self.ctx.get_loc(node)))
        return AnyType()

    def _check_type_call_bracket(self, fun_id: str, args: list[ast.expr], loc: Location) -> Type:
        match fun_id, args:
            case 'tuple', [*args, ast.Constant(v)] if v is ...:
                return TupleType([self.visit(arg) for arg in args], variant=True)
            case 'tuple', _:
                return TupleType([self.visit(arg) for arg in args])
            case 'list', [arg]:
                return ListType(self.visit(arg))
            case 'list', _:
                self.ctx.issue(ArityMismatch('list', '1', len(args), loc))
                return AnyType()
            case 'set', [arg]:
                return SetType(self.visit(arg))
            case 'set', _:
                self.ctx.issue(ArityMismatch('set', '1', len(args), loc))
                return AnyType()
            case 'dict', [key_arg, value_arg]:
                return DictType(self.visit(key_arg), self.visit(value_arg))
            case 'dict', _:
                self.ctx.issue(ArityMismatch('dict', '2', len(args), loc))
                return AnyType()
            case 'typing.Literal', _:
                return self._check_literal_type(args)
            case 'typing.Union', _:
                return UnionType([self.visit(e) for e in args])
            case 'typing.Optional', [arg]:
                return UnionType([self.visit(arg), none_type])
            case 'typing.Optional', _:
                self.ctx.issue(ArityMismatch('typing.Optional', '1', len(args), loc))
                return AnyType()
            case _:
                raise NameError(f"Unknown type constructor '{fun_id}'.")

    def _check_literal_type(self, args: list[ast.expr]) -> Type:
        values: list[LitValue] = []
        for arg in args:
            match arg:
                case ast.Constant(v):
                    values.append(v)
                case ast.UnaryOp(ast.USub(), ast.Constant(v)) if isinstance(v, (int, float, complex)):
                    values.append(-v)
                case _:
                    match self.visit(arg):
                        case LitType(vs):
                            values += vs
                        case _:
                            self.ctx.issue(InvalidLiteral(self.ctx.get_loc(arg)))

        return LitType(values)

    def visit_BinOp(self, node: ast.BinOp) -> Type:
        if isinstance(node.op, ast.BitOr):
            args = get_operands(node, ast.BitOr)
            return self._check_type_call_bracket('typing.Union', args, self.ctx.get_loc(node))
        else:
            self.ctx.issue(InvalidType(self.ctx.get_loc(node)))
            return AnyType()

    def generic_visit(self, node: ast.AST) -> Type:
        self.ctx.issue(InvalidType(self.ctx.get_loc(node)))
        return AnyType()
