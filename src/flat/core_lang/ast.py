from copy import deepcopy
from dataclasses import dataclass
from typing import Optional, Tuple

from flat.ast import Ident, Lit, Rule
from flat.pos import Pos


class Expr:
    pos: Pos


# --- Types ---
class TypeTree:
    pass


@dataclass
class NamedTypeTree(TypeTree):
    ident: Ident


@dataclass
class FunTypeTree(TypeTree):
    args: list[TypeTree]
    returns: TypeTree


@dataclass
class RefinementTypeTree(TypeTree):
    base: TypeTree
    refinement: Expr


# --- Expressions ---

@dataclass
class Constant(Expr):
    lit: Lit

    @property
    def pos(self) -> Pos:
        return self.lit.pos


@dataclass
class Var(Expr):
    ident: Ident

    @property
    def pos(self) -> Pos:
        return self.ident.pos


@dataclass
class App(Expr):
    fun: Expr
    args: list[Expr]
    pos: Pos


def apply(name: str, *args: Expr) -> App:
    return App(Var(name), list(args))


def prefix(op: str, operand: Expr) -> App:
    return apply(f'prefix_{op}', operand)


def infix(op: str, lhs: Expr, rhs: Expr) -> App:
    return apply(op, lhs, rhs)


@dataclass
class InLang(Expr):
    receiver: Expr
    lang: Ident
    pos: Pos


@dataclass
class Select(Expr):
    receiver: Expr
    select_all: bool
    lang: Ident
    path_is_absolute: bool
    path: list[Ident]


@dataclass
class Lambda(Expr):
    params: list[Ident]
    body: Expr
    pos: Pos


@dataclass
class IfThenElse(Expr):
    cond: Expr
    then_branch: Expr
    else_branch: Expr
    pos: Pos


def subst_expr(expr: Expr, mappings: dict[str, Expr], closed: frozenset[str] = frozenset()) -> Expr:
    match expr:
        case Constant():
            return expr
        case Var(Ident(x)):
            return mappings[x] if x in mappings and x not in closed else expr
        case App(e, es, pos):
            return App(subst_expr(e, mappings, closed),
                       [subst_expr(e, mappings, closed) for e in es], pos)
        case Lambda(xs, e, pos):
            return Lambda(xs, subst_expr(e, mappings, closed | frozenset(x.name for x in xs)), pos)
        case InLang(e, lang, pos):
            return InLang(subst_expr(e, mappings, closed), lang, pos)
        case Select(e) as node:
            copied = deepcopy(node)
            copied.receiver = subst_expr(e, mappings, closed)
            return copied
        case IfThenElse(e, e1, e2, pos):
            return IfThenElse(subst_expr(e, mappings, closed),
                              subst_expr(e1, mappings, closed),
                              subst_expr(e2, mappings, closed), pos)
        case _:
            raise NotImplementedError


# --- Statements ---
class Stmt:
    pass


@dataclass
class Declare(Stmt):
    var: Ident
    type_annot: TypeTree


@dataclass
class Assign(Stmt):
    var: Ident
    value: Expr


@dataclass
class Call(Stmt):
    method: Ident
    args: list[Expr]
    var: Optional[Ident] = None

    def set_lvalue(self, var: Ident):
        self.var = var
        return self


@dataclass
class Assert(Stmt):
    cond: Expr
    err: Optional[str] = None


@dataclass
class Return(Stmt):
    value: Optional[Expr] = None


@dataclass
class If(Stmt):
    cond: Expr
    then_body: list[Stmt]
    else_body: list[Stmt]


@dataclass
class While(Stmt):
    cond: Expr
    body: list[Stmt]


# --- Definitions ---
@dataclass
class Def:
    ident: Ident

    @property
    def name(self) -> str:
        return self.ident.name


@dataclass
class LangDef(Def):
    rules: list[Rule]


# @dataclass
# class TypeAlias(Def):
#     body: TypeTree


# @dataclass
# class FunDef(Def):
#     params: list[Param]
#     return_type: TypeTree
#     value: Expr


@dataclass
class MethodSpec:
    cond: Expr


class MethodPreSpec(MethodSpec):
    pass


class MethodPostSpec(MethodSpec):
    pass


@dataclass
class MethodDef(Def):
    params: list[Tuple[str, TypeTree]]
    returns: Optional[TypeTree]
    specs: list[MethodSpec]
    body: list[Stmt]


Program = list[Def]
