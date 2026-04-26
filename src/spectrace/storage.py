"""Read/write rule JSON files and track extraction state via manifest."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _manifest_path(rules_dir: Path) -> Path:
    return rules_dir / "_manifest.json"


def load_manifest(rules_dir: Path) -> dict[str, Any]:
    """Load the manifest file, or return a fresh one if it doesn't exist."""
    path = _manifest_path(rules_dir)
    if path.exists():
        return json.loads(path.read_text())
    return {"rfc_id": "rfc8446", "extracted_sections": {}}


def save_manifest(rules_dir: Path, manifest: dict[str, Any]) -> None:
    """Write the manifest file."""
    path = _manifest_path(rules_dir)
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def is_extracted(rules_dir: Path, section: str) -> bool:
    """Check if a section has already been extracted."""
    manifest = load_manifest(rules_dir)
    return section in manifest["extracted_sections"]


def section_to_filename(section: str, rfc_id: str = "rfc8446") -> str:
    """Convert a section ID to a filename. e.g. '4.2.8' -> 'rfc8446-4-2-8.json'"""
    return f"{rfc_id}-{section.replace('.', '-')}.json"


def save_rules(
    rules_dir: Path,
    section: str,
    rules: list[dict],
    model: str,
    rfc_id: str = "rfc8446",
    usage: dict[str, int] | None = None,
) -> Path:
    """Save extracted rules to a JSON file and update the manifest."""
    rules_dir.mkdir(parents=True, exist_ok=True)

    filename = section_to_filename(section, rfc_id)
    output_path = rules_dir / filename
    output_path.write_text(json.dumps(rules, indent=2) + "\n")

    # Update manifest
    manifest = load_manifest(rules_dir)
    manifest["rfc_id"] = rfc_id
    entry = {
        "filename": filename,
        "rule_count": len(rules),
        "model": model,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    if usage:
        entry["usage"] = usage
    manifest["extracted_sections"][section] = entry
    save_manifest(rules_dir, manifest)

    return output_path


def load_rules(rules_dir: Path, section: str, rfc_id: str = "rfc8446") -> list[dict]:
    """Load rules for a given section."""
    filename = section_to_filename(section, rfc_id)
    path = rules_dir / filename
    if not path.exists():
        raise FileNotFoundError(f"No rules file found for section {section}: {path}")
    return json.loads(path.read_text())
