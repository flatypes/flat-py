# whitespaces and comments
from string import digits, ascii_letters, punctuation
from traceback import FrameSummary
from typing import Any, Tuple

from parsy import (Parser, string as text, regex, whitespace, decimal_digit, seq, forward_declaration, any_char, alt,
                   ParseError, line_info_at, char_from)

from flat.ast import *
from flat.errors import ParsingError
from flat.pos import Pos

new_line = text('\n') | text('\r\n')
single_line_comment = text('//') >> regex(r'[^\r\n]').many() << new_line
multi_line_comment = text('/*') >> regex(r'[^*/]').many() << text('*/')
skip_whitespaces = (whitespace | single_line_comment | multi_line_comment).many()


# lexers

def token(word: str) -> Parser:
    return skip_whitespaces >> text(word)


comma = token(',')


def paren(p: Parser) -> Parser:
    return token('(') >> p << token(')')


def bracket(p: Parser) -> Parser:
    return token('[') >> p << token(']')


def brace(p: Parser) -> Parser:
    return token('{') >> p << token('}')


def make_string(*parts: str | list[str]) -> str:
    buf = ''
    for part in parts:
        match part:
            case str() as s:
                buf += s
            case list() as ss:
                buf += ''.join(ss)
    return buf


integer = skip_whitespaces >> decimal_digit.at_least(1).map(lambda digits: int(make_string(digits)))
hex_integer = skip_whitespaces >> (decimal_digit | char_from('AaBbCcDdEeFf')).at_least(1).map(
    lambda digits: int(make_string(digits), base=16))
boolean = skip_whitespaces >> (text('true').result(True) | text('false').result(False))


def unquote(raw: str) -> str:
    import ast
    e = ast.parse(raw).body[0]
    assert isinstance(e, ast.Expr) and isinstance(e.value, ast.Constant)
    v = e.value.value
    assert isinstance(v, str)
    return v


quote = text('"')
normal_char = regex(r'[^\r\n\f\\"]')
escape_char = seq(text('\\'), any_char).combine(make_string)
quoted_string = seq(quote, (normal_char | escape_char).many(), quote).combine(make_string)
string = skip_whitespaces >> quoted_string.map(unquote)

id_start = regex(r'[_a-zA-Z]')
id_rest = id_start | decimal_digit | text("'") | text("-")
identifier = skip_whitespaces >> seq(id_start, id_rest.many()).combine(make_string)


def with_pos(p: Parser) -> Parser:
    return skip_whitespaces >> p.mark().combine(lambda begin, res, end: (res, Pos(begin, (end[0], end[1] - 1))))


def seq_with_pos(*ps: Parser) -> Parser:
    return skip_whitespaces >> seq(*ps).mark().combine(lambda begin, rs, end: rs + [Pos(begin, (end[0], end[1] - 1))])


def positional(p: Parser) -> Parser:
    return with_pos(p).combine(lambda tree, pos: tree.set_pos(pos))


# parsers

int_lit = with_pos(integer).combine(Lit)
bool_lit = with_pos(boolean).combine(Lit)
string_lit = with_pos(string).combine(Lit)

ident = with_pos(identifier).combine(Ident)

terminal = string_lit.map(Token)
nonterminal = ident.map(Symbol)

char = with_pos(char_from(digits + ascii_letters +
                          ''.join(set(punctuation) - {'[', ']'}) + ' ')).combine(Lit)
char_range = seq(char, token('-') >> char).combine(CharRange)
charset_elem = char_range | char.map(Token)
charset = bracket(charset_elem.at_least(1)).map(lambda cs: cs[0] if len(cs) == 1 else Alt(cs))

# RFC extensions
dec_char = int_lit.map(lambda lit: Lit(chr(lit.value), lit.pos))
hex_char = with_pos(hex_integer).combine(Lit).map(lambda lit: Lit(chr(lit.value), lit.pos))
rfc_charset = alt(
    token('%d') >> seq(dec_char, (token('-') >> dec_char).optional()).combine(
        lambda n1, n2: (n1, n2 if n2 else n1)),
    token('%x') >> seq(hex_char, (token('-') >> hex_char).optional()).combine(
        lambda n1, n2: (n1, n2 if n2 else n1)),
).combine(CharRange)

clause = forward_declaration()
simple_clause = terminal | nonterminal | charset | rfc_charset | paren(clause)

rep_range = alt(
    token('*').result(RepStar()),
    token('+').result(RepPlus()),
    token('?').result(RepOpt()),
    brace(seq(int_lit.optional(), token(',') >> int_lit.optional())).combine(RepInRange),
    brace(int_lit).map(RepExactly)
)
repetition = seq(simple_clause, rep_range).combine(Rep) | simple_clause
concatenation = repetition.at_least(1).map(lambda cs: cs[0] if len(cs) == 1 else Seq(cs))
alternative = concatenation.sep_by(token('|'), min=1).map(lambda cs: cs[0] if len(cs) == 1 else Alt(cs))
clause.become(alternative)

rule = seq(ident, token(':') >> clause).combine(Rule) << token(';')
rules = rule.at_least(1)


def parse_using(parser: Parser, inp: str, filename: str, start_loc: Tuple[int, int]) -> Any:
    try:
        return (parser << skip_whitespaces).parse(inp)
    except ParseError as err:
        lineno, colno = start_loc
        row, offset = line_info_at(err.stream, err.index)
        real_lineno = lineno + row
        real_colno = (colno + offset) if row == 0 else offset
        frame = FrameSummary(filename, real_lineno, '<file>',
                             lookup_line=False, line=err.stream.splitlines()[row],
                             end_lineno=real_lineno, colno=real_colno - 1, end_colno=real_colno)
        raise ParsingError(err.expected, frame)
