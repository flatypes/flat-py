import ast

from flat.py.semantics import *
from flat.py.ast_helpers import *

b_type_items: set[str] = {'str', 'bool', 'int', 'float', 'complex', 'bytes'}
type_items: set[str] = b_type_items | {'typing.Any'}

b_constr_items: set[str] = {'tuple', 'list', 'set', 'dict'}

def analyze_type(node: ast.expr, ctx: Context) -> Type:
    analyzer = TypeAnalyzer(ctx)
    return analyzer.visit(node)

class TypeAnalyzer(ast.NodeVisitor):
    ctx: Context

    def __init__(self, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx

    def visit_Constant(self, node: ast.Constant) -> Type:
        if node.value is None:
            return none_type
        else:
            self.ctx.error("Invalid type: try using typing.Literal[...] instead?", node)
            return AnyType()
    
    def visit_Name(self, node: ast.Name) -> Type:
        match self.ctx.lookup(node.id):
            case None if node.id in b_type_items:
                return TypeName(node.id)
            case None if node.id in b_constr_items:
                return self._check_type_call_nil(node.id, node)
            case None:
                self.ctx.error(f"Unknown type '{node.id}'", node)
                return AnyType()
            case VarDef() | FunDef():
                self.ctx.error(f"'{node.id}' is not a type", node)
                return AnyType()
            case TypeDef(t):
                return t
            case TypeConstrDef(id):
                return self._check_type_call_nil(id, node)
            case _:
                return AnyType()
                
    def _check_type_call_nil(self, fun_id: str, fun_node: ast.expr) -> Type:
        match fun_id:
            case 'tuple':
                return TupleType([AnyType()], variant=True)
            case 'list':
                return ListType(AnyType())
            case 'set':
                return SetType(AnyType())
            case 'dict':
                return DictType(AnyType(), AnyType())
            case 'typing.Literal':
                self.ctx.error("typing.Literal[...] must have at least one parameter", fun_node)
                return AnyType()
            case 'typing.Union':
                # NOTE: mypy interprets this as a bottom type
                self.ctx.error("typing.Union[...] must have at least two arguments", fun_node)
                return AnyType()
            case 'typing.Optional':
                self.ctx.error("typing.Optional[...] must have exactly one argument", fun_node)
                return AnyType()
            case _:
                raise NameError(f"Unknown type constructor '{fun_id}'.")

    def visit_Call(self, node: ast.Call) -> Type:
        match node.func:
            case ast.Name(f):
                match self.ctx.lookup(f):
                    case None:
                        self.ctx.error(f"Unknown type constructor '{f}'", node)
                        return AnyType()
                    case TypeConstrDef(id):
                        return self._check_type_call_paren(id, node.func, node.args)

        self.ctx.error("Invalid type", node)
        return AnyType()
    
    def _check_type_call_paren(self, fun_id: str, fun_node: ast.expr, args: list[ast.expr]) -> Type:
        raise NotImplementedError

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
            case ast.Name(f):
                match self.ctx.lookup(f):
                    case None:
                        if f in b_constr_items:
                            return self._check_type_call_bracket(f, node.value, get_type_args(node))
                        else:
                            self.ctx.error(f"Name '{f}' is not defined", node.value)
                            return AnyType()
                    case TypeConstrDef(id):
                        return self._check_type_call_bracket(id, node.value, get_type_args(node))
                    case Type():
                        self.ctx.error(f"Type '{f}' expects no type arguments", node.value)
                        return AnyType()

        self.ctx.error("Invalid type", node)
        return AnyType()
    
    def _check_type_call_bracket(self, fun_id: str, fun_node: ast.expr, args: list[ast.expr]) -> Type:
        match fun_id, args:
            case 'tuple', _:
                # TODO: variant
                return TupleType([self.visit(arg) for arg in args])
            case 'list', [arg]:
                return ListType(self.visit(arg))
            case 'list', _:
                self.ctx.error("list[...] must have exactly 1 argument", fun_node)
                return AnyType()
            case 'set', [arg]:
                return SetType(self.visit(arg))
            case 'set', _:
                self.ctx.error("set[...] must have exactly 1 argument", fun_node)
                return AnyType()
            case 'dict', [key_arg, value_arg]:
                return DictType(self.visit(key_arg), self.visit(value_arg))
            case 'dict', _:
                self.ctx.error("dict[...] must have exactly 2 arguments", fun_node)
                return AnyType()
            case 'typing.Literal', _:
                return self._check_literal_type(args)
            case 'typing.Union', _:
                return UnionType([self.visit(e) for e in args])
            case 'typing.Optional', [arg]:
                return UnionType([self.visit(arg), none_type])
            case 'typing.Optional', _:  
                self.ctx.error("typing.Optional[...] must have exactly 1 argument", fun_node)
                return AnyType()
            case _:
                raise NameError(f"Unknown type constructor '{fun_id}'.")

    def _check_literal_type(self, args: list[ast.expr]) -> Type:
        values: list[LiteralValue] = []
        for arg in args:
            match arg:
                case ast.Constant(v):
                    values.append(v)
                case ast.UnaryOp(ast.USub(), ast.Constant(v)) if isinstance(v, (int, float, complex)):
                    values.append(-v)
                case _:
                    match self.visit(arg):
                        case LiteralType(vs):
                            values += vs
                        case _:
                            self.ctx.error(f"Parameter of typing.Literal is invalid", arg)

        return LiteralType(values)

    def visit_BinOp(self, node: ast.BinOp) -> Type:
        if isinstance(node.op, ast.BitOr):
            args = get_operands(node, ast.BitOr)
            return self._check_type_call_bracket('typing.Union', node, args)
            
        self.ctx.error("Invalid type", node)
        return AnyType()

    def generic_visit(self, node: ast.AST) -> Type:
        assert isinstance(node, ast.expr)
        self.ctx.error("Invalid type", node)
        return AnyType()
