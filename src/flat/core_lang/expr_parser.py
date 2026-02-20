import functools
from dataclasses import dataclass

from parsy import Parser, seq


class OpGroup:
    pass


@dataclass
class Prefix(OpGroup):
    op: Parser  # T -> T


@dataclass
class Postfix(OpGroup):
    op: Parser  # T -> T


@dataclass
class InfixL(OpGroup):
    op: Parser  # (T, T) -> T


@dataclass
class InfixR(OpGroup):
    op: Parser  # (T, T) -> T


def fold_left(func, acc, xs):
    return functools.reduce(func, xs, acc)


def fold_right(func, acc, xs):
    return functools.reduce(lambda x, y: func(y, x), xs[::-1], acc)


def _make_one_level(term: Parser, op_group: OpGroup) -> Parser:
    match op_group:
        case Prefix(op):
            return seq(op.many(), term).combine(lambda ops, t: fold_right(lambda f, e: f(e), t, ops))
        case Postfix(op):
            return seq(term, op.many()).combine(lambda t, ops: fold_left(lambda e, f: f(e), t, ops))
        case InfixL(op):
            return seq(term, seq(op, term).many()).combine(
                lambda t, ts: fold_left(lambda l, fr: fr[0](l, fr[1]), t, ts))
        case InfixR(op):
            return seq(seq(term, op).many(), term).combine(
                lambda ts, t: fold_right(lambda lf, r: lf[1](lf[0], r), t, ts))


def expr_parser(term: Parser, op_table: list[OpGroup]) -> Parser:
    return fold_left(_make_one_level, term, op_table)
