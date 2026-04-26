"""Code localization pipeline: maps NormalizedRules to candidate code locations."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from spectrace.search import GrepHit, collect_terms, generate_variants, run_grep
from spectrace.treesitter_utils import (
    FunctionInfo,
    extract_function_text,
    find_enclosing_function,
    get_functions,
    parse_file,
)


@dataclass
class Candidate:
    """A candidate code location for a rule."""

    file: str
    function: str
    line_range: tuple[int, int]
    distinct_terms_matched: int
    hit_count: int
    category_breadth: int
    categories_present: list[str]
    function_name_match: bool
    terms_matched: list[str]
    hits: list[dict]


def localize_rule(
    rule: dict,
    source_root: str,
    search_dirs: list[str],
    top_k: int = 10,
) -> dict:
    """
    Run the full localization pipeline for a single rule.

    Returns the localization result dict ready to be written as JSON.
    """
    rule_id = rule["rule_id"]
    protocol_keywords = rule.get("protocol_keywords", {})

    # Step 1-2: Collect and deduplicate terms, generate variants
    search_terms = collect_terms(protocol_keywords)
    search_terms = generate_variants(search_terms)

    search_terms_output = [
        {
            "term": st.term,
            "categories": st.categories,
            "variants_searched": st.variants,
        }
        for st in search_terms
    ]

    if not search_terms:
        return _empty_result(rule, search_terms_output)

    # Step 3: Grep the codebase
    grep_hits = run_grep(search_terms, source_root, search_dirs)

    if not grep_hits:
        return _empty_result(rule, search_terms_output)

    # Step 4: Identify relevant files
    files_with_hits: dict[str, list[GrepHit]] = {}
    for hit in grep_hits:
        files_with_hits.setdefault(hit.file_path, []).append(hit)

    # Step 5: Parse files with tree-sitter, map hits to functions
    # Key: (file_path, function_name) -> list of hits
    function_hits: dict[tuple[str, str], list[GrepHit]] = {}
    function_info_map: dict[tuple[str, str], FunctionInfo] = {}
    null_scope_count = 0

    for file_path, hits in files_with_hits.items():
        abs_path = f"{source_root}/{file_path}"
        try:
            tree, source_bytes = parse_file(abs_path)
            functions = get_functions(tree, source_bytes)
        except (FileNotFoundError, OSError):
            continue

        for hit in hits:
            func = find_enclosing_function(functions, hit.line_number)
            if func is None:
                null_scope_count += 1
                continue
            key = (file_path, func.name)
            function_hits.setdefault(key, []).append(hit)
            function_info_map[key] = func

    # Step 6: Score and sort candidates
    candidates: list[Candidate] = []
    all_search_term_strings = {st.term for st in search_terms}

    for (file_path, func_name), hits in function_hits.items():
        func_info = function_info_map[(file_path, func_name)]
        terms_matched = list({h.matched_term for h in hits})
        all_categories = set()
        for h in hits:
            all_categories.update(h.categories)
        categories_present = sorted(all_categories)

        # Check if function name contains any search term
        func_name_lower = func_name.lower()
        function_name_match = any(
            t.lower() in func_name_lower for t in all_search_term_strings
        )

        candidates.append(Candidate(
            file=file_path,
            function=func_name,
            line_range=(func_info.start_line, func_info.end_line),
            distinct_terms_matched=len(terms_matched),
            hit_count=len(hits),
            category_breadth=len(categories_present),
            categories_present=categories_present,
            function_name_match=function_name_match,
            terms_matched=sorted(terms_matched),
            hits=[
                {
                    "term": h.matched_term,
                    "line": h.line_number,
                    "text": h.line_text[:200],
                }
                for h in hits
            ],
        ))

    # Sort: primary by distinct_terms_matched desc, secondary by hit_count desc
    candidates.sort(key=lambda c: (c.distinct_terms_matched, c.hit_count), reverse=True)

    # Take top-k
    top_candidates = candidates[:top_k]

    # Warn about very long functions
    for c in top_candidates:
        func_len = c.line_range[1] - c.line_range[0] + 1
        if func_len > 500:
            print(
                f"Warning: {c.file}:{c.function} is {func_len} lines long",
                file=sys.stderr,
            )

    # Build output
    candidates_output = []
    for rank, c in enumerate(top_candidates, 1):
        candidates_output.append({
            "rank": rank,
            "file": c.file,
            "function": c.function,
            "line_range": list(c.line_range),
            "distinct_terms_matched": c.distinct_terms_matched,
            "hit_count": c.hit_count,
            "metadata": {
                "category_breadth": c.category_breadth,
                "categories_present": c.categories_present,
                "function_name_match": c.function_name_match,
                "terms_matched": c.terms_matched,
            },
            "hits": c.hits,
        })

    total_top_k_lines = sum(
        c.line_range[1] - c.line_range[0] + 1 for c in top_candidates
    )

    return {
        "rule_id": rule_id,
        "rule_type": rule.get("rule_type"),
        "checkability": rule.get("checkability"),
        "search_terms": search_terms_output,
        "candidates": candidates_output,
        "scoped_code_files": [],  # filled in by write_localization
        "stats": {
            "total_grep_hits": len(grep_hits),
            "files_with_hits": len(files_with_hits),
            "functions_identified": len(function_hits),
            "null_scope_hits": null_scope_count,
            "top_k_returned": len(top_candidates),
            "total_lines_in_top_k": total_top_k_lines,
        },
    }


def _empty_result(rule: dict, search_terms: list[dict]) -> dict:
    return {
        "rule_id": rule["rule_id"],
        "rule_type": rule.get("rule_type"),
        "checkability": rule.get("checkability"),
        "search_terms": search_terms,
        "candidates": [],
        "scoped_code_files": [],
        "stats": {
            "total_grep_hits": 0,
            "files_with_hits": 0,
            "functions_identified": 0,
            "null_scope_hits": 0,
            "top_k_returned": 0,
            "total_lines_in_top_k": 0,
        },
    }


def write_localization(
    result: dict,
    source_root: str,
    output_dir: Path,
) -> Path:
    """Write localization result JSON and extracted function files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    code_dir = output_dir / "code"
    code_dir.mkdir(exist_ok=True)

    rule_id = result["rule_id"]
    # Convert rule_id dots to dashes for filenames: rfc8446-4.2.8-R05 -> rfc8446-4-2-8-R05
    safe_id = rule_id.replace(".", "-")

    # Extract function text for each candidate
    scoped_files = []
    for candidate in result["candidates"]:
        rank = candidate["rank"]
        abs_path = f"{source_root}/{candidate['file']}"
        func_name = candidate["function"]
        line_start, line_end = candidate["line_range"]

        code_filename = f"{safe_id}_candidate_{rank}.c"
        code_path = code_dir / code_filename

        try:
            lines = Path(abs_path).read_text(errors="replace").splitlines()
            func_text = "\n".join(lines[line_start - 1 : line_end])
        except (FileNotFoundError, OSError):
            func_text = f"// Error: could not read {abs_path}"

        header = (
            f"// Source: {candidate['file']}\n"
            f"// Function: {func_name}\n"
            f"// Lines: {line_start}-{line_end}\n"
            f"// Rule: {rule_id}\n\n"
        )
        code_path.write_text(header + func_text + "\n")
        scoped_files.append(f"locations/code/{code_filename}")

    result["scoped_code_files"] = scoped_files

    # Write the result JSON
    json_path = output_dir / f"{safe_id}.json"
    json_path.write_text(json.dumps(result, indent=2) + "\n")

    return json_path
