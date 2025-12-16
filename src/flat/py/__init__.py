from typing import Any, Callable, Literal

type LangSyntax = Literal['ebnf', 'regex']


def lang(grammar: str, /, *, syntax: LangSyntax = 'ebnf', name: str | None = None) -> type[str]:
    """Create a formal language type."""
    return str


def refine(base_type: type, condition: str, /, *conditions: str) -> type:
    """Create a refinement type."""
    return base_type


def requires(*conditions: str) -> Callable[..., Any]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        return func

    return decorator


def ensures(*conditions: str) -> Callable[..., Any]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        return func

    return decorator


def returns(value: str) -> Callable[..., Any]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        return func

    return decorator
