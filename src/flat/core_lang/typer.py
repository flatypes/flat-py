from traceback import FrameSummary

from flat.core_lang.ast import *
from flat.core_lang.cond import CoreCond
from flat.core_lang.types import *
from flat.errors import Undefined
from flat.grammars import GrammarBuilder
from flat.typing import *


class Typer(GrammarBuilder):
    def __init__(self, filename: str):
        super().__init__()
        self.filename = filename
        self._grammars: dict[str, Grammar] = {}

    def lookup_lang(self, name: str) -> Optional[Grammar]:
        return self._grammars.get(name)

    def frame_from_pos(self, pos: Pos) -> FrameSummary:
        return FrameSummary(self.filename, pos.start[0] + 1, '<file>', end_lineno=pos.end[0] + 1,
                            colno=pos.start[1], end_colno=pos.end[1] + 1)

    def check_and_define_lang(self, tree: LangDef) -> None:
        if tree.name in self._grammars:
            raise NameError("lang already defined")

        self._grammars[tree.name] = self(tree.name, tree.rules)

    def get_types(self) -> dict[str, LangType]:
        return dict((x, LangType(self._grammars[x])) for x in self._grammars)

    def expand(self, tree: TypeTree) -> Type:
        match tree:
            case NamedTypeTree(Ident('Int')):
                return BuiltinType.Int
            case NamedTypeTree(Ident('Bool')):
                return BuiltinType.Bool
            case NamedTypeTree(Ident('String')):
                return BuiltinType.String
            case NamedTypeTree(Ident(name, pos)):
                if name not in self._grammars:
                    raise Undefined('lang', name, self.frame_from_pos(pos))
                return LangType(self._grammars[name])
            case RefinementTypeTree(base, refinement):
                match self.expand(base):
                    case BaseType() as b:
                        self.ensure_bool(refinement, {'_': b})
                        return RefinementType(b, CoreCond(refinement))
                    case _:
                        raise TypeError
            case FunTypeTree(args, returns):
                return FunType([self.expand(tree) for tree in args], self.expand(returns))
            case other:
                raise NotImplementedError(str(other))

    def ensure(self, expr: Expr, typ: Type, ctx: dict[str, Type]) -> None:
        pass

    def ensure_bool(self, expr: Expr, ctx: dict[str, Type]) -> None:
        pass
