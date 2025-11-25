import ast

from flat.py.diagnostics import *
from flat.py.semantics import *
from flat.py.ast_helpers import *
from flat.lang.parsing import Format, supported_formats, parse
from flat.lang.translation import normalize

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
            self.ctx.issue(InvalidType(self.ctx.get_loc(node)))
            return AnyType()
    
    def visit_Name(self, node: ast.Name) -> Type:
        match self.ctx.lookup(node.id):
            case None:
                if node.id in b_type_items:
                    return TypeName(node.id)
                elif node.id in b_constr_items:
                    return self._check_type_call_nil(node.id, node)
                else:
                    self.ctx.issue(UndefinedName(node.id, self.ctx.get_loc(node)))
                    return AnyType()
            case VarDef() | FunDef():
                self.ctx.issue(InvalidType(self.ctx.get_loc(node)))
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
                self.ctx.issue(ArityMismatch(fun_id, 'at least 1', 0, self.ctx.get_loc(fun_node)))
                return AnyType()
            case 'typing.Union':
                # NOTE: mypy interprets this as a bottom type
                self.ctx.issue(ArityMismatch(fun_id, 'at least 2', 0, self.ctx.get_loc(fun_node)))
                return AnyType()
            case 'typing.Optional':
                self.ctx.issue(ArityMismatch(fun_id, '1', 0, self.ctx.get_loc(fun_node)))
                return AnyType()
            case _:
                raise NameError(f"Unknown type constructor '{fun_id}'.")

    def visit_Call(self, node: ast.Call) -> Type:
        match node.func:
            case ast.Name(f):
                match self.ctx.lookup(f):
                    case None:
                        self.ctx.issue(UndefinedName(f, self.ctx.get_loc(node.func)))
                        return AnyType()
                    case TypeConstrDef(id):
                        return self._check_type_call_paren(id, node.args, node.keywords, self.ctx.get_loc(node))

        self.ctx.issue(InvalidType(self.ctx.get_loc(node)))
        return AnyType()
    
    def _check_type_call_paren(self, fun_id: str, args: list[ast.expr], keywords: list[ast.keyword],
                               loc: Location) -> Type:
        match fun_id, args:
            case 'flat.py.lang', [arg]:
                match arg:
                    case ast.Constant(str() as s):
                        format = self._check_lang_keywords(keywords, loc)
                        lang = parse(s, format=format, file_path=loc.file_path)
                        norm_lang = normalize(lang, self.ctx.issuer, self.ctx.lang_finder)
                        return LangType(0)
                    case _:
                        self.ctx.issue(InvalidType(self.ctx.get_loc(arg)))
                        return AnyType()
                return AnyType()
            case 'flat.py.lang', _:
                self.ctx.issue(ArityMismatch('flat.py.lang', '1', len(args), loc))
                return AnyType()
            case 'flat.py.refine', [arg_t, arg_p]:
                t = self.visit(arg_t)
                match arg_p:
                    case ast.Constant(str() as code):
                        p = mk_lambda(['_'], ast.parse(code, mode='eval').body)
                    case p:
                        pass
                return RefinedType(t, p)
            case 'flat.py.refine', _:
                self.ctx.issue(ArityMismatch('flat.py.refine', '2', len(args), loc))
                return AnyType()
            case _:
                raise NameError(f"Unknown type constructor '{fun_id}'.")
    
    def _check_lang_keywords(self, keywords: list[ast.keyword], loc: Location) -> Format:
        format: Format | None = None
        for kw in keywords:
            if kw.arg == 'format':
                match kw.value:
                    case ast.Constant(str() as s) if s in supported_formats:
                        format = s # type: ignore
                    case _:
                        self.ctx.issue(InvalidFormat(self.ctx.get_loc(kw.value)))
                        format = 'ebnf'

        return format or 'ebnf'

    def visit_Subscript(self, node: ast.Subscript) -> Type:
        match node.value:
            case ast.Name(f):
                match self.ctx.lookup(f):
                    case None:
                        if f in b_constr_items:
                            return self._check_type_call_bracket(f, get_type_args(node), self.ctx.get_loc(node))
                        else:
                            self.ctx.issue(UndefinedName(f, self.ctx.get_loc(node.value)))
                            return AnyType()
                    case TypeConstrDef(id):
                        return self._check_type_call_bracket(id, get_type_args(node), self.ctx.get_loc(node))

        self.ctx.issue(InvalidType(self.ctx.get_loc(node)))
        return AnyType()
    
    def _check_type_call_bracket(self, fun_id: str, args: list[ast.expr], loc: Location) -> Type:
        match fun_id, args:
            case 'tuple', [*args, ast.Constant(v)] if v is ...:
                return TupleType([self.visit(arg) for arg in args], variant=True)
            case 'tuple', _:
                return TupleType([self.visit(arg) for arg in args])
            case 'list', [arg]:
                return ListType(self.visit(arg))
            case 'list', _:
                self.ctx.issue(ArityMismatch('list', '1', len(args), loc))
                return AnyType()
            case 'set', [arg]:
                return SetType(self.visit(arg))
            case 'set', _:
                self.ctx.issue(ArityMismatch('set', '1', len(args), loc))
                return AnyType()
            case 'dict', [key_arg, value_arg]:
                return DictType(self.visit(key_arg), self.visit(value_arg))
            case 'dict', _:
                self.ctx.issue(ArityMismatch('dict', '2', len(args), loc))
                return AnyType()
            case 'typing.Literal', _:
                return self._check_literal_type(args)
            case 'typing.Union', _:
                return UnionType([self.visit(e) for e in args])
            case 'typing.Optional', [arg]:
                return UnionType([self.visit(arg), none_type])
            case 'typing.Optional', _:  
                self.ctx.issue(ArityMismatch('typing.Optional', '1', len(args), loc))
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
                            self.ctx.issue(InvalidLiteral(self.ctx.get_loc(arg)))

        return LiteralType(values)

    def visit_BinOp(self, node: ast.BinOp) -> Type:
        if isinstance(node.op, ast.BitOr):
            args = get_operands(node, ast.BitOr)
            return self._check_type_call_bracket('typing.Union', args, self.ctx.get_loc(node))
        else:
            self.ctx.issue(InvalidType(self.ctx.get_loc(node)))
            return AnyType()

    def generic_visit(self, node: ast.AST) -> Type:
        self.ctx.issue(InvalidType(self.ctx.get_loc(node)))
        return AnyType()
