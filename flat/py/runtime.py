import ast
import importlib.util
import inspect
import sys
import time
from types import TracebackType
from typing import Callable, Generator, Optional

from isla.solver import ISLaSolver

from flat.py import FuzzReport
from flat.py.errors import *
from flat.py.isla_extensions import *
from flat.typing import *


def load_source_module(path: str) -> None:
    spec = importlib.util.spec_from_file_location('_.source', path)
    source_module = importlib.util.module_from_spec(spec)
    sys.modules['_.source'] = source_module
    spec.loader.exec_module(source_module)


def has_type(obj: Any, expected: Type) -> bool:
    """Check if the object has the expected type."""
    match expected:
        case BuiltinType.Int:
            return not isinstance(obj, bool) and isinstance(obj, int)
        case BuiltinType.Bool:
            return isinstance(obj, bool)
        case BuiltinType.String:
            return isinstance(obj, str)
        case LangType(g):
            assert isinstance(g, CFG)
            return isinstance(obj, str) and obj in g
        case ListType(t):
            return isinstance(obj, list) and all(has_type(x, t) for x in obj)
        case TupleType(ts):
            return isinstance(obj, tuple) and len(obj) == len(ts) and all(
                has_type(x, t) for x, t in zip(obj, ts))
        case RecordType(k, ts):
            return isinstance(obj, k) and all(
                hasattr(obj, x) and has_type(getattr(obj, x), t) for x, t in ts.items())
        case RefinedType(t, p):
            assert isinstance(p, Callable), f"refinement '{p}' is not callable"
            return has_type(obj, t) and p(obj)
        case _:
            raise RuntimeError(f"cannot check type for '{obj}' of type {type(obj)}"
                               f"(expected {expected})")


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
    solver = ISLaSolver(typ.grammar.parser.grammar, formula,
                        structural_predicates={EBNF_DIRECT_CHILD, EBNF_KTH_CHILD},
                        max_number_free_instantiations=volume)
    while True:
        try:
            yield solver.solve().to_string()
        except StopIteration:
            volume *= 2
            solver = ISLaSolver(typ.grammar.parser.grammar, formula,
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


# Producers

class Producer:
    def produce(self) -> Any:
        """Produce a value."""
        raise NotImplementedError("Subclasses must implement produce method.")


@dataclass
class ConstProducer(Producer):
    value: Any

    def produce(self) -> Any:
        return self.value


@dataclass
class ISLaProducer(Producer):
    grammar: CFG
    formula: Optional[str] = None

    def __post_init__(self) -> None:
        self.volume = 10
        self.solver = ISLaSolver(self.grammar.rules, self.formula,
                                 structural_predicates={EBNF_DIRECT_CHILD, EBNF_KTH_CHILD},
                                 max_number_free_instantiations=self.volume)

    def produce(self) -> str:
        while True:
            try:
                return self.solver.solve().to_string()
            except StopIteration:
                self.volume *= 2
                self.solver = ISLaSolver(self.grammar.rules, self.formula,
                                         structural_predicates={EBNF_DIRECT_CHILD, EBNF_KTH_CHILD},
                                         max_number_free_instantiations=self.volume)


@dataclass
class ListProducer(Producer):
    elem: Producer

    def produce(self) -> list:
        # TODO: implement list producer
        return []


@dataclass
class TupleProducer(Producer):
    elems: list[Producer]

    def produce(self) -> tuple:
        return tuple(elem.produce() for elem in self.elems)


@dataclass
class RecordProducer(Producer):
    constr: Callable[..., Any]
    fields: list[Producer]

    def produce(self) -> Any:
        args = [field.produce() for field in self.fields]
        return self.constr(*args)


@dataclass
class FilterProducer(Producer):
    base: Producer
    pred: Callable[[Any], bool]

    def produce(self) -> Any:
        while True:
            value = self.base.produce()
            if self.pred(value):
                return value


def fuzz_test(target: Callable, times: int, args_producer: TupleProducer) -> FuzzReport:
    """Run a fuzz test on the target function with the specified number of times."""
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
            inputs = args_producer.produce()
            producer_time += (time.process_time() - t)
        except StopIteration:
            break

        t = time.process_time()
        try:
            target(*inputs)
        except Error as err:
            exe_time += (time.process_time() - t)
            records.append((inputs, 'Error'))
            err.print()
        except Exception as exc:
            exe_time += (time.process_time() - t)
            records.append((inputs, 'Error'))
            print('{}: {}'.format(type(exc).__name__, exc))
        except SystemExit:
            exe_time += (time.process_time() - t)
            records.append((inputs, 'Exited'))
        else:
            exe_time += (time.process_time() - t)
            records.append((inputs, 'OK'))
            # if verbose:
            #     cprint(f'[OK] {target.__name__}{tuple(inputs)}', 'green')

    # print(f'{target.__name__}: {passed[target.__name__]}/{times} passed, {total_time[target.__name__]} ms')
    return FuzzReport(target.__name__, records, producer_time, exe_time)
