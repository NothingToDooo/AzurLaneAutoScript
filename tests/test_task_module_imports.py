import ast
import importlib
from pathlib import Path

import pytest


def _local_module_imports() -> list[str]:
    imports: list[str] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._scope_depth = 0

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._scope_depth += 1
            self.generic_visit(node)
            self._scope_depth -= 1

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._scope_depth += 1
            self.generic_visit(node)
            self._scope_depth -= 1

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if self._scope_depth > 0 and node.module and node.module.startswith("module.") and node.module not in imports:
                imports.append(node.module)

    alas_path = Path(__file__).resolve().parents[1] / "alas.py"
    tree = ast.parse(alas_path.read_text(encoding="utf-8"))
    Visitor().visit(tree)
    return imports


@pytest.mark.parametrize("module_name", _local_module_imports())
def test_alas_local_task_imports(module_name: str) -> None:
    importlib.import_module(module_name)
