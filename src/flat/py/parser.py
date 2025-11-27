import re
import string
from abc import abstractmethod, ABC
from typing import FrozenSet

from parsy import Parser, Result, ParseError, line_info_at, seq, alt, forward_declaration

from flat.py.diagnostics import Position, Range, Location, InvalidSyntax
from flat.py.grammar import *

__all__ = ['grammar_formats', 'parse']

grammar_formats: FrozenSet[str] = frozenset(['ebnf', 'regex'])


def parse(source: str,
          *,
          grammar_format: str = 'ebnf',
          file_path: str = '<unknown>',
          start_pos: Position = Position(0, 0)) -> Grammar | InvalidSyntax:
    """Parse a grammar in the given format."""
    match grammar_format:
        case 'ebnf':
            parser = EBNFParser(file_path, angled=True).grammar()
        case 'regex':
            parser = RegexParser(file_path).grammar()
        case _:
            raise ValueError(f"unknown grammar format: {grammar_format!r}")

    try:
        return parser.parse(source)
    except ParseError as err:
        expected_list: list[str] = sorted(err.expected)
        messages: list[str] = []
        for i in range(len(expected_list)):
            s = expected_list[i]
            if s.startswith('[') and s.endswith(']'):
                expected_list[i] = s[1:-1]
            elif s != 'EOF':
                messages.append(s)

        if len(messages) == 1:
            msg = messages[0]
        elif len(messages) > 1:
            assert False, "multiple error messages"
        elif len(expected_list) == 1:
            msg = f"expected {expected_list[0]}"
        else:
            msg = f"expected one of {', '.join(expected_list)}"

        pos = start_pos + line_info_at(source, err.index)
        loc = Location(file_path, Range(pos, pos))
        return InvalidSyntax(msg, loc)


def expect(s: str) -> Parser:
    @Parser
    def expect_parser(source: str, offset: int) -> Result:
        if source.startswith(s, offset):
            return Result.success(offset + len(s), s)
        else:
            return Result.failure(offset, f"['{s}']")

    return expect_parser


ESCAPE_CHARS = {
    '\\': '\\',
    "'": "'",
    '"': '"',
    'a': '\a',
    'b': '\b',
    'f': '\f',
    'n': '\n',
    'r': '\r',
    't': '\t',
    'v': '\v',
}


def char(special: str) -> Parser:
    @Parser
    def char_parser(source: str, offset: int) -> Result:
        if offset < len(source) and source[offset] != '\\' and source[offset] not in special:
            return Result.success(offset + 1, source[offset])

        if offset + 1 < len(source) and source[offset] == '\\':
            if source[offset + 1] in ESCAPE_CHARS:
                return Result.success(offset + 2, ESCAPE_CHARS[source[offset + 1]])

            if source[offset + 1] in special:
                return Result.success(offset + 2, source[offset + 1])

            if source[offset + 1] in string.octdigits:  # octal (1-3 digits)
                if offset + 2 < len(source) and source[offset + 2] in string.octdigits:
                    if offset + 3 < len(source) and source[offset + 3] in string.octdigits:
                        return Result.success(offset + 4, chr(int(source[offset + 1:offset + 4], 8)))
                    else:
                        return Result.success(offset + 3, chr(int(source[offset + 1:offset + 3], 8)))
                else:
                    return Result.success(offset + 2, chr(int(source[offset + 1], 8)))

            if source[offset + 1] == 'x':  # hexadecimal (2 digits)
                if offset + 3 < len(source) and all(c in string.hexdigits for c in source[offset + 2:offset + 4]):
                    return Result.success(offset + 4, chr(int(source[offset + 2:offset + 4], 16)))
                else:
                    return Result.failure(offset + 2, "invalid Unicode escape sequence (expected 2 hex digits)")

            if source[offset + 1] == 'u':  # hexadecimal (4 digits)
                if offset + 5 < len(source) and all(c in string.hexdigits for c in source[offset + 2:offset + 6]):
                    return Result.success(offset + 6, chr(int(source[offset + 2:offset + 6], 16)))
                else:
                    return Result.failure(offset + 2, "invalid Unicode escape sequence (expected 4 hex digits)")

            if source[offset + 1] == 'U':  # hexadecimal (8 digits)
                if offset + 9 < len(source) and all(c in string.hexdigits for c in source[offset + 2:offset + 10]):
                    return Result.success(offset + 10, chr(int(source[offset + 2:offset + 10], 16)))
                else:
                    return Result.failure(offset + 2, "invalid Unicode escape sequence (expected 8 hex digits)")

            return Result.failure(offset, "invalid escape sequence")

        return Result.failure(offset, "invalid character")

    return char_parser


def char_seq(special: str) -> Parser:
    return char(special).many().map(''.join)


class ExprParser(ABC):
    def __init__(self, file_path: str, whitespace: str) -> None:
        self.file_path = file_path
        self.whitespace = whitespace

    def skip_whitespace(self, source: str, offset: int) -> int:
        while offset < len(source) and source[offset] in self.whitespace:
            offset += 1
        return offset

    def literal(self, s: str) -> Parser:
        @Parser
        def literal_parser(source: str, offset: int) -> Result:
            offset = self.skip_whitespace(source, offset)
            if source.startswith(s, offset):
                return Result.success(offset + len(s), s)
            else:
                return Result.failure(offset, f"['{s}']")

        return literal_parser

    def paren(self, p: Parser) -> Parser:
        return self.literal('(') >> p << self.literal(')')

    def brace(self, p: Parser) -> Parser:
        return self.literal('{') >> p << self.literal('}')

    def regex(self, r: str, name: str) -> Parser:
        pattern = re.compile(r)

        @Parser
        def regex_parser(source: str, offset: int) -> Result:
            offset = self.skip_whitespace(source, offset)
            m = pattern.match(source, offset)
            if m:
                i, j = m.span()
                return Result.success(j, source[i:j])
            else:
                return Result.failure(offset, f"[{name}]")

        return regex_parser

    def set_loc(self, p: Parser) -> Parser:
        @Parser
        def set_loc_parser(source: str, offset: int) -> Result:
            offset = self.skip_whitespace(source, offset)
            start = Position(*line_info_at(source, offset))
            result = p(source, offset)
            if result.status:
                end = Position(*line_info_at(source, result.index - 1))
                loc = Location(self.file_path, Range(start, end))
                setattr(result.value, 'loc', loc)
                return Result.success(result.index, result.value)

            return result

        return set_loc_parser

    def char_class(self) -> Parser:
        mode = expect('^').result('exclusive').optional('inclusive')
        literal = char('[]-')
        range = self.set_loc(seq(literal, expect('-') >> literal).combine(CharRange))
        items = (range | literal).at_least(1)
        return self.set_loc(self.literal('[') >> seq(mode, items).combine(CharClass) << expect(']'))

    @abstractmethod
    def atomic(self) -> Parser:
        raise NotImplementedError

    def expr(self) -> Parser:
        num = self.regex('[0-9]+', 'number').map(int)
        range = self.set_loc(self.brace(seq(num.optional(0), self.literal(',') >> num.optional()).combine(NatRange)))
        postfix_op = alt(self.literal('*').result(Star),
                         self.literal('+').result(Plus),
                         self.literal('?').result(Optional),
                         self.brace(num).map(lambda n: lambda e: Power(e, n)),
                         range.map(lambda r: lambda e: Loop(e, r)))

        parser = forward_declaration()
        base = self.atomic() | self.paren(parser)
        element = self.set_loc(seq(base, postfix_op.optional()).combine(lambda e, f: f(e) if f else e))
        concat = self.set_loc(element.at_least(1).map(lambda es: es[0] if len(es) == 1 else Concat(es)))
        union = self.set_loc(concat.sep_by(self.literal('|'), min=1
                                           ).map(lambda es: es[0] if len(es) == 1 else Union(es)))
        parser.become(union)
        return parser


class EBNFParser(ExprParser):
    def __init__(self, file_path: str, angled: bool) -> None:
        super().__init__(file_path, string.whitespace)
        self.angled = angled

    def symbol(self) -> Parser:
        symbol = self.set_loc(self.regex('[A-Za-z0-9_-]+', 'identifier').map(Ref))
        if self.angled:
            symbol |= self.set_loc(self.regex('<[A-Za-z0-9_-]+>', 'identifier').map(lambda s: Ref(s[1:-1])))
        return symbol

    def atomic(self) -> Parser:
        single_quote = self.literal("'") >> char_seq("'") << expect("'")
        double_quote = self.literal('"') >> char_seq('"') << expect('"')
        constant = self.set_loc((single_quote | double_quote).map(Lit))
        return constant | self.char_class() | self.symbol()

    def grammar(self) -> Parser:
        rule = self.set_loc(seq(self.symbol(), self.literal(':') >> self.expr() << self.literal(';')).combine(Rule))
        return rule.at_least(1) << self.literal('')


class RegexParser(ExprParser):
    def __init__(self, file_path: str) -> None:
        super().__init__(file_path, '')

    def atomic(self) -> Parser:
        constant = self.set_loc(char('.^$*+?{}[]()|').map(Lit))
        return constant | self.char_class()

    def grammar(self) -> Parser:
        return self.expr().map(lambda e: [Rule(Ref('start'), e)])
