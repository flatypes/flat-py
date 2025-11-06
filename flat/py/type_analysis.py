import ast

from flat.py.ast_helpers import *
from flat.py.type_trees import *

b_type_items: set[str] = {'str', 'bool', 'int', 'float', 'complex', 'bytes'}
type_items: set[str] = b_type_items | {'typing.Any'}

b_constr_items: set[str] = {'tuple', 'list', 'set', 'dict'}

class TypeAnalyzer(ast.NodeVisitor):
    def __init__(self, imports: dict[str, str], aliases: dict[str, Type]) -> None:
        self._imports = imports
        self._aliases = aliases

    def visit_Constant(self, node: ast.Constant) -> Type:
        if node.value is None:
            return none_type
        
        raise TypeError("Invalid type.")
    
    def visit_Name(self, node: ast.Name) -> Type:
        match self._lookup(node.id):
            case Type():
                return TypeName(node.id)
            case str() as item:
                if item in type_items:
                    return TypeName(node.id)
                else:
                    raise TypeError(f"Type constructor '{node.id}' ({item}) requires arguments.")
            case None:  # Undefined name
                raise NameError(f"Name '{node.id}' is not defined.")
    
    def _lookup(self, name: str) -> Type | str | None:
        if name in self._aliases:
            return self._aliases[name]
                
        if name in self._imports:
            return self._imports[name]

        if name in (b_type_items | b_constr_items):
            return name
        
        return None

    def visit_Call(self, node: ast.Call) -> Type:
        match node.func:
            case ast.Name(name):
                match self._lookup(name):
                    case 'flat.py.lang':
                        [grammar, tag] = check_args(node, ['grammar'], [('tag', ast.Constant(''))])
                        return self._check_lang(grammar, tag)
                    case 'flat.py.refine':
                        [base, predicate] = check_args(node, ['base', 'predicate'])
                        return self._check_refine(base, predicate)

        raise TypeError(f"Invalid type.")

    def _check_lang(self, grammar: ast.expr, tag: ast.expr) -> Type:
        raise NotImplementedError

    def _check_refine(self, base: ast.expr, predicate: ast.expr) -> Type:
        t = self.visit(base)
        match predicate:
            case ast.Constant(str() as code):
                p = mk_lambda(['_'], ast.parse(code, mode='eval').body)
            case p:
                pass
        return RefinedType(t, p)

    def visit_Subscript(self, node: ast.Subscript) -> Type:
        match node.value:
            case ast.Name(name):
                match self._lookup(name):
                    case str() as item:
                        if item not in type_items:
                            return self._check_apply(item, get_type_args(node))
                        else:
                            raise TypeError(f"Type '{name}' ({item}) does not take arguments.")
                    case Type() as t:
                        raise TypeError(f"Type '{name}' ({t}) does not take arguments.")
                    
        return AnyType()

    def visit_BinOp(self, node: ast.BinOp) -> Type:
        if isinstance(node.op, ast.BitOr):
            args = get_operands(node, ast.BitOr)
            return self._check_apply('typing.Union', args)
            
        raise TypeError("Invalid type expression.")

    def _check_apply(self, constr_item: str, args: list[ast.expr]) -> Type:
        match constr_item:
            case 'tuple':
                if len(args) < 2:
                    raise TypeError("tuple[...] expects at least 2 arguments.")
                
                return TupleType([self.visit(arg) for arg in args])
            
            case 'list':
                match args:
                    case [arg]:
                        return ListType(self.visit(arg))
                    case _:
                        raise TypeError("list[...] expects exactly 1 argument.")
                    
            case 'set':
                match args:
                    case [arg]:
                        return SetType(self.visit(arg))
                    case _:
                        raise TypeError("set[...] expects exactly 1 argument.")
                    
            case 'dict':
                match args:
                    case [arg_key, arg_value]:
                        return DictType(self.visit(arg_key), self.visit(arg_value))
                    case _:
                        raise TypeError("dict[...] expects exactly 2 arguments.")
                    
            case 'typing.Literal':
                values: list[LiteralValue] = []
                options: list[Type] = []
                for arg in args:
                    match self._analyze_literal(arg):
                        case Type() as t:
                            options.append(t)
                        case v:
                            values.append(v)

                lt = LiteralType(values)
                if len(options) == 0:
                    return lt
                if len(values) == 0:
                    return UnionType(options)
                return UnionType([lt, *options])

            case 'typing.Union':
                if len(args) < 2:
                    raise TypeError("typing.Union[...] expects at least 2 arguments.")
                
                return UnionType([self.visit(e) for e in args])

            case 'typing.Optional':
                match args:
                    case [arg]:
                        return UnionType([self.visit(arg), none_type])
                    case _:
                        raise TypeError("typing.Optional[...] expects exactly 1 argument.")

            case _:
                raise TypeError(f"Unknown type constructor '{constr_item}'.")


    def _analyze_literal(self, value: ast.expr) -> LiteralValue | Type:
        match value:
            case ast.Constant(v):
                return v
            case ast.UnaryOp(ast.USub(), ast.Constant(v)) if isinstance(v, (int, float, complex)):
                return -v
        
        match self.visit(value):
            case LiteralType() as t:
                return t
            case TypeName(name) as t if name in self._aliases and isinstance(self._aliases[name], LiteralType):
                return t
            case _:
                raise TypeError(f"Invalid Literal value: {value}.")

    def generic_visit(self, node: ast.AST) -> Type:
        raise TypeError("Invalid type.")