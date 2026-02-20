import ast
import importlib.util
import inspect
import sys
import time
from types import TracebackType
from typing import Any, Callable, Generator, Optional, get_args

from isla.solver import ISLaSolver

from flat.py import FuzzReport
from flat.py.errors import *
from flat.py.isla_extensions import *
from flat.typing import Type, value_has_type, LangType, ListType


def load_source_module(path: str) -> None:
    spec = importlib.util.spec_from_file_location('_.source', path)
    source_module = importlib.util.module_from_spec(spec)
    sys.modules['_.source'] = source_module
    spec.loader.exec_module(source_module)


def has_type(obj: Any, expected: Any) -> bool:
    if isinstance(expected, Type):
        match obj:
            case (int() | bool() | str()) as v:
                return value_has_type(v, expected)
            case list() as xs:
                match expected:
                    case ListType(t):
                        return all(has_type(x, t) for x in xs)
                    case _:
                        return False
            case _:
                raise RuntimeError(f'cannot check type for object {obj} with type {type(obj)}')
    else:  # Literal
        values = get_args(expected)
        return obj in values


def assert_type(value: Any, value_loc: Loc, expected_type: Type):
    if not has_type(value, expected_type):
        raise TypeMismatch(str(expected_type), show_value(value), value_loc)


def assert_arg_type(value: Any, k: int, of_method: str, expected_type: Type):
    if not has_type(value, expected_type):
        raise ArgTypeMismatch(str(expected_type), show_value(value), k, of_method)


def assert_pre(cond: bool, args: list[Tuple[str, Any]], of_method: str):
    if not cond:
        raise PreconditionViolated(of_method, [(name, show_value(v)) for name, v in args])


def assert_post(cond: bool, args: list[Tuple[str, Any]], return_value: Any, return_value_loc: Loc, of_method: str):
    if not cond:
        raise PostconditionViolated(of_method, [(name, show_value(v)) for name, v in args],
                                    show_value(return_value), return_value_loc)


class ExpectExceptions:
    def __init__(self, exc_info: list[Tuple[bool, type[BaseException], Loc]]) -> None:
        """Expect a specified type of exception if its condition is held.
        Assuming the conditions are disjoint."""
        self.expected_type: Optional[type] = None
        self.loc: Optional[Loc] = None

        for b, exc_type, loc in exc_info:
            if b:
                self.expected_type = exc_type
                self.loc = loc
                break

    def __enter__(self) -> Any:
        return self

    def __exit__(self, exc_type: type, exc_value: BaseException, tb: TracebackType) -> bool:
        if self.expected_type is not None:
            if exc_type is self.expected_type:
                return True  # success, ignore exc
            # failure: raise another error
            raise NoExpectedException(self.expected_type, self.loc)

        # no expected error: handle normally
        return False


def show_value(value: Any):
    match value:
        case str() as s:
            return ast.unparse(ast.Constant(s))
        case _:
            return str(value)


Gen = Generator[Any, None, None]


def constant_generator(value: Any) -> Gen:
    while True:
        yield value


def choice_generator(choices: list[Any]) -> Gen:
    for value in choices:
        yield value


def isla_generator(typ: LangType, formula: Optional[str] = None) -> Gen:
    assert typ is not None
    volume = 10
    solver = ISLaSolver(typ.grammar.isla_solver.grammar, formula,
                        structural_predicates={EBNF_DIRECT_CHILD, EBNF_KTH_CHILD},
                        max_number_free_instantiations=volume)
    while True:
        try:
            yield solver.solve().to_string()
        except StopIteration:
            volume *= 2
            solver = ISLaSolver(typ.grammar.isla_solver.grammar, formula,
                                structural_predicates={EBNF_DIRECT_CHILD, EBNF_KTH_CHILD},
                                max_number_free_instantiations=volume)


def producer(generator: Gen, test: Callable[[Any], bool]) -> Gen:
    while True:
        try:
            value = next(generator)
        except StopIteration:
            break
        if test(value):
            yield value


def product_producer(producers: list[Gen], test: Callable[[Any], bool]) -> Gen:
    while True:
        try:
            values = [next(p) for p in producers]
        except StopIteration:
            break
        if test(*values):
            yield values


def fuzz(target: Callable, times: int, args_producer: Gen, verbose: bool = False) -> FuzzReport:
    # copy __source__, __line__ from the last frame
    frame = inspect.currentframe()
    back_frame = frame.f_back
    if '__line__' in back_frame.f_locals:
        frame.f_locals['__line__'] = back_frame.f_locals['__line__']
        frame.f_globals['__source__'] = back_frame.f_globals['__source__']

    producer_time = 0.0
    exe_time = 0.0
    records = []
    for i in range(times):
        try:
            t = time.process_time()
            inputs = next(args_producer)
            producer_time += (time.process_time() - t)
        except StopIteration:
            break

        t = time.process_time()
        try:
            target(*inputs)
        except Error as err:
            exe_time += (time.process_time() - t)
            records.append((tuple(inputs), 'Error'))
            # cprint(f'[Error] {target.__name__}{tuple(inputs)}', 'red')
            # err.print()
        except Exception as exc:
            exe_time += (time.process_time() - t)
            records.append((tuple(inputs), 'Error'))
            # cprint(f'[Error] {target.__name__}{tuple(inputs)}', 'red')
            # cprint('{}: {}'.format(type(exc).__name__, exc), 'red')
        except SystemExit:
            exe_time += (time.process_time() - t)
            records.append((tuple(inputs), 'Exited'))
            # cprint(f'[Exited] {target.__name__}{tuple(inputs)}', 'red')
        else:
            exe_time += (time.process_time() - t)
            records.append((tuple(inputs), 'OK'))
            # if verbose:
            #     cprint(f'[OK] {target.__name__}{tuple(inputs)}', 'green')

    # print(f'{target.__name__}: {passed[target.__name__]}/{times} passed, {total_time[target.__name__]} ms')
    return FuzzReport(target.__name__, records, producer_time, exe_time)


def run_main(main: Callable) -> None:
    try:
        main()
    except Error as err:
        err.print()
