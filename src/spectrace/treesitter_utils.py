"""Tree-sitter utilities for parsing C files and mapping grep hits to functions."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import tree_sitter_c as tsc
from tree_sitter import Language, Parser

C_LANGUAGE = Language(tsc.language())


@dataclass
class FunctionInfo:
    """Information about a function found by tree-sitter."""

    name: str
    start_line: int  # 1-indexed
    end_line: int  # 1-indexed


def _get_parser() -> Parser:
    return Parser(C_LANGUAGE)


def parse_file(filepath: str) -> tuple[object, bytes]:
    """Parse a C file and return (tree, source_bytes)."""
    source_bytes = Path(filepath).read_bytes()
    parser = _get_parser()
    tree = parser.parse(source_bytes)
    return tree, source_bytes


def get_functions(tree, source_bytes: bytes) -> list[FunctionInfo]:
    """Extract all function definitions from a parsed tree (iterative walk)."""
    functions = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "function_definition":
            name = _extract_function_name(node, source_bytes)
            if name:
                functions.append(FunctionInfo(
                    name=name,
                    start_line=node.start_point.row + 1,
                    end_line=node.end_point.row + 1,
                ))
        stack.extend(node.children)
    return functions


def _extract_function_name(func_node, source_bytes: bytes) -> Optional[str]:
    """Extract the function name from a function_definition node."""
    declarator = func_node.child_by_field_name("declarator")
    if declarator is None:
        return None
    return _find_identifier(declarator, source_bytes)


def _find_identifier(node, source_bytes: bytes) -> Optional[str]:
    """Find the function name identifier in a declarator (BFS, leftmost-first)."""
    from collections import deque
    queue = deque([node])
    while queue:
        n = queue.popleft()
        if n.type == "identifier":
            return source_bytes[n.start_byte:n.end_byte].decode("utf-8", errors="replace")
        # Only descend into declarator-like nodes, not parameter lists
        if n.type not in ("parameter_list", "parameter_declaration", "argument_list"):
            queue.extend(n.children)
    return None


def find_enclosing_function(functions: list[FunctionInfo], line: int) -> Optional[FunctionInfo]:
    """Find which function encloses a given line number (1-indexed)."""
    for func in functions:
        if func.start_line <= line <= func.end_line:
            return func
    return None


def extract_function_text(filepath: str, func: FunctionInfo) -> str:
    """Extract the full text of a function from a source file."""
    lines = Path(filepath).read_text(errors="replace").splitlines()
    # start_line and end_line are 1-indexed
    return "\n".join(lines[func.start_line - 1 : func.end_line])
