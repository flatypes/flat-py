import ast
from typing import Any
from flat.typing import Type


"""Evaluate type aliases of our interest in a Python AST.
   Only evaluates type aliases that are defined at the top level."""
class AnnotEvaluator(ast.NodeVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.env: dict[str, Any] = {}

    def visit_Import(self, node: ast.Import) -> None:
        exec(ast.unparse(node), {}, self.env)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        exec(ast.unparse(node), {}, self.env)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return  # Skip function definitions

    def visit_TypeAlias(self, node: ast.TypeAlias):
        if len(node.type_params) == 0:
            self.env[node.name.id] = eval(ast.unparse(node.value), self.env)

    def visit_ClassDef(self, node: ast.ClassDef):
        keys_to_remove = globals().keys()
        exec(ast.unparse(node), self.env, self.env)
        self.env = {k: v for k, v in self.env.items() if k not in keys_to_remove}

    def visit_Assign(self, node: ast.Assign) -> None:
        match node.targets, node.value:
            case [ast.Name(t)], ast.Call(ast.Name(f)) if f in self.env:
                if self.env[f].__module__ == 'flat.py':
                    self.env[t] = eval(ast.unparse(node.value), self.env)
