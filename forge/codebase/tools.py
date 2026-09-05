"""
forge/codebase/tools.py — Semantic Code Intelligence tools.

Registered tools:
    get_code_outline, find_symbol, find_references
"""
from __future__ import annotations

import os
from forge.codebase.ast_index import CodebaseIndex
from forge.tools import registry

_index = CodebaseIndex(os.getcwd())


@registry.register(
    name="get_code_outline",
    description=(
        "Get a structured AST code outline (classes, functions, methods, parameters, return types, line numbers) "
        "of a source file without reading the entire raw text."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to inspect."},
        },
        "required": ["path"],
    },
)
def get_code_outline(path: str) -> str:
    return _index.get_file_outline(path)


@registry.register(
    name="find_symbol",
    description=(
        "Search the project's AST symbol index for classes, functions, or methods by name. "
        "Returns signature, parent class, docstring summary, file path, and exact line ranges."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Symbol name or substring to search for."},
            "limit": {"type": "integer", "description": "Maximum results to return. Default 10."},
        },
        "required": ["query"],
    },
)
def find_symbol(query: str, limit: int = 10) -> str:
    matches = _index.find_symbol(query, limit=limit)
    if not matches:
        return f"No symbols found matching '{query}'."

    lines = [f"Found {len(matches)} symbol match(es) for '{query}':"]
    for sym in matches:
        parent_info = f" (in {sym.parent})" if sym.parent else ""
        doc = f"\n      Summary: {sym.docstring}" if sym.docstring else ""
        lines.append(f"  • [{sym.kind}] {sym.filepath}:{sym.start_line}-{sym.end_line}{parent_info}\n      `{sym.signature}`{doc}")
    return "\n".join(lines)


@registry.register(
    name="find_references",
    description="Find usages, invocations, or references of a symbol or identifier across the codebase.",
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Exact symbol name to search for."},
            "limit": {"type": "integer", "description": "Maximum occurrences to return. Default 20."},
        },
        "required": ["symbol"],
    },
)
def find_references(symbol: str, limit: int = 20) -> str:
    refs = _index.find_references(symbol, limit=limit)
    if not refs:
        return f"No references found for '{symbol}'."

    lines = [f"Found {len(refs)} reference(s) to '{symbol}':"]
    for r in refs:
        lines.append(f"  • {r['file']}:{r['line']}: {r['content']}")
    return "\n".join(lines)
