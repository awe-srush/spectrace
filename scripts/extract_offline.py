#!/usr/bin/env python3
"""
Offline extraction script — designed for Claude Code to use instead of the API.

Same pipeline as `spectrace extract`, but instead of calling the Anthropic API,
it dumps the context for Claude Code to read and accepts extracted rules as JSON.

Usage:
    # Step 1: Prepare contexts for all pending sections
    python scripts/extract_offline.py prepare

    # Step 2: Claude Code reads contexts from contexts/ and writes rules to rules/
    #         (Claude writes the JSON files directly)

    # Step 3: Register all new rule files in the manifest
    python scripts/extract_offline.py register

    # Other commands:
    python scripts/extract_offline.py status          # show progress
    python scripts/extract_offline.py prepare --section 4.1.2  # prepare one section
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

KB_DIR = "/Users/srushti/Documents/01-SRUSHTI/software-engineering/SpecTrace_Project/rfc_knowledge_base/kb/rfc8446"
RULES_DIR = Path(__file__).parent.parent / "rules"
CONTEXTS_DIR = Path(__file__).parent.parent / "contexts"
RFC_ID = "rfc8446"
MODEL = "claude-opus-4-6"


def get_all_sections() -> list[str]:
    """Get all section IDs from the knowledge base."""
    kb = Path(KB_DIR)
    sections = []
    for f in sorted(kb.glob("rfc8446-*.md")):
        if f.name == "_index.yaml":
            continue
        sec = f.stem.replace("rfc8446-", "").replace("-", ".")
        sections.append(sec)
    return sections


def get_normative_sections() -> list[tuple[str, int]]:
    """Get sections that contain normative keywords, with counts."""
    kb = Path(KB_DIR)
    normative_re = re.compile(r'\b(MUST|MUST NOT|SHOULD|SHOULD NOT|SHALL|SHALL NOT|REQUIRED|RECOMMENDED)\b')
    results = []
    for f in sorted(kb.glob("rfc8446-*.md")):
        sec = f.stem.replace("rfc8446-", "").replace("-", ".")
        matches = normative_re.findall(f.read_text())
        if matches:
            results.append((sec, len(matches)))
    return results


def get_context(section_id: str) -> str:
    """Get rfckb context for a section via CLI."""
    import subprocess
    r = subprocess.run(
        ["rfckb", "context", "--kb", KB_DIR, "--section", section_id],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"Error getting context for {section_id}: {r.stderr}", file=sys.stderr)
        return ""
    return r.stdout


def is_extracted(section_id: str) -> bool:
    """Check if a section already has a rules file."""
    filename = f"{RFC_ID}-{section_id.replace('.', '-')}.json"
    return (RULES_DIR / filename).exists()


def prepare(section_id: str = None):
    """Dump rfckb contexts to contexts/ directory for Claude Code to read."""
    CONTEXTS_DIR.mkdir(parents=True, exist_ok=True)

    if section_id:
        sections = [(section_id, 0)]
    else:
        sections = get_normative_sections()

    prepared = 0
    skipped = 0
    for sec, _ in sections:
        if is_extracted(sec):
            skipped += 1
            continue
        ctx = get_context(sec)
        if not ctx:
            continue
        out = CONTEXTS_DIR / f"{sec.replace('.', '-')}.md"
        out.write_text(ctx)
        prepared += 1

    print(f"Prepared {prepared} contexts in {CONTEXTS_DIR}/")
    if skipped:
        print(f"Skipped {skipped} already-extracted sections")


def register():
    """Scan rules/ for new JSON files and update the manifest."""
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = RULES_DIR / "_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = {"rfc_id": RFC_ID, "extracted_sections": {}}

    registered = 0
    for f in sorted(RULES_DIR.glob("rfc8446-*.json")):
        if f.name.startswith("_"):
            continue
        # Derive section ID from filename: rfc8446-4-1-2.json -> 4.1.2
        sec = f.stem.replace("rfc8446-", "").replace("-", ".")

        rules = json.loads(f.read_text())

        # Check if model field is present in rules, add if missing
        for rule in rules:
            rule.setdefault("model", MODEL)
        f.write_text(json.dumps(rules, indent=2) + "\n")

        if sec not in manifest["extracted_sections"]:
            manifest["extracted_sections"][sec] = {
                "filename": f.name,
                "rule_count": len(rules),
                "model": MODEL,
                "extracted_at": datetime.now(timezone.utc).isoformat(),
            }
            registered += 1
            print(f"  Registered §{sec}: {len(rules)} rules")

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\nRegistered {registered} new sections in manifest")


def status():
    """Show extraction progress."""
    normative = get_normative_sections()
    done = []
    pending = []
    for sec, count in normative:
        if is_extracted(sec):
            # Count rules in file
            filename = f"{RFC_ID}-{sec.replace('.', '-')}.json"
            rules = json.loads((RULES_DIR / filename).read_text())
            done.append((sec, count, len(rules)))
        else:
            pending.append((sec, count))

    total = len(normative)
    print(f"Extraction progress: {len(done)}/{total} sections done\n")

    if done:
        print(f"{'Section':<20} {'Keywords':<10} {'Rules':<8} Status")
        print("-" * 50)
        for sec, kw, rc in done:
            print(f"{sec:<20} {kw:<10} {rc:<8} done")

    if pending:
        if done:
            print()
        print(f"{'Section':<20} {'Keywords':<10} Status")
        print("-" * 40)
        for sec, kw in pending:
            print(f"{sec:<20} {kw:<10} pending")


def main():
    parser = argparse.ArgumentParser(description="Offline rule extraction helper")
    parser.add_argument("command", choices=["prepare", "register", "status"],
                        help="prepare: dump contexts, register: update manifest, status: show progress")
    parser.add_argument("--section", help="Process only this section (with prepare)")
    args = parser.parse_args()

    if args.command == "prepare":
        prepare(args.section)
    elif args.command == "register":
        register()
    elif args.command == "status":
        status()


if __name__ == "__main__":
    main()
