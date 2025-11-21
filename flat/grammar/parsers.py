from abc import abstractmethod
import string
from parsy import Parser, Result, line_info_at, string as expect, seq, alt, forward_declaration, ParseError
import re

from flat.grammar.ast import *
from flat.grammar.diagnostics import Position, Range, Location

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

class ExprParser:
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
                return Result.failure(offset, s)
        
        return literal_parser
    
    def paren(self, p: Parser) -> Parser:
        return self.literal('(') >> p << self.literal(')')
    
    def brace(self, p: Parser) -> Parser:
        return self.literal('{') >> p << self.literal('}')
    
    def regex(self, r: str) -> Parser:
        pattern = re.compile(r)

        @Parser
        def regex_parser(source: str, offset: int) -> Result:
            offset = self.skip_whitespace(source, offset)
            m = pattern.match(source, offset)
            if m:
                i, j = m.span()
                return Result.success(j, source[i:j])
            else:
                return Result.failure(offset, f"pattern {r}")
        
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

    def char(self, special: str) -> Parser:
        @Parser
        def char_parser(source: str, offset: int) -> Result:
            if offset < len(source) and source[offset] != '\\' and source[offset] not in special:
                return Result.success(offset + 1, source[offset])
            
            if offset + 1 < len(source) and source[offset] == '\\':
                if source[offset + 1] in ESCAPE_CHARS:
                    return Result.success(offset + 2, ESCAPE_CHARS[source[offset + 1]])
            
                if source[offset + 1] in special:
                    return Result.success(offset + 2, source[offset + 1])
                
                if source[offset + 1] in string.octdigits: # octal (1-3 digits)
                    if offset + 2 < len(source) and source[offset + 2] in string.octdigits:
                        if offset + 3 < len(source) and source[offset + 3] in string.octdigits:
                            return Result.success(offset + 4, chr(int(source[offset + 1:offset + 4], 8)))
                        else:
                            return Result.success(offset + 3, chr(int(source[offset + 1:offset + 3], 8)))
                    else:
                        return Result.success(offset + 2, chr(int(source[offset + 1], 8)))

                if source[offset + 1] == 'x': # hexadecimal (2 digits)
                    if offset + 3 < len(source) and all(c in string.hexdigits for c in source[offset + 2:offset + 4]):
                        return Result.success(offset + 4, chr(int(source[offset + 2:offset + 4], 16)))
                    else:
                        return Result.failure(offset + 2, "2 hex digits (error: invalid Unicode escape sequence)")
                    
                if source[offset + 1] == 'u': # hexadecimal (4 digits)
                    if offset + 5 < len(source) and all(c in string.hexdigits for c in source[offset + 2:offset + 6]):
                        return Result.success(offset + 6, chr(int(source[offset + 2:offset + 6], 16)))
                    else:
                        return Result.failure(offset + 2, "4 hex digits (error: invalid Unicode escape sequence)")
                
                if source[offset + 1] == 'U': # hexadecimal (8 digits)
                    if offset + 9 < len(source) and all(c in string.hexdigits for c in source[offset + 2:offset + 10]):
                        return Result.success(offset + 10, chr(int(source[offset + 2:offset + 10], 16)))
                    else:
                        return Result.failure(offset + 2, "8 hex digits (error: invalid Unicode escape sequence)")
                    
                return Result.failure(offset, f"a valid escape character (error: invalid escape sequence)")
            
            return Result.failure(offset, f"an ordinary character (error: invalid character)")

        return char_parser
    
    def char_seq(self, special: str) -> Parser:
        return self.char(special).many().map(''.join)

    def char_class(self) -> Parser:
        mode = expect('^').result('exclusive').optional('inclusive')
        literal = self.char('[]-')
        range = self.set_loc(seq(literal, expect('-') >> literal).combine(CharRange))
        items = (range | literal).at_least(1)
        return self.set_loc(self.literal('[') >> seq(mode, items).combine(CharClass) << expect(']'))
    
    @abstractmethod
    def atomic(self) -> Parser:
        raise NotImplementedError
    
    def expr(self) -> Parser:
        num = self.regex(r'[0-9]+').map(int)
        range = self.set_loc(self.brace(seq(num.optional(0), self.literal(',') >> num.optional()).combine(NatRange)))
        postfix_op = alt(
            self.literal('*').result(Star),
            self.literal('+').result(Plus),
            self.literal('?').result(Optional),
            self.brace(num).map(lambda n: lambda e: Power(e, n)),
            range.map(lambda r: lambda e: Loop(e, r))
        )

        parser = forward_declaration()
        base = self.atomic() | self.paren(parser)
        element = self.set_loc(seq(base, postfix_op.optional()).combine(lambda e, f: f(e) if f else e))
        concat = self.set_loc(element.at_least(1).map(lambda es: es[0] if len(es) == 1 else Concat(es)))
        union = self.set_loc(concat.sep_by(self.literal('|'), min=1
                                           ).map(lambda es: es[0] if len(es) == 1 else Union(es)))
        parser.become(union)
        return parser

def parse_RE(source: str, file_path: str = '<unknown>') -> RE:
    parser = REParser(file_path).expr()
    return parser.parse(source)

class REParser(ExprParser):
    def __init__(self, file_path: str) -> None:
        super().__init__(file_path, '')

    def atomic(self) -> Parser:
        constant = self.set_loc(self.char('.^$*+?{}[]()|').map(Lit))
        return constant | self.char_class()

def parse_CFG(source: str, file_path: str = '<unknown>', *, angled: bool = True) -> list[Rule]:
    parser = CFGParser(file_path, angled).cfg()
    try:
        return parser.parse(source)
    except ParseError as e:
        row, offset = line_info_at(source, e.index)
        code_line = source.splitlines()[row]
        caret_line = ' ' * offset + '^'
        long_string = f"{e}\n{code_line}\n{caret_line}"
        raise SyntaxError(long_string)

class CFGParser(ExprParser):
    def __init__(self, file_path: str, angled: bool) -> None:
        super().__init__(file_path, string.whitespace)
        self.angled = angled

    def symbol(self) -> Parser:
        symbol = self.set_loc(self.regex(r'[A-Za-z0-9_-]+').map(Symbol))
        if self.angled:
            symbol |= self.set_loc(self.regex(r'<[A-Za-z0-9_-]+>').map(lambda s: Symbol(s[1:-1])))
        return symbol

    def atomic(self) -> Parser:
        single_quote = self.literal("'") >> self.char_seq("'") << expect("'")
        double_quote = self.literal('"') >> self.char_seq('"') << expect('"')
        constant = self.set_loc((single_quote | double_quote).map(Lit))
        return constant | self.char_class() | self.symbol()
    
    def cfg(self) -> Parser:
        rule = self.set_loc(seq(self.symbol(), self.literal(':') >> self.expr() << self.literal(';')).combine(Rule))
        return rule.at_least(1) << self.literal('')
