import ast
import inspect
import itertools
import linecache
import sys
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import TracebackType, FrameType
from typing import Callable, Sequence

from flat.py.shared import Range, get_range, print_details, NT, Lang

__all__ = ['Type', 'BuiltinType', 'LangType', 'RefinedType', 'LitType',
           'UnionType', 'TupleType', 'ListType', 'SetType', 'DictType',
           'SOURCE', 'LINENO', 'check_arg_type', 'check_pre', 'check_type', 'check_post',
           'Range', 'NT', 'Lang']


## Types ##

class Type(ABC):
    """(Runtime) Type."""

    @abstractmethod
    def __contains__(self, value: object) -> bool:
        """Test if value is a member of this type."""
        raise NotImplementedError()


@dataclass
class BuiltinType(Type):
    """Builtin type."""
    py_type: type

    def __contains__(self, value: object) -> bool:
        return isinstance(value, self.py_type)

    def __str__(self) -> str:
        return self.py_type.__name__


@dataclass
class LangType(Type):
    """Language type."""
    lang: Lang

    def __contains__(self, value: object) -> bool:
        raise NotImplementedError

    def __str__(self) -> str:
        return f'lang({self.lang})'


@dataclass
class RefinedType(Type):
    """Refinement type."""
    base: Type
    predicate: Callable[[object], bool]

    def __contains__(self, value: object) -> bool:
        return value in self.base and self.predicate(value)

    def __str__(self) -> str:
        return f'refine({self.base}, ...)'


@dataclass
class LitType(Type):
    """Literal type."""
    values: Sequence[object]

    def __contains__(self, value: object) -> bool:
        return value in self.values

    def __str__(self) -> str:
        return f'Literal[{", ".join(repr(v) for v in self.values)}]'


@dataclass
class UnionType(Type):
    """Union type."""
    options: Sequence[Type]

    def __contains__(self, value: object) -> bool:
        return any(value in t for t in self.options)

    def __str__(self) -> str:
        return ' | '.join(str(t) for t in self.options)


@dataclass
class TupleType(Type):
    """Tuple type."""
    elements: Sequence[Type]
    variants: bool

    def __contains__(self, value: object) -> bool:
        if isinstance(value, tuple) and len(value) >= len(self.elements):
            if not self.variants and len(value) != len(self.elements):
                return False

            return all(v in t for v, t in zip(value, self.elements))

        return False

    def __str__(self) -> str:
        prefix = ', '.join(str(t) for t in self.elements)
        suffix = ', ...' if self.variants else ''
        return f'tuple[{prefix}{suffix}]'


@dataclass
class ListType(Type):
    """List type."""
    element_type: Type

    def __contains__(self, value: object) -> bool:
        if isinstance(value, list):
            return all(v in self.element_type for v in value)

        return False

    def __str__(self) -> str:
        return f'list[{self.element_type}]'


@dataclass
class SetType(Type):
    """Set type."""
    elem_type: Type

    def __contains__(self, value: object) -> bool:
        if not isinstance(value, set):
            return False
        return all(v in self.elem_type for v in value)

    def __str__(self) -> str:
        return f'set[{self.elem_type}]'


@dataclass
class DictType(Type):
    """Dictionary type."""
    key_type: Type
    value_type: Type

    def __contains__(self, value: object) -> bool:
        if not isinstance(value, dict):
            return False
        return all(k in self.key_type and v in self.value_type for k, v in value.items())

    def __str__(self) -> str:
        return f'dict[{self.key_type}, {self.value_type}]'


## Checks ##

SOURCE = '__source__'
LINENO = '__lineno__'


def check_arg_type(actual: object, expected: Type,
                   position: int | None, keyword: str | None, default_range: Range | None) -> None:
    """Check the type of function argument."""
    if actual not in expected:
        print("-- Runtime Type Error: type mismatch", file=sys.stderr)

        frame = inspect.currentframe()
        assert frame is not None
        frame = frame.f_back  # f = caller of this checker
        assert frame is not None
        fun_source = frame.f_globals[SOURCE]

        frame = frame.f_back  # caller of f
        assert frame is not None
        source = frame.f_globals[SOURCE]
        call = locate_call_in_source(frame)
        assert isinstance(call, ast.Call)

        match locate_arg(call, position, keyword):
            case None:
                assert default_range is not None
                print_details(fun_source, default_range,
                              [f"default value does not match expected type {expected}"])
            case arg:
                print_details(source, get_range(arg),
                              [f"expected type: {expected}", f"actual value:  {repr(actual)}"])
        print_tb(frame)


def locate_call_in_source(frame: FrameType) -> ast.Call:
    """Locate the last executed call of this frame in the corresponding source file."""
    # Ref: traceback._get_code_position
    assert frame.f_lasti >= 0
    positions_gen = frame.f_code.co_positions()
    x1, x2, y1, y2 = next(itertools.islice(positions_gen, frame.f_lasti // 2, None))

    # Extract code
    assert x1 is not None
    assert x2 is not None
    assert y1 is not None
    assert y2 is not None
    code = ''
    for lineno in range(x1, x2 + 1):
        line = linecache.getline(frame.f_code.co_filename, lineno)
        start = y1 if lineno == x1 else 0
        end = y2 if lineno == x2 else len(line)
        code += line[start:end]

    # Locate in source AST
    source = frame.f_globals[SOURCE]
    with open(source) as f:
        source_code = f.read()
    tree = ast.parse(source_code)
    lineno = frame.f_locals[LINENO]
    locator = CallLocator(lineno, code)
    locator.visit(tree)
    assert locator.result is not None, f"Could not locate '{code}' in {source}"
    return locator.result


class CallLocator(ast.NodeVisitor):
    def __init__(self, lineno: int, call_code: str) -> None:
        super().__init__()
        self.lineno = lineno
        self.call_code = call_code
        self.result: ast.Call | None = None

    def visit_Call(self, node: ast.Call) -> None:
        assert hasattr(node, 'lineno')
        lineno: int = getattr(node, 'lineno')
        end_lineno: int = getattr(node, 'end_lineno', lineno)
        if lineno <= self.lineno <= end_lineno:
            if ast.unparse(node) == self.call_code:
                self.result = node
                return

            self.generic_visit(node)


def locate_arg(call: ast.Call, position: int | None, keyword: str | None) -> ast.expr | None:
    if position is not None and position < len(call.args):  # this is a positional argument
        return call.args[position]

    if keyword is not None:
        for kw in call.keywords:
            if kw.arg == keyword:  # this is a keyword argument
                return kw.value

    return None


def check_pre(cond: bool, cond_range: Range) -> None:
    """Check precondition."""
    if not cond:
        print("-- Runtime Type Error: precondition violated", file=sys.stderr)

        frame = inspect.currentframe()
        assert frame is not None
        frame = frame.f_back  # f = caller of this checker
        assert frame is not None
        cond_source = frame.f_globals[SOURCE]

        frame = frame.f_back  # caller of f
        assert frame is not None
        source = frame.f_globals[SOURCE]
        call = locate_call_in_source(frame)

        call_range = get_range(call)
        if source == cond_source:
            width = max(len(str(call_range.end_lineno)), len(str(cond_range.end_lineno)))
            print_details(source, call_range, [], width=width)
            print_details(cond_source, cond_range, ["note: precondition is defined here"], width=width,
                          show_file_path=False)
        else:
            print_details(source, call_range, [])
            print("note: precondition is defined here", file=sys.stderr)
            print_details(cond_source, cond_range, [])

        print_tb(frame)


def check_type(actual: object, expected: Type, actual_range: Range) -> None:
    """Check the type of value."""
    if actual not in expected:
        print("-- Runtime Type Error: type mismatch", file=sys.stderr)

        frame = inspect.currentframe()
        assert frame is not None
        frame = frame.f_back  # f = caller of this checker
        assert frame is not None
        source = frame.f_globals[SOURCE]
        print_details(source, actual_range,
                      [f"expected type: {expected}", f"actual value:  {repr(actual)}"])

        frame = frame.f_back  # caller of f
        assert frame is not None
        print_tb(frame)


def check_post(cond: bool, cond_range: Range, return_range: Range) -> None:
    """Check postcondition."""
    if not cond:
        print("-- Runtime Type Error: postcondition violated", file=sys.stderr)

        frame = inspect.currentframe()
        assert frame is not None
        frame = frame.f_back  # f = caller of this checker
        assert frame is not None
        source = frame.f_globals[SOURCE]
        width = max(len(str(return_range.end_lineno)), len(str(return_range.end_lineno)))
        print_details(source, return_range, [], width=width)
        print_details(source, cond_range, ["note: postcondition is defined here"], width=width,
                      show_file_path=False)

        frame = frame.f_back  # caller of f
        assert frame is not None
        print_tb(frame)


def print_tb(frame: FrameType) -> None:
    print('Traceback (most recent call first):', file=sys.stderr)
    for f, _ in traceback.walk_stack(frame):
        source = f.f_globals.get(SOURCE)
        lineno = f.f_locals.get(LINENO)
        print(f'  File "{source}", line {lineno}, in {f.f_code.co_name}', file=sys.stderr)
        tb = TracebackType(None, f, f.f_lasti, f.f_lineno)
        extracted = traceback.extract_tb(tb)
        for line in traceback.format_list(extracted)[0].splitlines(keepends=True)[1:]:
            print(line, end='', file=sys.stderr)
    print('', file=sys.stderr)
