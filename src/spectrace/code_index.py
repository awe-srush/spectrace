"""Tree-sitter based code index for cross-file navigation during conformance checking."""

import sys
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Query, QueryCursor

from spectrace.treesitter_utils import (
    C_LANGUAGE,
    FunctionInfo,
    extract_function_text,
    find_enclosing_function,
    get_functions,
    parse_file,
)

# Tree-sitter queries for call extraction
CALL_QUERY = Query(C_LANGUAGE, "(call_expression function: (identifier) @callee)")
FIELD_CALL_QUERY = Query(
    C_LANGUAGE,
    "(call_expression function: (field_expression field: (field_identifier) @callee))",
)


@dataclass
class FunctionDef:
    """A function definition with its location and source text."""

    name: str
    file: str  # relative path from source_root
    start_line: int  # 1-indexed
    end_line: int  # 1-indexed
    start_byte: int
    end_byte: int
    body: str


class CodeIndex:
    """
    Pre-built tree-sitter index over a C codebase.

    Parses all .c and .h files in the given search directories and provides:
    - Function definition lookup by name
    - Callee extraction (what does function X call?)
    - Caller search (who calls function X?)
    - Symbol search (where is identifier X used?)
    """

    def __init__(self, source_root: str, search_dirs: list[str]):
        self.source_root = Path(source_root)
        self._func_index: dict[str, list[FunctionDef]] = {}
        self._file_trees: dict[str, tuple] = {}  # rel_path -> (tree, source_bytes)
        self._file_functions: dict[str, list[FunctionInfo]] = {}  # rel_path -> functions

        file_count = 0
        func_count = 0

        for search_dir in search_dirs:
            dir_path = self.source_root / search_dir
            if not dir_path.is_dir():
                print(f"Warning: search dir not found: {dir_path}", file=sys.stderr)
                continue

            for pattern in ("**/*.c", "**/*.h"):
                for filepath in sorted(dir_path.rglob(pattern.split("/")[-1])):
                    if not filepath.is_file():
                        continue
                    rel_path = str(filepath.relative_to(self.source_root))

                    # Skip if already indexed (can happen with overlapping search dirs)
                    if rel_path in self._file_trees:
                        continue

                    try:
                        tree, source_bytes = parse_file(str(filepath))
                    except Exception as e:
                        print(f"Warning: failed to parse {rel_path}: {e}", file=sys.stderr)
                        continue

                    self._file_trees[rel_path] = (tree, source_bytes)
                    functions = get_functions(tree, source_bytes)
                    self._file_functions[rel_path] = functions
                    file_count += 1

                    # Index each function definition
                    for func in functions:
                        fdef = FunctionDef(
                            name=func.name,
                            file=rel_path,
                            start_line=func.start_line,
                            end_line=func.end_line,
                            start_byte=self._find_node_bytes(tree, func)[0],
                            end_byte=self._find_node_bytes(tree, func)[1],
                            body=extract_function_text(str(filepath), func),
                        )
                        self._func_index.setdefault(func.name, []).append(fdef)
                        func_count += 1

        self.file_count = file_count
        self.function_count = func_count
        print(
            f"CodeIndex: indexed {file_count} files, {func_count} functions",
            file=sys.stderr,
        )

    def _find_node_bytes(self, tree, func: FunctionInfo) -> tuple[int, int]:
        """Find the byte range of a function_definition node matching the given FunctionInfo."""
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if (
                node.type == "function_definition"
                and node.start_point.row + 1 == func.start_line
                and node.end_point.row + 1 == func.end_line
            ):
                return node.start_byte, node.end_byte
            stack.extend(node.children)
        # Fallback: use approximate byte positions
        return 0, 0

    def get_function(self, name: str) -> list[FunctionDef]:
        """Return all definitions of a function by name."""
        return self._func_index.get(name, [])

    def get_callees(self, function_name: str, file_hint: str | None = None) -> list[str]:
        """
        Return names of all functions called by function_name.

        Uses tree-sitter QueryCursor scoped to the function's byte range.
        """
        defs = self.get_function(function_name)
        if not defs:
            return []

        # Pick the right definition
        fdef = defs[0]
        if file_hint:
            for d in defs:
                if d.file == file_hint:
                    fdef = d
                    break

        if fdef.file not in self._file_trees:
            return []

        tree, source_bytes = self._file_trees[fdef.file]
        root = tree.root_node

        callees = set()

        # Find the function node and query within it
        func_node = self._find_func_node(root, fdef)
        if func_node is None:
            return []

        # Direct calls: foo(...)
        cursor = QueryCursor(CALL_QUERY)
        cursor.set_byte_range(func_node.start_byte, func_node.end_byte)
        for _, match_dict in cursor.matches(func_node):
            for nodes in match_dict.values():
                for node in nodes:
                    name = source_bytes[node.start_byte : node.end_byte].decode(
                        "utf-8", errors="replace"
                    )
                    callees.add(name)

        # Field calls: obj->method(...) or obj.method(...)
        cursor = QueryCursor(FIELD_CALL_QUERY)
        cursor.set_byte_range(func_node.start_byte, func_node.end_byte)
        for _, match_dict in cursor.matches(func_node):
            for nodes in match_dict.values():
                for node in nodes:
                    name = source_bytes[node.start_byte : node.end_byte].decode(
                        "utf-8", errors="replace"
                    )
                    callees.add(name)

        return sorted(callees)

    def get_callers(self, function_name: str, max_results: int = 50) -> list[dict]:
        """
        Find all functions that call the given function name.

        Returns list of {caller_function, file, line, context}.
        """
        callers = []
        for rel_path, (tree, source_bytes) in self._file_trees.items():
            root = tree.root_node
            functions = self._file_functions.get(rel_path, [])

            cursor = QueryCursor(CALL_QUERY)
            for _, match_dict in cursor.matches(root):
                for nodes in match_dict.values():
                    for node in nodes:
                        name = source_bytes[node.start_byte : node.end_byte].decode(
                            "utf-8", errors="replace"
                        )
                        if name != function_name:
                            continue

                        line = node.start_point.row + 1
                        enclosing = find_enclosing_function(functions, line)

                        # Get the line text for context
                        lines = source_bytes.decode("utf-8", errors="replace").split("\n")
                        context = lines[line - 1].strip() if line <= len(lines) else ""

                        callers.append({
                            "caller_function": enclosing.name if enclosing else "(global)",
                            "file": rel_path,
                            "line": line,
                            "context": context[:200],
                        })

                        if len(callers) >= max_results:
                            return callers

        return callers

    def search_symbol(self, symbol_name: str, max_results: int = 30) -> list[dict]:
        """
        Search for an identifier across all indexed files.

        Uses simple text search on file contents (faster than tree-sitter query
        over all files for a single identifier).
        """
        results = []
        for rel_path, (tree, source_bytes) in self._file_trees.items():
            text = source_bytes.decode("utf-8", errors="replace")
            lines = text.split("\n")
            functions = self._file_functions.get(rel_path, [])

            for i, line in enumerate(lines, 1):
                # Simple word-boundary check
                if symbol_name not in line:
                    continue
                # Verify it's a whole word match (not substring)
                idx = 0
                while True:
                    idx = line.find(symbol_name, idx)
                    if idx == -1:
                        break
                    # Check word boundaries
                    before_ok = idx == 0 or not (line[idx - 1].isalnum() or line[idx - 1] == "_")
                    after_idx = idx + len(symbol_name)
                    after_ok = after_idx >= len(line) or not (
                        line[after_idx].isalnum() or line[after_idx] == "_"
                    )
                    if before_ok and after_ok:
                        enclosing = find_enclosing_function(functions, i)
                        results.append({
                            "file": rel_path,
                            "line": i,
                            "function": enclosing.name if enclosing else None,
                            "context": line.strip()[:200],
                        })
                        break
                    idx += 1

                if len(results) >= max_results:
                    return results

        return results

    def _find_func_node(self, root, fdef: FunctionDef):
        """Find the tree-sitter node for a FunctionDef."""
        stack = [root]
        while stack:
            node = stack.pop()
            if (
                node.type == "function_definition"
                and node.start_point.row + 1 == fdef.start_line
                and node.end_point.row + 1 == fdef.end_line
            ):
                return node
            stack.extend(node.children)
        return None
