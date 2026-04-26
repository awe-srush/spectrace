"""CLI entry point for SpecTrace."""

import json
import subprocess
import time
from pathlib import Path

import click

from spectrace.checker import group_candidates_by_file, write_judgment, write_summary
from spectrace.extractor import extract_rules
from spectrace.locator import localize_rule, write_localization
from spectrace.storage import is_extracted, load_manifest, load_rules, save_rules

DEFAULT_MODEL = "claude-sonnet-4-6"


def _get_context_from_kb(kb_path: str, section: str) -> str:
    """Get context from rfckb, trying Python API first, then CLI fallback."""
    try:
        from rfckb.query import get_context

        return get_context(kb_dir=kb_path, section_id=section)
    except ImportError:
        pass

    result = subprocess.run(
        ["rfckb", "context", "--kb", kb_path, "--section", section],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise click.ClickException(f"rfckb context failed: {result.stderr}")
    return result.stdout


@click.group()
def cli():
    """SpecTrace — structured RFC conformance rule extraction."""
    pass


@cli.command()
@click.option("--context", "context_path", type=click.Path(exists=True), help="Path to rfckb context markdown file")
@click.option("--kb", "kb_path", type=click.Path(exists=True), help="Path to rfckb knowledge base directory")
@click.option("--section", help="Section ID to extract (required with --kb)")
@click.option("--output", "output_dir", type=click.Path(), default="rules/", help="Output directory for rule JSONs")
@click.option("--model", default=DEFAULT_MODEL, help="Anthropic model to use")
@click.option("--force", is_flag=True, help="Re-extract even if section already exists")
def extract(context_path, kb_path, section, output_dir, model, force):
    """Extract normative rules from an RFC section."""
    rules_dir = Path(output_dir)

    # Get the context markdown
    if context_path:
        context_markdown = Path(context_path).read_text()
        # Try to infer section from the context header
        if not section:
            for line in context_markdown.split("\n")[:5]:
                if "§" in line:
                    # Extract section id like "4.2.8" from "§4.2.8"
                    import re

                    match = re.search(r"§([\d.]+)", line)
                    if match:
                        section = match.group(1)
                        break
            if not section:
                raise click.ClickException("Could not infer section ID from context. Use --section.")
    elif kb_path and section:
        context_markdown = _get_context_from_kb(kb_path, section)
    else:
        raise click.ClickException("Provide either --context or both --kb and --section.")

    # Check if already extracted
    if not force and is_extracted(rules_dir, section):
        click.echo(f"Section {section} already extracted. Use --force to re-extract.")
        return

    click.echo(f"Extracting rules from §{section} using {model}...")
    result = extract_rules(context_markdown, model=model)

    output_path = save_rules(rules_dir, section, result.rules, model=model, usage=result.usage)
    click.echo(f"Extracted {len(result.rules)} rules → {output_path}")
    click.echo(f"Tokens: {result.input_tokens} input + {result.output_tokens} output = {result.total_tokens} total")


@cli.command("list")
@click.option("--rules-dir", type=click.Path(exists=True), default="rules/", help="Rules directory")
def list_sections(rules_dir):
    """List already-extracted sections."""
    manifest = load_manifest(Path(rules_dir))
    sections = manifest.get("extracted_sections", {})

    if not sections:
        click.echo("No sections extracted yet.")
        return

    click.echo(f"RFC: {manifest.get('rfc_id', 'unknown')}")
    click.echo(f"{'Section':<12} {'Rules':<8} {'Model':<30} {'Extracted At'}")
    click.echo("-" * 80)
    for sec_id, info in sorted(sections.items()):
        click.echo(f"{sec_id:<12} {info['rule_count']:<8} {info['model']:<30} {info['extracted_at']}")


@cli.command()
@click.option("--rules-dir", type=click.Path(exists=True), default="rules/", help="Rules directory")
@click.option("--section", required=True, help="Section ID to show")
def show(rules_dir, section):
    """Show extracted rules for a section."""
    try:
        rules = load_rules(Path(rules_dir), section)
    except FileNotFoundError as e:
        raise click.ClickException(str(e))

    click.echo(json.dumps(rules, indent=2))


@cli.command()
@click.option("--rules", "rules_path", type=click.Path(exists=True), help="Path to a single rule JSON file")
@click.option("--rules-dir", type=click.Path(exists=True), help="Path to directory of rule JSON files")
@click.option("--rule-id", help="Process only this specific rule ID")
@click.option("--source", required=True, type=click.Path(exists=True), help="Root of the target codebase")
@click.option("--search-dirs", required=True, multiple=True, help="Directories to search, relative to --source")
@click.option("--output", "output_dir", type=click.Path(), default="locations/", help="Output directory")
@click.option("--top-k", default=10, help="Number of top candidates to return per rule")
def localize(rules_path, rules_dir, rule_id, source, search_dirs, output_dir, top_k):
    """Locate candidate code for extracted rules (deterministic, no LLM)."""
    out_path = Path(output_dir)

    # Load rules
    all_rules = []
    if rules_path:
        all_rules = json.loads(Path(rules_path).read_text())
    elif rules_dir:
        rules_dir_path = Path(rules_dir)
        for f in sorted(rules_dir_path.glob("*.json")):
            if f.name.startswith("_"):
                continue
            all_rules.extend(json.loads(f.read_text()))
    else:
        raise click.ClickException("Provide either --rules or --rules-dir.")

    # Filter to specific rule if requested
    if rule_id:
        all_rules = [r for r in all_rules if r["rule_id"] == rule_id]
        if not all_rules:
            raise click.ClickException(f"Rule {rule_id} not found.")

    click.echo(f"Localizing {len(all_rules)} rule(s) in {source}...")

    for rule in all_rules:
        rid = rule["rule_id"]
        result = localize_rule(rule, source, list(search_dirs), top_k=top_k)
        json_path = write_localization(result, source, out_path)
        n_candidates = len(result["candidates"])
        n_hits = result["stats"]["total_grep_hits"]
        click.echo(f"  {rid}: {n_candidates} candidates from {n_hits} grep hits → {json_path}")

    click.echo("Done.")


@cli.command()
@click.option("--rules", "rules_path", type=click.Path(exists=True), help="Path to a single rule JSON file")
@click.option("--rules-dir", type=click.Path(exists=True), help="Path to directory of rule JSON files")
@click.option("--rule-id", help="Check only this specific rule ID")
@click.option("--checkability", type=click.Choice(["high", "medium", "low"]), help="Only check rules with this checkability level")
@click.option("--keyword", multiple=True, help="Only check rules with these normative keywords (e.g. MUST 'MUST NOT')")
@click.option("--locations", "locations_dir", required=True, type=click.Path(exists=True), help="Localization output directory")
@click.option("--source", required=True, type=click.Path(exists=True), help="Root of the target codebase")
@click.option("--search-dirs", required=True, multiple=True, help="Directories to index for cross-file navigation, relative to --source")
@click.option("--output", "output_dir", type=click.Path(), default="results/", help="Output directory for judgments")
@click.option("--model", default=DEFAULT_MODEL, help="Anthropic model to use")
@click.option("--top-k", default=3, help="Max source files to check per rule (by candidate rank)")
@click.option("--max-tool-calls", default=10, help="Max tool calls per judgment")
def check(rules_path, rules_dir, rule_id, checkability, keyword, locations_dir, source, search_dirs, output_dir, model, top_k, max_tool_calls):
    """Check code conformance against extracted rules (LLM with tool-use)."""
    from spectrace.checker import check_conformance
    from spectrace.code_index import CodeIndex

    out_path = Path(output_dir)
    loc_path = Path(locations_dir)

    # Load rules
    all_rules = []
    if rules_path:
        all_rules = json.loads(Path(rules_path).read_text())
    elif rules_dir:
        rules_dir_path = Path(rules_dir)
        for f in sorted(rules_dir_path.glob("*.json")):
            if f.name.startswith("_"):
                continue
            all_rules.extend(json.loads(f.read_text()))
    else:
        raise click.ClickException("Provide either --rules or --rules-dir.")

    # Filter by rule ID
    if rule_id:
        all_rules = [r for r in all_rules if r["rule_id"] == rule_id]
        if not all_rules:
            raise click.ClickException(f"Rule {rule_id} not found.")

    # Filter by checkability
    if checkability:
        all_rules = [r for r in all_rules if r.get("checkability") == checkability]

    # Filter by normative keyword
    if keyword:
        all_rules = [r for r in all_rules if r.get("normative_keyword") in keyword]

    if not all_rules:
        click.echo("No rules match the given filters.")
        return

    # Build the code index
    click.echo(f"Building code index for {source}...")
    code_index = CodeIndex(source, list(search_dirs))
    click.echo(f"Indexed {code_index.file_count} files, {code_index.function_count} functions.")

    click.echo(f"Checking {len(all_rules)} rule(s) using {model}...")

    all_judgments = []
    skipped_rules = []

    for rule in all_rules:
        rid = rule["rule_id"]
        safe_id = rid.replace(".", "-")

        # Find localization JSON
        loc_file = loc_path / f"{safe_id}.json"
        if not loc_file.exists():
            click.echo(f"  {rid}: no localization found, skipping")
            skipped_rules.append(rid)
            continue

        localization = json.loads(loc_file.read_text())

        if not localization.get("candidates"):
            click.echo(f"  {rid}: no candidates, skipping")
            skipped_rules.append(rid)
            continue

        # Group candidates by file, limit to top-k files
        by_file = group_candidates_by_file(localization)
        # Order files by best candidate rank in each
        files_ordered = sorted(by_file.keys(), key=lambda f: by_file[f][0]["rank"])
        files_to_check = files_ordered[:top_k]

        results = []
        for src_file in files_to_check:
            candidates = by_file[src_file]

            # Skip if judgment already exists
            safe_file = Path(src_file).stem
            existing = out_path / f"{safe_id}_{safe_file}.json"
            if existing.exists():
                click.echo(f"  {rid} → {src_file}: already checked, skipping")
                all_judgments.append(json.loads(existing.read_text()))
                continue

            result = check_conformance(
                rule, src_file, candidates, code_index,
                model=model, max_tool_calls=max_tool_calls,
            )
            results.append(result)
            # Brief throttle between API calls
            time.sleep(2)

        for r in results:
            j = r.judgment
            write_judgment(j, out_path)
            all_judgments.append(j)
            verdict = j.get("judgment", "error")
            confidence = j.get("confidence", "?")
            tokens = r.usage
            tc = j.get("tool_calls_made", 0)
            click.echo(
                f"  {rid} → {j.get('source_file', '?')}: "
                f"{verdict} ({confidence}) "
                f"[{tokens['input']}+{tokens['output']} tokens, {tc} tool calls]"
            )

    # Write summary
    if all_judgments:
        summary_path = write_summary(all_judgments, model, out_path, skipped_rules)
        click.echo(f"\nSummary → {summary_path}")

        # Print quick summary
        summary = json.loads(summary_path.read_text())
        click.echo(f"  {summary['total_judgments']} judgments across {summary['total_rules_checked']} rules")
        for jtype, count in summary["judgment_counts"].items():
            if count > 0:
                click.echo(f"  {jtype}: {count}")
        if summary.get("total_tool_calls"):
            click.echo(f"  Total tool calls: {summary['total_tool_calls']}")
        if summary["violations"]:
            click.echo(f"\n  VIOLATIONS FOUND: {len(summary['violations'])}")
            for v in summary["violations"]:
                click.echo(f"    - {v['rule_id']} in {v['function']} ({v['source_file']})")

    click.echo("Done.")


if __name__ == "__main__":
    cli()
