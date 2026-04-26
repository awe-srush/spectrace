"""Tests for tree-sitter utilities."""

from pathlib import Path

import pytest

from spectrace.treesitter_utils import (
    FunctionInfo,
    extract_function_text,
    find_enclosing_function,
    get_functions,
    parse_file,
)

SAMPLE_C = """\
#include <stdio.h>

int add(int a, int b) {
    return a + b;
}

void greet(const char *name) {
    printf("Hello, %s\\n", name);
}

int main() {
    greet("world");
    return add(1, 2);
}
"""


@pytest.fixture
def c_file(tmp_path):
    f = tmp_path / "test.c"
    f.write_text(SAMPLE_C)
    return str(f)


def test_parse_file(c_file):
    tree, source_bytes = parse_file(c_file)
    assert tree.root_node.type == "translation_unit"
    assert len(source_bytes) > 0


def test_get_functions(c_file):
    tree, source_bytes = parse_file(c_file)
    functions = get_functions(tree, source_bytes)
    names = [f.name for f in functions]
    assert "add" in names
    assert "greet" in names
    assert "main" in names
    assert len(functions) == 3


def test_find_enclosing_function(c_file):
    tree, source_bytes = parse_file(c_file)
    functions = get_functions(tree, source_bytes)

    # Line 4 is inside add()
    func = find_enclosing_function(functions, 4)
    assert func is not None
    assert func.name == "add"

    # Line 8 is inside greet()
    func = find_enclosing_function(functions, 8)
    assert func is not None
    assert func.name == "greet"

    # Line 1 is outside any function
    func = find_enclosing_function(functions, 1)
    assert func is None


def test_extract_function_text(c_file):
    tree, source_bytes = parse_file(c_file)
    functions = get_functions(tree, source_bytes)
    add_func = [f for f in functions if f.name == "add"][0]

    text = extract_function_text(c_file, add_func)
    assert "int add" in text
    assert "return a + b" in text
