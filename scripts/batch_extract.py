#!/usr/bin/env python3
"""
Batch extraction helper: reads rfckb context for each section and writes
rule JSONs. Designed to be used with Claude Code (not the API) —
the extraction is done by the LLM in the conversation, not via API calls.

Usage:
    python scripts/batch_extract.py --list          # list sections with normative keywords
    python scripts/batch_extract.py --context 4.2.8  # dump context for a section (for extraction)
    python scripts/batch_extract.py --save 4.2.8     # save rules from stdin for a section
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

KB_DIR = "/Users/srushti/Documents/01-SRUSHTI/software-engineering/SpecTrace_Project/rfc_knowledge_base/kb/rfc8446"
RULES_DIR = Path(__file__).parent.parent / "rules"
MODEL = "claude-opus-4-6"
RFC_ID = "rfc8446"


def list_normative_sections():
    """List all sections that contain normative keywords."""
    kb_path = Path(KB_DIR)
    normative_re = re.compile(r'\b(MUST|SHOULD|SHALL|REQUIRED|RECOMMENDED)\b')
    sections = []

    for f in sorted(kb_path.glob("rfc8446-*.md")):
        section_id = f.stem.replace("rfc8446-", "").replace("-", ".")
        text = f.read_text()
        matches = normative_re.findall(text)
        if matches:
            # Check if already extracted
            rules_file = RULES_DIR / f"{RFC_ID}-{section_id.replace('.', '-')}.json"
            status = "done" if rules_file.exists() else "pending"
            sections.append((section_id, len(matches), status))

    return sections


def get_context(section_id: str) -> str:
    """Get rfckb context for a section."""
    try:
        from rfckb.query import get_context as rfckb_get_context
        return rfckb_get_context(kb_dir=KB_DIR, section_id=section_id)
    except ImportError:
        import subprocess
        result = subprocess.run(
            ["rfckb", "context", "--kb", KB_DIR, "--section", section_id],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"Error: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        return result.stdout


def save_rules(section_id: str, rules: list[dict]):
    """Save extracted rules for a section."""
    RULES_DIR.mkdir(parents=True, exist_ok=True)

    # Add model field to each rule
    for rule in rules:
        rule["model"] = MODEL

    filename = f"{RFC_ID}-{section_id.replace('.', '-')}.json"
    out_path = RULES_DIR / filename
    out_path.write_text(json.dumps(rules, indent=2) + "\n")

    # Update manifest
    manifest_path = RULES_DIR / "_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = {"rfc_id": RFC_ID, "extracted_sections": {}}

    manifest["extracted_sections"][section_id] = {
        "filename": filename,
        "rule_count": len(rules),
        "model": MODEL,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"Saved {len(rules)} rules → {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Batch rule extraction helper")
    parser.add_argument("--list", action="store_true", help="List normative sections")
    parser.add_argument("--context", metavar="SECTION", help="Dump context for a section")
    parser.add_argument("--save", metavar="SECTION", help="Save rules from stdin JSON")
    parser.add_argument("--status", action="store_true", help="Show extraction progress")
    args = parser.parse_args()

    if args.list or args.status:
        sections = list_normative_sections()
        done = sum(1 for _, _, s in sections if s == "done")
        total = len(sections)
        print(f"Normative sections: {total} total, {done} extracted, {total - done} pending\n")
        print(f"{'Section':<20} {'Keywords':<10} {'Status'}")
        print("-" * 45)
        for sec_id, count, status in sections:
            marker = "✓" if status == "done" else " "
            print(f"{sec_id:<20} {count:<10} {marker} {status}")

    elif args.context:
        context = get_context(args.context)
        print(context)

    elif args.save:
        raw = sys.stdin.read()
        rules = json.loads(raw)
        if not isinstance(rules, list):
            rules = [rules]
        save_rules(args.save, rules)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
