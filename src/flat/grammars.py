import abc
from functools import reduce
from typing import Optional

from isla.derivation_tree import DerivationTree
from isla.helpers import is_valid_grammar
from isla.solver import ISLaSolver, SemanticError
from isla.type_defs import Grammar as ISLaGrammar

from flat.ast import (Rule, Clause, Token, Symbol, CharRange, Rep, Seq, Alt, RepExactly, RepInRange, Lit, Ident)


class Grammar:
    def __init__(self, name: str, clauses: dict[str, Clause], isla_grammar: ISLaGrammar):
        self.name = name
        self.clauses = clauses
        self.isla_solver = ISLaSolver(isla_grammar)

    def __contains__(self, word: str) -> bool:
        try:
            self.isla_solver.parse(word, skip_check=True, silent=True)
            return True
        except (SyntaxError, SemanticError):
            return False

    def parse(self, word: str) -> DerivationTree:
        return self.isla_solver.parse(word, skip_check=True, silent=True)

    def count(self, target: str, clause: Clause | str, direct: bool):
        """Count how many times a `target` nonterminal can appear in a parse tree derived from `clause`.
        If `direct` is set, only consider the direct children; otherwise the full tree.
        Return:
        - 0 if `target` does not appear on all trees;
        - 1 if `target` appears exactly once on all trees;
        - 2 if either `target` appears multiple times or undetermined.
        """

        def acc(n1, n2):
            """Addition of times: min(2, n1 + n2)."""
            match n1 + n2:
                case 0:
                    return 0
                case 1:
                    return 1
                case _:
                    return 2

        if isinstance(clause, str):
            clause = self.clauses[clause]

        match clause:
            case Symbol(name):
                n = 1 if name == target else 0
                if not direct:
                    n = acc(n, self.count(target, self.clauses[name], direct))
                return n
            case Rep(clause, _):
                if self.count(target, clause, direct) == 0:
                    return 0
                return 2
            case Seq(clauses):
                return reduce(acc, [self.count(target, clause, direct) for clause in clauses])
            case Alt(clauses):
                return reduce(lambda v1, v2: v1 if v1 == v2 else 2,
                              [self.count(target, clause, direct) for clause in clauses])
            case _:  # terminal clause
                return 0


class GrammarBuilder:
    @abc.abstractmethod
    def lookup_lang(self, name: str) -> Optional[Grammar]:
        raise NotImplementedError

    def validate(self, rules: list[Rule]) -> dict[str, Rule]:
        grammar: dict[str, Rule] = {}
        for rule in rules:
            if rule.name in grammar:
                raise NameError(f'redefined rule: {rule}')
                # self.issuer.error(RedefinedName(grammar[rule.name].pos, rule.ident.pos))
            else:
                grammar[rule.name] = rule

        if 'start' not in grammar:
            raise NameError
            # self.issuer.error(MissingStartRule(ident.pos))

        def check(clause: Clause) -> None:
            match clause:
                case CharRange(Lit(lower), lit) as cs:
                    if cs.end < cs.begin:
                        raise NameError(f"{cs.end} < {cs.begin} in clause {cs}")
                        # self.issuer.error(InvalidClause(f'this charactor (code={cs.end}) must > '
                        #                                 f'"{lower}" (code={cs.begin})', lit.pos))
                case Symbol(Ident('start')):
                    raise NameError
                    # self.issuer.error(InvalidClause('using start rule is not allowed here', clause.pos,
                    #                                 hint='introduce a new rule and let start rule point to it'))
                case Symbol(Ident(name)):
                    if name in grammar:
                        pass
                    elif self.lookup_lang(name) is None:
                        raise NameError(name)
                        # self.issuer.error(UndefinedName(clause.pos))
                case Rep(clause, rep_range):
                    check(clause)
                    match rep_range:
                        case RepExactly(lit):
                            match lit.value:
                                case 0:
                                    raise NameError
                                    # self.issuer.error(InvalidClause('0 is not allowed here', lit.pos,
                                    #                                 hint='use the empty clause "" instead'))
                                case 1:
                                    raise NameError
                                    # self.issuer.error(InvalidClause('1 is redundant here', lit.pos,
                                    #                                 hint='drop the repetition in this clause'))
                        case RepInRange(_, Lit() as lit) if lit.value == 0:
                            raise NameError
                            # self.issuer.error(InvalidClause('0 is not allowed here', lit.pos,
                            #                                 hint='use the empty clause "" instead'))
                        case RepInRange(Lit(lower), Lit() as lit) if lit.value <= lower:
                            raise NameError
                            # self.issuer.error(InvalidClause(f'this value must > {lower}', lit.pos))
                case Seq(clauses):
                    for clause in clauses:
                        check(clause)
                case Alt(clauses):
                    for clause in clauses:
                        check(clause)

        for rule in rules:
            check(rule.body)
        return grammar

    def reduce(self, grammar: dict[str, Rule]) -> dict[str, Clause]:
        clauses: dict[str, Clause] = {}

        def collect_used(clause: Clause, buf: set[str]) -> None:
            match clause:
                case Symbol(Ident(name)):
                    if name in grammar:
                        buf.add(name)
                    elif name not in clauses:
                        g = self.lookup_lang(name)
                        clauses[name] = g.clauses['start']
                        for k in g.clauses:
                            if k != 'start':
                                assert k not in clauses
                                clauses[k] = g.clauses[k]
                case Rep(c, _):
                    collect_used(c, buf)
                case Seq(cs):
                    for c in cs:
                        collect_used(c, buf)
                case Alt(cs):
                    for c in cs:
                        collect_used(c, buf)

        queue = ['start']
        while len(queue) > 0:
            n = queue.pop(0)
            if n not in clauses:
                clauses[n] = grammar[n].body
                used = set()
                collect_used(grammar[n].body, used)
                for x in used:
                    if x not in clauses:
                        queue.append(x)

        return clauses

    def __call__(self, name: str, rules: list[Rule], start: str = 'start') -> Grammar:
        if start != 'start':
            for rule in rules:
                if rule.name == 'start':
                    rule.body = Symbol(Ident(start, None))

        grammar = self.validate(rules)
        clauses = self.reduce(grammar)

        self._grammar = {}
        self._next_counter = 0

        for symbol in clauses:
            label = f'<{symbol}>'
            self._grammar[label] = self._convert(clauses[symbol])
            if label == '<start>' and len(self._grammar['<start>']) > 1:
                # NOTE: ISLa assumes the start rule to be a singleton
                start = self._fresh_nonterminal()
                self._grammar[start] = self._grammar['<start>']
                self._grammar['<start>'] = [start]

        assert is_valid_grammar(self._grammar)
        return Grammar(name, clauses, self._grammar)

    def _fresh_nonterminal(self) -> str:
        fresh_name = f'<-{str(self._next_counter)}>'
        self._next_counter += 1
        return fresh_name

    def _convert(self, clause: Clause) -> list[str]:
        match clause:
            case Token(Lit(str() as text, _)):
                if '<' in text or '>' in text:
                    quoted = ''
                    for ch in text:
                        match ch:
                            case '<':
                                quoted += '<-l>'
                                self._grammar['<-l>'] = ['<']
                            case '>':
                                quoted += '<-r>'
                                self._grammar['<-r>'] = ['>']
                            case _:
                                quoted += ch
                    return [quoted]
                return [text]
            case Symbol(Ident(name, _)):
                return [f'<{name}>']
            case CharRange() as cs:
                return [chr(code) for code in cs.get_range]
            case Rep(clause, rep_range):
                match self._convert(clause):
                    case [c]:
                        elem = c  # inline
                    case cs:
                        elem = self._fresh_nonterminal()
                        self._grammar[elem] = cs

                k1 = rep_range.lower
                k2 = rep_range.upper
                if k2:  # finite
                    return [elem * k for k in range(k1, k2 + 1)]
                else:  # infinite
                    elems = self._fresh_nonterminal()
                    self._grammar[elems] = [elem * k1, elem + elems]
                    return [elems]
            case Seq(clauses):
                concat = ''
                for clause in clauses:
                    match self._convert(clause):
                        case [c]:
                            concat += c
                        case cs:
                            group = self._fresh_nonterminal()
                            self._grammar[group] = cs
                            concat += group
                return [concat]
            case Alt(clauses):
                return [c for clause in clauses for c in self._convert(clause)]
            case other:
                raise NotImplementedError(other.__class__.__name__)
