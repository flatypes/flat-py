from typing import Literal

from flat.py import lang, refine

type T1 = lang
type T2 = lang('a', syntax='null')
type T3 = lang(syntax='regex')
type T4 = lang(404)

type T5 = refine
type T6 = refine(int)
type T7 = refine(int, '_ > 0', lambda x: x < 10)

type T8 = Literal
type A = refine(int, '_ >= 0')
type B = Literal['a', 'b', 'c']
type T9 = Literal[0, -1, str, A, B]

type T10 = tuple[int, ..., str, ...]
type T11 = list[int, bool]
type T12 = dict[str]

type L1 = lang('a++', syntax='regex')

type L2 = lang('[z-a]', syntax='regex')

type L3 = lang("""
    start: A;
""")

type L4 = lang("""
    start: A;
    A: 'a'+;
    A: 'b'+;
""")

type Number = lang("""
    number: digit+;
    digit: [0-9];
""")

type L5 = lang("""
    start: Number "." Number;
""")
