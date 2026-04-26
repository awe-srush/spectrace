"""Term collection, variant generation, and grep execution for code localization."""

import re
import subprocess
from dataclasses import dataclass, field


@dataclass
class SearchTerm:
    """A search term with its keyword categories and generated variants."""

    term: str
    categories: list[str]
    variants: list[str] = field(default_factory=list)


@dataclass
class GrepHit:
    """A single grep match in the codebase."""

    file_path: str
    line_number: int
    line_text: str
    matched_term: str
    categories: list[str]


def collect_terms(protocol_keywords: dict) -> list[SearchTerm]:
    """Flatten protocol_keywords into deduplicated SearchTerms with category tags."""
    term_map: dict[str, list[str]] = {}
    for category, terms in protocol_keywords.items():
        for term in terms:
            if term not in term_map:
                term_map[term] = []
            if category not in term_map[term]:
                term_map[term].append(category)

    return [SearchTerm(term=t, categories=cats) for t, cats in term_map.items()]


def _to_camel_case(snake: str) -> str:
    """Convert snake_case to CamelCase. e.g. 'key_share' -> 'KeyShare'"""
    return "".join(part.capitalize() for part in snake.split("_"))


def _to_snake_case(camel: str) -> str:
    """Convert CamelCase to snake_case. e.g. 'ClientHello' -> 'client_hello'"""
    result = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", camel)
    result = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", result)
    return result.lower()


def _is_snake_case(term: str) -> bool:
    """Check if term is snake_case (has underscore and lowercase chars)."""
    return "_" in term and any(c.islower() for c in term)


def _is_camel_case(term: str) -> bool:
    """Check if term has mid-word uppercase (CamelCase)."""
    return bool(re.search(r"[a-z][A-Z]", term))


def generate_variants(search_terms: list[SearchTerm]) -> list[SearchTerm]:
    """Add snake_case/CamelCase variants to each search term."""
    for st in search_terms:
        st.variants = [st.term]
        if _is_snake_case(st.term):
            camel = _to_camel_case(st.term)
            if camel != st.term:
                st.variants.append(camel)
        elif _is_camel_case(st.term):
            snake = _to_snake_case(st.term)
            if snake != st.term:
                st.variants.append(snake)
    return search_terms


def run_grep(
    search_terms: list[SearchTerm],
    source_root: str,
    search_dirs: list[str],
) -> list[GrepHit]:
    """Run case-insensitive grep for all terms across search directories."""
    hits: list[GrepHit] = []
    abs_dirs = [f"{source_root}/{d.rstrip('/')}" for d in search_dirs]

    for st in search_terms:
        for variant in st.variants:
            try:
                result = subprocess.run(
                    [
                        "grep", "-rni",
                        "--include=*.c", "--include=*.h",
                        variant,
                    ] + abs_dirs,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                continue

            if result.returncode not in (0, 1):
                continue

            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                # Parse grep output: file:line:text
                match = re.match(r"^(.+?):(\d+):(.*)$", line)
                if not match:
                    continue
                file_path = match.group(1)
                # Make path relative to source_root
                if file_path.startswith(source_root):
                    file_path = file_path[len(source_root):].lstrip("/")
                hits.append(GrepHit(
                    file_path=file_path,
                    line_number=int(match.group(2)),
                    line_text=match.group(3).strip(),
                    matched_term=st.term,
                    categories=st.categories,
                ))

    return hits
