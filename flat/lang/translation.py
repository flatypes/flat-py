from dataclasses import dataclass
from typing import Callable, Sequence, Mapping, FrozenSet

from flat.lang.ast import *
from flat.lang.diagnostics import *

# Normalization

@dataclass
class NT:
    """NonTerminal symbol in normal form."""
    id: str

type NormLang = Mapping[str, Sequence[Sequence[str | NT]]]

type LangFinder = Callable[[str], NormLang | None]

default_finder: LangFinder = lambda id: None

def normalize(lang: Lang, issuer: Issuer, finder: LangFinder = default_finder) -> NormLang:
    """Validate and normalize the language.

    :param lang: the language to normalize
    :param issuer: the issuer to report diagnostics to
    :param finder: the function to find languages by their IDs
    :return: a normalized language where each rule body is a list of alternatives, and
             each alternative is a list of terminals or nonterminals
    """
    if isinstance(lang, Expr):
        rules: Sequence[Rule] = [Rule(Name('start'), lang)]
    else:
        rules = lang
    
    # Set up context
    nonterminals: list[str] = []
    for rule in rules:
        if rule.name.id not in nonterminals:
            nonterminals.append(rule.name.id)
        else:
            issuer.issue(RedefinedRule(rule.name.id, rule.name.loc))
    ctx = Context(frozenset(nonterminals), finder)

    # Validate
    validator = Validator(issuer, ctx)
    for rule in rules:
        validator.visit(rule.body)

    # Normalize
    normalizer = Normalizer(ctx)
    for rule in rules:
        normalizer.rule(rule.name.id, rule.body)
    return normalizer.rules

@dataclass
class Context:
    nonterminals: FrozenSet[str]
    finder: LangFinder

    def lookup(self, id: str) -> NT | NormLang | None:
        if id in self.nonterminals:
            return NT(id)
        
        return self.finder(id)

class Validator(ExprVisitor):
    def __init__(self, issuer: Issuer, ctx: Context) -> None:
        self.issuer = issuer
        self.ctx = ctx

    def visit_CharClass(self, node: CharClass) -> None:
        for item in node.items:
            if isinstance(item, CharRange) and item.lower > item.upper:
                self.issuer.issue(EmptyRange(item.lower, item.upper, item.loc))

    def visit_Name(self, node: Name) -> None:
        item = self.ctx.lookup(node.id)
        if item is None:
            self.issuer.issue(UndefinedRule(node.id, node.loc))
        elif node.start and (isinstance(item, NT) or isinstance(item, Mapping) and node.start not in item):
            self.issuer.issue(UndefinedRule(node.start, node.loc))

    def visit_Loop(self, node: Loop) -> None:
        self.visit(node.element)
        times = node.times
        if times.upper and times.lower > times.upper:
            self.issuer.issue(EmptyRange(str(times.lower), str(times.upper), times.loc))

class Normalizer(ExprVisitor):
    def __init__(self, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx
        self.rules: dict[str, Sequence[Sequence[str | NT]]] = {}
        self._fresh_count = 0

    def _fresh(self) -> str:
        self._fresh_count += 1
        return f'@{self._fresh_count}'
    
    def rule(self, id: str, body: Expr) -> None:
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
                    for n in range(ord(c1), ord(c2) + 1):
                        chars.append(chr(n))
        
        if len(chars) == 1:
            return [chars.pop()]

        fresh_id = self._fresh()
        self.rules[fresh_id] = [[c] for c in chars]
        return [NT(fresh_id)]
    
    def visit_Name(self, node: Name) -> Sequence[str | NT]:
        item = self.ctx.lookup(node.id)
        if isinstance(item, NT):
            return [item]
        elif isinstance(item, Mapping):
            start = node.start if node.start else 'start'
            nested_lang = project(item, start)
            for id in nested_lang:
                self.rules[f'{node.id}.{id}'] = nested_lang[id]
            return [NT(f'{node.id}.{start}')]
        else:
            return []
    
    def visit_Concat(self, node: Concat) -> Sequence[str | NT]:
        return [s for element in node.elements for s in self.visit(element)]
    
    def visit_Union(self, node: Union) -> Sequence[str | NT]:
        fresh_id = self._fresh()
        self.rule(fresh_id, node)
        return [NT(fresh_id)]

    def visit_Star(self, node: Star) -> Sequence[str | NT]:
        fresh_id = self._fresh()
        seq = self.visit(node.element)
        self.rules[fresh_id] = [[], seq + [NT(fresh_id)]] # a* = ε | a a*
        return [NT(fresh_id)]
    
    def visit_Plus(self, node: Plus) -> Sequence[str | NT]:
        fresh_id = self._fresh()
        seq = self.visit(node.element)
        self.rules[fresh_id] = [seq, seq + [NT(fresh_id)]] # a+ = a | a a+
        return [NT(fresh_id)]
    
    def visit_Optional(self, node: Optional) -> Sequence[str | NT]:
        fresh_id = self._fresh()
        seq = self.visit(node.element)
        self.rules[fresh_id] = [[], seq] # a? = ε | a
        return [NT(fresh_id)]
    
    def visit_Power(self, node: Power) -> Sequence[str | NT]:
        seq = self.visit(node.element)
        return seq * node.times
    
    def visit_Loop(self, node: Loop) -> Sequence[str | NT]:
        times = node.times
        seq = self.visit(node.element)
        fresh_id = self._fresh()
        if times.upper:
            self.rules[fresh_id] = [seq * k for k in range(0, times.upper - times.lower + 1)]
                                                      # a{,n-m} = a{0} | ... | a{n-m}
            return seq * times.lower + [NT(fresh_id)] # a{m,n} = a{m} a{,n-m}
        else:
            self.rules[fresh_id] = [[], seq + [NT(fresh_id)]] # a* = ε | a a*
            return seq * times.lower + [NT(fresh_id)] # a{m,} = a{m} a*

# Projection

def project(lang: NormLang, start: str) -> NormLang:
    """Project the language to only include rules reachable from the start symbol."""
    reachable: set[str] = set()
    queue = [start]
    while len(queue) > 0:
        id = queue.pop(0)
        if id in lang and id not in reachable:
            reachable.add(id)
            for id in collect_nonterminals(lang[id]):
                if id not in reachable:
                    queue.append(id)
    return {id: lang[id] for id in reachable}

def collect_nonterminals(body: Sequence[Sequence[str | NT]]) -> FrozenSet[str]:
    """Collect all nonterminals occurring in the body."""
    ids: set[str] = set()
    for seq in body:
        for s in seq:
            if isinstance(s, NT):
                ids.add(s.id)
    return frozenset(ids)