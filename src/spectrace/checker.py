"""Conformance judgment: sends rule + code to LLM with tool-use for cross-file navigation."""

import json
import re
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import anthropic

from spectrace.prompts.judgment import JUDGMENT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from spectrace.code_index import CodeIndex


class JudgmentResult:
    """Result of a conformance judgment, including the judgment dict and token usage."""

    def __init__(self, judgment: dict, usage: dict):
        self.judgment = judgment
        self.usage = usage


# Tool definitions for the Anthropic API
TOOLS = [
    {
        "name": "get_function_source",
        "description": (
            "Get the full source code of a function definition. Use this when you "
            "need to see how a called function is implemented. If multiple definitions "
            "exist (e.g., static functions in different files), all are returned."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {
                    "type": "string",
                    "description": "Exact function name to look up",
                },
            },
            "required": ["function_name"],
        },
    },
    {
        "name": "get_callees",
        "description": (
            "List all functions called by a given function. Use this to understand "
            "what a function delegates to before looking up specific callees."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {
                    "type": "string",
                    "description": "Function whose callees you want to see",
                },
            },
            "required": ["function_name"],
        },
    },
    {
        "name": "get_callers",
        "description": (
            "Find all functions that call a given function. Use this when you need "
            "to understand how a function is invoked or what context it runs in."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {
                    "type": "string",
                    "description": "Function whose callers you want to find",
                },
            },
            "required": ["function_name"],
        },
    },
    {
        "name": "search_symbol",
        "description": (
            "Search for any symbol, variable name, macro, or identifier across the "
            "codebase. Use this when you need to find where something is defined, "
            "assigned, or used but don't know which function it's in. Returns matching "
            "lines with file, line number, and enclosing function."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Symbol or identifier to search for",
                },
            },
            "required": ["symbol"],
        },
    },
]


def build_focus_guidance(candidates: list[dict]) -> str:
    """Build natural-language focus guidance from localization candidates."""
    lines = []
    for c in candidates:
        start, end = c["line_range"]
        lines.append(f"- Function `{c['function']}` (lines {start}-{end})")
        for hit in c.get("hits", [])[:10]:
            lines.append(
                f"  - Line {hit['line']}: matches term '{hit['term']}' — {hit['text'][:150]}"
            )
    return "\n".join(lines)


def execute_tool(tool_name: str, tool_input: dict, code_index: "CodeIndex") -> str:
    """Execute a tool call against the code index and return result as string."""
    if tool_name == "get_function_source":
        results = code_index.get_function(tool_input["function_name"])
        if not results:
            return f"No function named '{tool_input['function_name']}' found in the indexed codebase."
        parts = []
        for r in results:
            body = r.body
            # Truncate very large functions
            lines = body.split("\n")
            if len(lines) > 400:
                body = "\n".join(lines[:400]) + f"\n\n// ... truncated ({len(lines)} total lines)"
            parts.append(
                f"// File: {r.file} (lines {r.start_line}-{r.end_line})\n{body}"
            )
        return "\n\n".join(parts)

    elif tool_name == "get_callees":
        callees = code_index.get_callees(tool_input["function_name"])
        if not callees:
            return (
                f"No callees found for '{tool_input['function_name']}' "
                f"(function may not exist in index or has no calls)."
            )
        return (
            f"Functions called by {tool_input['function_name']}:\n"
            + "\n".join(f"  - {c}" for c in callees)
        )

    elif tool_name == "get_callers":
        callers = code_index.get_callers(tool_input["function_name"])
        if not callers:
            return f"No callers found for '{tool_input['function_name']}' in the indexed codebase."
        parts = [f"Functions that call {tool_input['function_name']}:"]
        for c in callers:
            parts.append(f"  - {c['caller_function']} in {c['file']}:{c['line']}")
        return "\n".join(parts)

    elif tool_name == "search_symbol":
        results = code_index.search_symbol(tool_input["symbol"])
        if not results:
            return f"No matches found for '{tool_input['symbol']}' in the indexed codebase."
        parts = [f"Matches for '{tool_input['symbol']}':"]
        for r in results:
            fn = r["function"] or "(global scope)"
            parts.append(f"  {r['file']}:{r['line']} in {fn}: {r['context']}")
        return "\n".join(parts)

    return f"Unknown tool: {tool_name}"


def build_initial_context(
    rule: dict,
    source_file: str,
    focus_candidates: list[dict],
    code_index: "CodeIndex",
) -> str:
    """Build the initial user message with rule + primary function bodies."""
    parts = []
    parts.append("## Rule to check\n\n")
    parts.append(f"```json\n{json.dumps(rule, indent=2)}\n```\n\n")

    parts.append("## Focus guidance\n\n")
    focus_text = build_focus_guidance(focus_candidates)
    parts.append(f"{focus_text}\n\n")

    parts.append("## Primary functions\n\n")
    parts.append(
        "The functions below were identified by searching the codebase for terms "
        "from the rule. Start your analysis here. Use the available tools to look "
        "up any called functions, callers, or symbols you need to determine "
        "conformance.\n\n"
    )

    seen_funcs = set()
    for c in focus_candidates:
        fn_name = c["function"]
        if fn_name in seen_funcs:
            continue
        seen_funcs.add(fn_name)

        bodies = code_index.get_function(fn_name)
        if bodies:
            # Prefer definition in the same file as the candidate
            best = bodies[0]
            for b in bodies:
                if b.file == source_file:
                    best = b
                    break
            body = best.body
            body_lines = body.split("\n")
            if len(body_lines) > 400:
                body = (
                    "\n".join(body_lines[:400])
                    + f"\n\n// ... truncated ({len(body_lines)} total lines)"
                )
            parts.append(
                f"### {best.name} ({best.file}:{best.start_line}-{best.end_line})\n\n"
                f"```c\n{body}\n```\n\n"
            )
        else:
            parts.append(f"### {fn_name} — not found in index\n\n")

    parts.append(
        "Check whether this code conforms to the rule. Use the available tools "
        "to look up any functions, callers, or symbols you need to resolve "
        "cross-file dependencies. When you have enough information, output your "
        "final judgment as a JSON object (no markdown fences)."
    )

    return "".join(parts)


def check_conformance(
    rule: dict,
    source_file: str,
    focus_candidates: list[dict],
    code_index: "CodeIndex",
    model: str = "claude-sonnet-4-6",
    max_tool_calls: int = 10,
) -> JudgmentResult:
    """
    Check whether source code conforms to a specific rule using tool-use loop.

    The LLM starts with the primary function body and can use tools to navigate
    the codebase (look up function definitions, callers, symbols) to resolve
    cross-file dependencies.

    Args:
        rule: NormalizedRule dict
        source_file: relative path of the primary source file
        focus_candidates: list of candidate dicts from localization for this file
        code_index: pre-built CodeIndex for the codebase
        model: Anthropic model to use
        max_tool_calls: maximum number of tool calls allowed

    Returns:
        JudgmentResult with judgment dict and token usage
    """
    client = anthropic.Anthropic()

    primary_function = focus_candidates[0]["function"] if focus_candidates else "unknown"
    initial_context = build_initial_context(rule, source_file, focus_candidates, code_index)

    messages = [{"role": "user", "content": initial_context}]

    total_usage = {"input": 0, "output": 0}
    tool_calls_made = 0
    tools_used = []

    for turn in range(max_tool_calls + 5):  # extra turns for budget-exceeded message + final response
        # Retry with backoff on rate limit errors
        response = None
        for retry in range(5):
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    system=JUDGMENT_SYSTEM_PROMPT,
                    messages=messages,
                    tools=TOOLS if tool_calls_made < max_tool_calls else [],
                )
                break
            except anthropic.RateLimitError:
                wait = 30 * (retry + 1)
                print(
                    f"Rate limited, waiting {wait}s (retry {retry + 1}/5)...",
                    file=sys.stderr,
                )
                time.sleep(wait)
            except anthropic.APIConnectionError:
                wait = 10 * (retry + 1)
                print(
                    f"Connection error, waiting {wait}s (retry {retry + 1}/5)...",
                    file=sys.stderr,
                )
                time.sleep(wait)
        else:
            # All retries exhausted
            return JudgmentResult(
                _error_judgment(rule, source_file, primary_function, "API error after 5 retries."),
                total_usage,
            )

        total_usage["input"] += response.usage.input_tokens
        total_usage["output"] += response.usage.output_tokens

        # Check if the response contains tool use
        if response.stop_reason == "tool_use":
            # Process tool calls
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_calls_made += 1
                    tools_used.append({"tool": block.name, "input": block.input})

                    if tool_calls_made > max_tool_calls:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Tool call budget exceeded. Please provide your judgment now based on what you have seen so far.",
                            "is_error": True,
                        })
                    else:
                        result = execute_tool(block.name, block.input, code_index)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        elif response.stop_reason == "end_turn":
            # LLM has produced its final response — extract judgment
            response_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    response_text += block.text

            judgment = _parse_judgment(response_text, rule, source_file, primary_function)

            # If JSON parse failed, ask the LLM to output just the JSON
            if judgment.get("judgment") == "error" and "Failed to parse" in judgment.get("reasoning", ""):
                messages.append({"role": "assistant", "content": response.content})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your response was not valid JSON. Based on your analysis above, "
                        "output ONLY the JSON judgment object now. No prose, no markdown "
                        "fences, just the JSON object with rule_id, source_file, "
                        "primary_function, judgment, confidence, reasoning, and evidence fields."
                    ),
                })
                continue  # One more turn to get JSON

            judgment["tool_calls_made"] = tool_calls_made
            judgment["tools_used"] = tools_used
            judgment["model"] = model
            judgment["tokens_used"] = total_usage

            return JudgmentResult(judgment, total_usage)

    # Should not reach here, but safety fallback
    return JudgmentResult(
        _error_judgment(rule, source_file, primary_function, "Max turns exceeded without judgment."),
        total_usage,
    )


def _parse_judgment(response_text: str, rule: dict, source_file: str, primary_function: str) -> dict:
    """Parse a JSON judgment from the LLM's text response."""
    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", response_text, re.DOTALL)
    if fence_match:
        response_text = fence_match.group(1).strip()
    else:
        response_text = response_text.strip()

    try:
        judgment = json.loads(response_text)
    except json.JSONDecodeError:
        judgment = {
            "judgment": "error",
            "confidence": "low",
            "reasoning": f"Failed to parse LLM response as JSON.",
            "raw_response": response_text[:2000],
            "evidence": {
                "violating_lines": [],
                "conforming_lines": [],
                "key_code_snippet": "",
                "expected_behavior": "",
                "paths_checked": 0,
                "paths_conforming": 0,
                "paths_violating": 0,
            },
        }

    # Ensure required fields
    judgment.setdefault("rule_id", rule.get("rule_id"))
    judgment.setdefault("source_file", source_file)
    judgment.setdefault("primary_function", primary_function)
    judgment.setdefault("context_used_beyond_primary_function", False)

    return judgment


def _error_judgment(rule: dict, source_file: str, primary_function: str, reason: str) -> dict:
    """Build an error judgment dict."""
    return {
        "rule_id": rule.get("rule_id"),
        "source_file": source_file,
        "primary_function": primary_function,
        "judgment": "error",
        "confidence": "low",
        "reasoning": reason,
        "evidence": {
            "violating_lines": [],
            "conforming_lines": [],
            "key_code_snippet": "",
            "expected_behavior": "",
            "paths_checked": 0,
            "paths_conforming": 0,
            "paths_violating": 0,
        },
        "context_used_beyond_primary_function": False,
    }


def group_candidates_by_file(localization: dict) -> dict[str, list[dict]]:
    """Group localization candidates by source file path."""
    by_file: dict[str, list[dict]] = {}
    for c in localization.get("candidates", []):
        by_file.setdefault(c["file"], []).append(c)
    return by_file


def check_rule(
    rule: dict,
    localization: dict,
    source_root: str,
    code_index: "CodeIndex",
    model: str = "claude-sonnet-4-6",
    max_candidates_per_file: int = 5,
    max_tool_calls: int = 10,
) -> list[JudgmentResult]:
    """
    Check conformance for a single rule across all its localized source files.

    Args:
        rule: NormalizedRule dict
        localization: localization result dict for this rule
        source_root: root path of the target codebase
        code_index: pre-built CodeIndex for the codebase
        model: Anthropic model to use
        max_candidates_per_file: max candidates to include in focus guidance per file
        max_tool_calls: max tool calls per judgment

    Returns:
        list of JudgmentResults, one per source file
    """
    by_file = group_candidates_by_file(localization)
    results = []

    for source_file, candidates in by_file.items():
        focus = candidates[:max_candidates_per_file]
        result = check_conformance(
            rule, source_file, focus, code_index, model=model, max_tool_calls=max_tool_calls
        )
        results.append(result)

    return results


def write_judgment(
    judgment: dict,
    output_dir: Path,
) -> Path:
    """Write a single judgment JSON to the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    rule_id = judgment.get("rule_id", "unknown")
    source_file = judgment.get("source_file", "unknown")

    # Build filename from rule_id and source file
    safe_rule = rule_id.replace(".", "-")
    safe_file = Path(source_file).stem
    filename = f"{safe_rule}_{safe_file}.json"

    out_path = output_dir / filename
    out_path.write_text(json.dumps(judgment, indent=2) + "\n")
    return out_path


def write_summary(
    all_judgments: list[dict],
    model: str,
    output_dir: Path,
    skipped_rules: list[str] | None = None,
) -> Path:
    """Write a summary JSON aggregating all judgments."""
    output_dir.mkdir(parents=True, exist_ok=True)

    counts = {"conforms": 0, "violates": 0, "not_applicable": 0, "ambiguous": 0, "error": 0}
    violations = []
    total_input = 0
    total_output = 0
    total_tool_calls = 0
    rules_seen = set()

    for j in all_judgments:
        jtype = j.get("judgment", "error")
        counts[jtype] = counts.get(jtype, 0) + 1
        rules_seen.add(j.get("rule_id"))

        tokens = j.get("tokens_used", {})
        total_input += tokens.get("input", 0)
        total_output += tokens.get("output", 0)
        total_tool_calls += j.get("tool_calls_made", 0)

        if jtype == "violates":
            violations.append({
                "rule_id": j.get("rule_id"),
                "source_file": j.get("source_file"),
                "function": j.get("primary_function"),
                "confidence": j.get("confidence"),
                "summary": j.get("reasoning", "")[:200],
            })

    summary = {
        "total_rules_checked": len(rules_seen),
        "total_judgments": len(all_judgments),
        "judgment_counts": counts,
        "violations": violations,
        "skipped_rules": skipped_rules or [],
        "model": model,
        "total_tokens": {
            "input": total_input,
            "output": total_output,
        },
        "total_tool_calls": total_tool_calls,
    }

    out_path = output_dir / "_summary.json"
    out_path.write_text(json.dumps(summary, indent=2) + "\n")
    return out_path
