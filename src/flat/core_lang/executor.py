from importlib import import_module
from types import ModuleType
from typing import Any

from flat.core_lang.ast import *
from flat.core_lang.predef import *


def load(name: str) -> ast.Name:
    return ast.Name(name, ctx=ast.Load())


def store(name: str) -> ast.Name:
    return ast.Name(name, ctx=ast.Store())


def load_defs_to(m: ModuleType, env: dict[str, Any]) -> None:
    for key in m.__dict__:
        if not key.startswith('_'):
            env[key] = m.__dict__[key]


class Executor:
    def __init__(self, instrumented_program: Program, env: dict[str, Any]):
        body = [self.visit_def(tree) for tree in instrumented_program]
        tree = ast.Module(body, type_ignores=[])
        tree = ast.fix_missing_locations(tree)
        code = ast.unparse(tree)
        self.user_code = code
        # print(self.user_code)
        self.env = env

    def __call__(self, method_name: str = 'main') -> None:
        env = {}
        load_defs_to(import_module('flat.lib'), env)
        load_defs_to(import_module('flat.core_lang.predef'), env)
        env |= self.env
        exec(self.user_code + f'\n{method_name}()', env, env)

    def visit_def(self, tree: Def) -> ast.FunctionDef:
        match tree:
            case MethodDef(Ident(name), params, _, specs, body):
                assert specs == []
                args = ast.arguments([], [ast.arg(param_ident.name) for param_ident, _ in params],
                                     None, [], [], None, [])
                fun_body = [self.visit_stmt(s) for s in body]
                return ast.FunctionDef(name, args, fun_body,
                                       decorator_list=[], returns=None, type_comment=None)
            case _:
                raise NotImplementedError

    def visit_stmt(self, stmt: Stmt) -> ast.stmt:
        match stmt:
            case Declare():
                return ast.Pass()
            case Assign(Ident(name), value):
                rhs = self.visit_expr(value)
                return ast.Assign([store(name)], rhs, type_comment=None)
            case Call(Ident(name), args) as call:
                values = [self.visit_expr(e) for e in args]
                app = ast.Call(load(name), values, keywords=[])
                if call.var:
                    return ast.Assign([store(call.var.name)], app, type_comment=None)
                else:
                    return ast.Expr(app)
            case Assert(cond, err):
                test = self.visit_expr(cond)
                assert err is not None
                return ast.If(ast.UnaryOp(ast.Not(), test), [ast.Raise(load(err), cause=None)],
                              orelse=[])
            case Return(value):
                expr = self.visit_expr(value) if value else None
                return ast.Return(expr)
            case If(cond, then_body, else_body):
                test = self.visit_expr(cond)
                body = [self.visit_stmt(s) for s in then_body]
                orelse = [self.visit_stmt(s) for s in else_body]
                return ast.If(test, body, orelse)
            case While(cond, body):
                test = self.visit_expr(cond)
                loop_body = [self.visit_stmt(s) for s in body]
                return ast.While(test, loop_body, orelse=[])
            case _:
                raise NotImplementedError

    def visit_expr(self, expr: Expr) -> ast.expr:
        match expr:
            case Constant(Lit(value)):
                return ast.Constant(value)
            case Var(Ident(name)):
                return ast.Name(name, ctx=ast.Load())
            case App(fun, args):
                arguments = [self.visit_expr(e) for e in args]
                match fun:
                    case Var(Ident(fun_name)) if fun_name in ops:
                        return self.call_op(fun_name, arguments)
                    case _:
                        function = self.visit_expr(fun)
                        return ast.Call(function, arguments, keywords=[])
            case InLang(receiver, Ident(lang_name)):
                word = self.visit_expr(receiver)
                return ast.Compare(word, [ast.In()],
                                   [ast.Attribute(load(lang_name), 'grammar', ctx=ast.Load())])
            case Lambda(params, body):
                args = ast.arguments([], [ast.arg(param.name) for param in params], None, [], [], None, [])
                expr = self.visit_expr(body)
                return ast.Lambda(args, expr)
            case IfThenElse(cond, then_branch, else_branch):
                test = self.visit_expr(cond)
                body = self.visit_expr(then_branch)
                orelse = self.visit_expr(else_branch)
                return ast.IfExp(test, body, orelse)
            case _:
                raise NotImplementedError

    def call_op(self, fun_name: str, args: list[ast.expr]) -> ast.expr:
        if fun_name in unary_ops:
            op = py_unary_ops[unary_ops.index(fun_name)]
            assert len(args) == 1
            return ast.UnaryOp(op, args[0])

        if fun_name in binary_ops:
            op = py_binary_ops[binary_ops.index(fun_name)]
            assert len(args) == 2
            return ast.BinOp(args[0], op, args[1])

        if fun_name in bool_ops:
            op = py_bool_ops[bool_ops.index(fun_name)]
            assert len(args) == 2
            return ast.BoolOp(op, args)

        if fun_name in compare_ops:
            op = py_compare_ops[compare_ops.index(fun_name)]
            assert len(args) == 2
            return ast.Compare(args[0], [op], [args[1]])

        assert False
