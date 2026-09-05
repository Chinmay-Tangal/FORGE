"""
forge/codebase/ast_index.py — Semantic AST and Symbol Indexing engine.

Extracts classes, functions, methods, docstrings, type signatures, and line ranges
across the project using native Python AST analysis with polyglot regex fallbacks.
"""
from __future__ import annotations

import ast
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class SymbolInfo:
    """Represents a code symbol (class, function, method, interface)."""
    name: str
    kind: str  # 'class', 'function', 'async_function', 'method', 'variable', 'interface', 'struct'
    filepath: str
    start_line: int
    end_line: int
    signature: str = ""
    docstring: str = ""
    parent: Optional[str] = None
    decorators: List[str] = field(default_factory=list)


class PythonASTVisitor(ast.NodeVisitor):
    """Walks a Python AST to extract classes, functions, methods, and docstrings."""

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self.symbols: List[SymbolInfo] = []
        self._current_class: Optional[str] = None

    def _format_args(self, args_node: ast.arguments) -> str:
        parts = []
        # Positional only
        for a in getattr(args_node, "posonlyargs", []):
            ann = f": {ast.unparse(a.annotation)}" if a.annotation else ""
            parts.append(f"{a.arg}{ann}")
        if getattr(args_node, "posonlyargs", []):
            parts.append("/")

        # Standard positional/keyword args
        for a in args_node.args:
            ann = f": {ast.unparse(a.annotation)}" if a.annotation else ""
            parts.append(f"{a.arg}{ann}")

        # Varargs (*args)
        if args_node.vararg:
            ann = f": {ast.unparse(args_node.vararg.annotation)}" if args_node.vararg.annotation else ""
            parts.append(f"*{args_node.vararg.arg}{ann}")

        # Keyword-only args
        for a in args_node.kwonlyargs:
            ann = f": {ast.unparse(a.annotation)}" if a.annotation else ""
            parts.append(f"{a.arg}{ann}")

        # Kwarg (**kwargs)
        if args_node.kwarg:
            ann = f": {ast.unparse(args_node.kwarg.annotation)}" if args_node.kwarg.annotation else ""
            parts.append(f"**{args_node.kwarg.arg}{ann}")

        return ", ".join(parts)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = [ast.unparse(b) for b in node.bases]
        sig = f"class {node.name}" + (f"({', '.join(bases)})" if bases else "")
        doc = ast.get_docstring(node) or ""
        decorators = [ast.unparse(d) for d in node.decorator_list]

        sym = SymbolInfo(
            name=node.name,
            kind="class",
            filepath=self.filepath,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            signature=sig,
            docstring=doc.strip().splitlines()[0] if doc else "",
            decorators=decorators,
        )
        self.symbols.append(sym)

        old_class = self._current_class
        self._current_class = node.name
        self.generic_visit(node)
        self._current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_func(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_func(node, is_async=True)

    def _handle_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool) -> None:
        try:
            params = self._format_args(node.args)
        except Exception:
            params = "..."

        ret_ann = ""
        if node.returns:
            try:
                ret_ann = f" -> {ast.unparse(node.returns)}"
            except Exception:
                pass

        prefix = "async def " if is_async else "def "
        sig = f"{prefix}{node.name}({params}){ret_ann}"
        doc = ast.get_docstring(node) or ""
        decorators = [ast.unparse(d) for d in node.decorator_list]

        kind = "method" if self._current_class else ("async_function" if is_async else "function")

        sym = SymbolInfo(
            name=node.name,
            kind=kind,
            filepath=self.filepath,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            signature=sig,
            docstring=doc.strip().splitlines()[0] if doc else "",
            parent=self._current_class,
            decorators=decorators,
        )
        self.symbols.append(sym)


# Polyglot Regex Parser for JS/TS/Go/Rust/C++
_GENERIC_PATTERNS = [
    # TS/JS Class or Interface
    (re.compile(r"^(?:export\s+)?(?:abstract\s+)?(class|interface)\s+([a-zA-Z0-9_$]+)", re.MULTILINE), "class"),
    # TS/JS Function
    (re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\((.*?)\)", re.MULTILINE), "function"),
    # TS/JS Arrow Function const foo = (...) =>
    (re.compile(r"^(?:export\s+)?const\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\((.*?)\)\s*=>", re.MULTILINE), "function"),
    # Go Function / Method
    (re.compile(r"^func\s+(?:\((?:[a-zA-Z0-9_*\s]+)\)\s+)?([a-zA-Z0-9_]+)\s*\((.*?)\)", re.MULTILINE), "function"),
    # Go Struct / Interface
    (re.compile(r"^type\s+([a-zA-Z0-9_]+)\s+(struct|interface)", re.MULTILINE), "class"),
    # Rust fn / struct / enum / trait
    (re.compile(r"^(?:pub\s+)?(?:async\s+)?fn\s+([a-zA-Z0-9_]+)\s*\((.*?)\)", re.MULTILINE), "function"),
    (re.compile(r"^(?:pub\s+)?(struct|enum|trait)\s+([a-zA-Z0-9_]+)", re.MULTILINE), "class"),
]


class CodebaseIndex:
    """
    In-memory semantic symbol index of the workspace.
    """

    def __init__(self, base_dir: str = ".") -> None:
        self.base_dir = os.path.abspath(base_dir)
        self.symbols: List[SymbolInfo] = []
        self._indexed_files: Set[str] = set()

    def index_file(self, filepath: str) -> List[SymbolInfo]:
        """Index a single file and return its symbols."""
        abs_path = os.path.abspath(os.path.join(self.base_dir, filepath)) if not os.path.isabs(filepath) else filepath
        rel_path = os.path.relpath(abs_path, self.base_dir).replace("\\", "/")

        if not os.path.isfile(abs_path):
            return []

        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                code = fh.read()
        except Exception:
            return []

        file_symbols: List[SymbolInfo] = []

        if abs_path.endswith(".py"):
            try:
                tree = ast.parse(code, filename=abs_path)
                visitor = PythonASTVisitor(filepath=rel_path)
                visitor.visit(tree)
                file_symbols = visitor.symbols
            except SyntaxError:
                pass
        else:
            # Polyglot fallback
            lines = code.splitlines()
            for lineno, line in enumerate(lines, 1):
                line_str = line.strip()
                for pattern, kind in _GENERIC_PATTERNS:
                    m = pattern.search(line_str)
                    if m:
                        name = m.group(1) if kind != "class" or len(m.groups()) < 2 else m.group(2)
                        if name:
                            file_symbols.append(
                                SymbolInfo(
                                    name=name,
                                    kind=kind,
                                    filepath=rel_path,
                                    start_line=lineno,
                                    end_line=lineno,
                                    signature=line_str[:120],
                                )
                            )

        return file_symbols

    def index_workspace(self, max_files: int = 500) -> int:
        """Scan and index symbols across all project source files."""
        self.symbols = []
        self._indexed_files = set()

        ignored = {
            ".git", "__pycache__", ".pytest_cache", "node_modules",
            ".venv", "venv", ".egg-info", "build", "dist", ".forge", ".tox"
        }
        supported_exts = {".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs", ".cpp", ".c", ".h", ".hpp"}

        count = 0
        for root, dirs, files in os.walk(self.base_dir):
            dirs[:] = [d for d in dirs if d not in ignored and not d.startswith(".")]
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in supported_exts:
                    full_path = os.path.join(root, fname)
                    syms = self.index_file(full_path)
                    self.symbols.extend(syms)
                    self._indexed_files.add(full_path)
                    count += 1
                    if count >= max_files:
                        break
            if count >= max_files:
                break

        logger.info("Indexed %d symbols across %d files.", len(self.symbols), len(self._indexed_files))
        return len(self.symbols)

    def get_file_outline(self, filepath: str) -> str:
        """Return a formatted outline of symbols for a specific file."""
        syms = self.index_file(filepath)
        if not syms:
            return f"No symbols found in '{filepath}'."

        lines = [f"Symbols in {filepath}:"]
        for s in syms:
            indent = "    " if s.parent else "  "
            decorators = f" [{' ,'.join(s.decorators)}]" if s.decorators else ""
            doc = f" — {s.docstring}" if s.docstring else ""
            lines.append(f"{indent}[L{s.start_line}-L{s.end_line}] {s.signature}{decorators}{doc}")
        return "\n".join(lines)

    def find_symbol(self, query: str, limit: int = 15) -> List[SymbolInfo]:
        """Find symbols by exact or partial name match."""
        if not self.symbols:
            self.index_workspace()

        q = query.lower().strip()
        exact_matches = []
        partial_matches = []

        for s in self.symbols:
            s_lower = s.name.lower()
            if s_lower == q:
                exact_matches.append(s)
            elif q in s_lower or (s.parent and q in s.parent.lower()):
                partial_matches.append(s)

        results = exact_matches + partial_matches
        return results[:limit]

    def find_references(self, symbol_name: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Find occurrences of symbol_name being referenced or called in the codebase."""
        refs: List[Dict[str, Any]] = []
        pattern = re.compile(rf"\b{re.escape(symbol_name)}\b")

        ignored = {
            ".git", "__pycache__", ".pytest_cache", "node_modules",
            ".venv", "venv", ".egg-info", "build", "dist", ".forge"
        }

        for root, dirs, files in os.walk(self.base_dir):
            dirs[:] = [d for d in dirs if d not in ignored and not d.startswith(".")]
            for fname in files:
                if fname.endswith((".py", ".ts", ".js", ".go", ".rs")):
                    fpath = os.path.join(root, fname)
                    rel = os.path.relpath(fpath, self.base_dir).replace("\\", "/")
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                            for lineno, line in enumerate(fh, 1):
                                if pattern.search(line):
                                    refs.append({
                                        "file": rel,
                                        "line": lineno,
                                        "content": line.strip()[:140],
                                    })
                                    if len(refs) >= limit:
                                        return refs
                    except Exception:
                        pass
        return refs
