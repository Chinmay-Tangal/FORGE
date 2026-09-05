"""
Tests for AST symbol indexing, outline extraction, and symbol search.
"""
import os
import pytest
from forge.codebase.ast_index import CodebaseIndex, SymbolInfo, PythonASTVisitor


SAMPLE_PY_CODE = '''"""Module docstring."""

class Engine:
    """Represents a core engine."""
    def __init__(self, power: int = 100) -> None:
        self.power = power

    async def start(self) -> bool:
        """Start the engine."""
        return True


def helper_func(a: str, b: int = 10) -> str:
    """A sample helper function."""
    return f"{a}:{b}"
'''


class TestCodebaseAST:
    def test_python_ast_indexing(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text(SAMPLE_PY_CODE, encoding="utf-8")

        index = CodebaseIndex(base_dir=str(tmp_path))
        syms = index.index_file(str(f))

        names = [s.name for s in syms]
        assert "Engine" in names
        assert "__init__" in names
        assert "start" in names
        assert "helper_func" in names

        # Class checks
        engine_cls = next(s for s in syms if s.name == "Engine")
        assert engine_cls.kind == "class"
        assert "Represents a core engine" in engine_cls.docstring

        # Method checks
        start_method = next(s for s in syms if s.name == "start")
        assert start_method.kind == "method"
        assert start_method.parent == "Engine"
        assert "-> bool" in start_method.signature

        # Function checks
        helper = next(s for s in syms if s.name == "helper_func")
        assert helper.kind == "function"
        assert helper.parent is None
        assert "a: str, b: int" in helper.signature

    def test_file_outline_formatting(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text(SAMPLE_PY_CODE, encoding="utf-8")

        index = CodebaseIndex(base_dir=str(tmp_path))
        outline = index.get_file_outline(str(f))
        assert "Symbols in" in outline
        assert "class Engine" in outline
        assert "def helper_func" in outline

    def test_find_symbol(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text(SAMPLE_PY_CODE, encoding="utf-8")

        index = CodebaseIndex(base_dir=str(tmp_path))
        index.index_workspace()

        matches = index.find_symbol("Engine")
        assert len(matches) >= 1
        assert matches[0].name == "Engine"

        sub_matches = index.find_symbol("helper")
        assert len(sub_matches) >= 1
        assert sub_matches[0].name == "helper_func"

    def test_find_references(self, tmp_path):
        f1 = tmp_path / "mod1.py"
        f1.write_text("def target_fn(): pass\n", encoding="utf-8")
        f2 = tmp_path / "mod2.py"
        f2.write_text("import mod1\nmod1.target_fn()\n", encoding="utf-8")

        index = CodebaseIndex(base_dir=str(tmp_path))
        refs = index.find_references("target_fn")
        assert len(refs) >= 2
