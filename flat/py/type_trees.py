import ast
from dataclasses import dataclass

from flat.py.ast_helpers import mk_call_runtime, mk_name

class Type:
    """Type tree (at source level)."""
    @property
    def ast(self) -> ast.expr:
        """The AST representation of this type."""
        raise NotImplementedError()

@dataclass
class AnyType(Type):
    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('AnyType')
    
@dataclass
class TypeName(Type):
    name: str

    @property
    def ast(self) -> ast.expr:
        return mk_name(self.name)

@dataclass
class LangType(Type):
    grammar: str
    name: str

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('LangType', ast.Name(self.grammar, ctx = ast.Load()), ast.Constant(self.name))

@dataclass
class RefinedType(Type):
    base: Type
    predicate: ast.expr

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('RefinedType', self.base.ast, self.predicate)

type LiteralValue = ast._ConstantValue

@dataclass
class LiteralType(Type):
    values: list[LiteralValue]

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('LiteralType', ast.List([ast.Constant(v) for v in self.values], ctx=ast.Load()))

none_type = LiteralType([None])

@dataclass
class UnionType(Type):
    options: list[Type]

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('UnionType', ast.List([t.ast for t in self.options], ctx=ast.Load()))

@dataclass
class TupleType(Type):
    elements: list[Type]

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('TupleType', ast.List([t.ast for t in self.elements], ctx=ast.Load()))
    
@dataclass
class ListType(Type):
    element: Type

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('ListType', self.element.ast)
    
@dataclass
class SetType(Type):
    element: Type

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('SetType', self.element.ast)
    
@dataclass
class DictType(Type):
    key: Type
    value: Type

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('DictType', self.key.ast, self.value.ast)
