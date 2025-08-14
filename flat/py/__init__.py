import ast
import inspect
from typing import Callable, Tuple, Literal

import flat.parser
from flat.py.ast_factory import parse_expr
from flat.types import *
from flat.typing import *


class LangBuilder(CFGBuilder):
    def lookup_lang(self, name: str) -> Optional[CFG]:
        match name:
            case 'RFC_Email':
                return RFC_Email.grammar
            case 'RFC_URL':
                return RFC_URL.grammar
            case 'Host':
                return Host.grammar
            case 'URL':
                return URL.grammar
            case _:
                try:
                    value = eval(name)
                except NameError:
                    return None

                match value:
                    case LangType(g):
                        return g
                    case _:
                        return None


def lang(name: str, rules: str) -> LangType:
    builder = LangBuilder()
    grammar = builder(name, parse_using(flat.parser.rules, rules, '<file>', (1, 1)))
    return LangType(grammar)


def refine(base: type | Type, refinement: Any) -> RefinedType:
    match base:
        case type() as ty:
            if ty is int:
                t = BuiltinType.Int
            elif ty is bool:
                t = BuiltinType.Bool
            elif ty is str:
                t = BuiltinType.String
            else:
                raise TypeError("expect a FLAT Type")
        case Type() as ty:
            t = ty
        case _:
            raise TypeError("expect a FLAT Type")
    match refinement:
        case str() as s:
            e = parse_expr(s)
            # lambda _: e
            p = ast.Lambda(ast.arguments([], [ast.arg('_')], None, [], [], None, []), e)
        case Callable() as f:
            source = inspect.getsource(f)
            match parse_expr(source):
                case ast.Call(_, [ast.Lambda() as lam]):
                    p = lam
                case _:
                    raise SyntaxError(f"Expected a lambda expression as the refinement")

    return RefinedType(t, p)


@DeprecationWarning
def list_of(elem_type: Type) -> ListType:
    return ListType(elem_type)


def requires(condition: Any):
    def decorate(func):
        def decorated(*args, **kwargs):
            return func(*args, **kwargs)  # identity

        return decorated

    return decorate


def ensures(condition: Any):
    def decorate(func):
        def decorated(*args, **kwargs):
            return func(*args, **kwargs)  # identity

        return decorated

    return decorate


def returns(value: Any):
    def decorate(func):
        def decorated(*args, **kwargs):
            return func(*args, **kwargs)  # identity

        return decorated

    return decorate


def raise_if(exc: type[BaseException], cond: Any):
    def decorate(func):
        def decorated(*args, **kwargs):
            return func(*args, **kwargs)  # identity

        return decorated

    return decorate


@dataclass(frozen=True)
class FuzzReport:
    target: str
    records: list[Tuple[Any, Literal['Error', 'Exited', 'OK']]]
    producer_time: float
    checker_time: float


def fuzz(target: Callable,
         times: int = 10, using: Optional[dict[str, Any]] = None) -> FuzzReport:
    raise NotImplementedError
