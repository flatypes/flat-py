from parsy import forward_declaration, seq, Parser, alt

from flat.core_lang.ast import *
from flat.core_lang.expr_parser import expr_parser, Postfix, Prefix, InfixL, InfixR
from flat.parser import (token, ident, brace, comma, paren, int_lit, bool_lit, string_lit, with_pos, rule, parse_using,
                         seq_with_pos)

# from flat.compiler.issuer import Issuer
# from flat.compiler.trees import *

# parsers

named_type = ident.map(NamedTypeTree)
expr = forward_declaration()
refinement_type = brace(seq(named_type, token('|') >> expr)).combine(RefinementTypeTree)
typ = expr_parser(named_type, [
    InfixR(token('->').result(lambda t1, t2: FunTypeTree([t1], t2))),
    Prefix(paren(named_type.sep_by(comma)).map(lambda ts: lambda t: FunTypeTree(ts, t)) << token('->'))
]) | refinement_type

constant = (int_lit | bool_lit | string_lit).map(Constant)
variable = ident.map(Var)
if_expr = seq_with_pos(token('if') >> expr, token('then') >> expr, token('else') >> expr).combine(IfThenElse)
lambda_params = ident.map(lambda x: [x]) | paren(ident.sep_by(comma))
lambda_expr = seq_with_pos(lambda_params, token('->') >> expr).combine(Lambda)


def prefix_parser(*ops: str) -> Parser:
    # NOTE: avoid capturing any variable in lambda expressions as their values may be updated
    return alt(*[with_pos(token(op)).combine(
        lambda op, pos: lambda e: App(Var(Ident(f'prefix_{op}', pos)), [e], Pos(pos.start, e.pos.end)))
        for op in ops])


def infix_parser(*ops: str) -> Parser:
    return alt(*[with_pos(token(op)).combine(
        lambda op, pos: lambda e1, e2: App(Var(Ident(op, pos)), [e1, e2], Pos(e1.pos.start, e2.pos.end)))
        for op in ops])


expr.become(lambda_expr | if_expr | expr_parser(constant | variable | paren(expr), [
    Postfix(with_pos(paren(expr.sep_by(comma))).combine(
        lambda es, pos: lambda f: App(f, es, Pos(f.pos.start, pos.end)))),
    Prefix(prefix_parser('-')),
    InfixL(infix_parser('*', '/', '%')),
    InfixL(infix_parser('+', '-')),
    # Postfix(select.map(lambda f: lambda e: f(e))),
    Postfix(token('in') >> ident.map(lambda lang: lambda e: InLang(e, lang, Pos(e.pos.start, lang.pos.end)))),
    InfixL(infix_parser('>=', '<=', '>', '<')),
    InfixL(infix_parser('==', '!=')),
    Prefix(prefix_parser('!')),
    InfixL(infix_parser('&&')),
    InfixL(infix_parser('||')),
    # Prefix(lambda_params.map(lambda xs: lambda e: Lambda(xs, e)) << token('->'))
]))

stmt = forward_declaration()
body = brace(stmt.many())

return_stmt = token('return') >> expr.optional().map(Return) << token(';')
if_stmt = token('if') >> seq(expr, body, (token('else') >> body).optional(default=[])).combine(If)
while_stmt = token('while') >> seq(expr, body).combine(While)
assert_stmt = token('assert') >> expr.map(Assert) << token(';')

just_call = token('call') >> seq(ident, paren(expr.sep_by(comma))).combine(Call) << token(';')
call_and_assign = seq(ident, token('=') >> just_call).combine(lambda x, call: call.set_lvalue(x))
call_stmt = just_call | call_and_assign
declare_stmt = seq(ident, token(':') >> typ).combine(Declare) << token(';')
assign_stmt = seq(ident, token('=') >> expr).combine(Assign) << token(';')

stmt.become(return_stmt | if_stmt | while_stmt | assert_stmt | call_stmt | declare_stmt | assign_stmt)

lang_def = token('lang') >> seq(ident, brace(rule.many())).combine(LangDef)
param = seq(ident, token(':') >> typ).map(tuple)
method_spec = token('requires') >> expr.map(MethodPreSpec) | token('ensures') >> expr.map(MethodPostSpec)
method_return = (token(':') >> typ).optional()
method_def = token('method') >> seq(ident, paren(param.sep_by(comma)), method_return,
                                    method_spec.many(), body).combine(MethodDef)

top_level_def = lang_def | method_def
program = top_level_def.many()


def parse_program(inp: str, filename: str) -> Program:
    return parse_using(program, inp, filename, (1, 1))
