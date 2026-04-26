"""Tests for storage module."""

import json
from pathlib import Path

import pytest

from spectrace.storage import (
    is_extracted,
    load_manifest,
    load_rules,
    save_rules,
    section_to_filename,
)


@pytest.fixture
def tmp_rules_dir(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    return rules_dir


def _sample_rules():
    return [
        {
            "rule_id": "rfc8446-4.2.8-R01",
            "source_section": "4.2.8",
            "source_text": "test rule",
            "normative_keyword": "MUST",
            "rule_type": "value_constraint",
            "rule_statement": "Test statement",
            "entity": "client",
            "applies_when": "Always",
            "protocol_keywords": {"message_types": [], "field_names": [], "extension_names": [], "alert_names": [], "modes_or_conditions": []},
            "checkability": "high",
            "checkability_rationale": "test",
            "extraction_confidence": "high",
            "extraction_confidence_rationale": "test",
        }
    ]


def test_section_to_filename():
    assert section_to_filename("4.2.8") == "rfc8446-4-2-8.json"
    assert section_to_filename("4.1.2", "rfc8446") == "rfc8446-4-1-2.json"


def test_save_and_load_roundtrip(tmp_rules_dir):
    rules = _sample_rules()
    save_rules(tmp_rules_dir, "4.2.8", rules, model="test-model")

    loaded = load_rules(tmp_rules_dir, "4.2.8")
    assert loaded == rules


def test_manifest_created_on_save(tmp_rules_dir):
    save_rules(tmp_rules_dir, "4.2.8", _sample_rules(), model="test-model")

    manifest = load_manifest(tmp_rules_dir)
    assert "4.2.8" in manifest["extracted_sections"]
    assert manifest["extracted_sections"]["4.2.8"]["rule_count"] == 1
    assert manifest["extracted_sections"]["4.2.8"]["model"] == "test-model"


def test_is_extracted(tmp_rules_dir):
    assert not is_extracted(tmp_rules_dir, "4.2.8")
    save_rules(tmp_rules_dir, "4.2.8", _sample_rules(), model="test-model")
    assert is_extracted(tmp_rules_dir, "4.2.8")


def test_load_nonexistent_section(tmp_rules_dir):
    with pytest.raises(FileNotFoundError):
        load_rules(tmp_rules_dir, "99.99")


def test_multiple_sections(tmp_rules_dir):
    save_rules(tmp_rules_dir, "4.2.8", _sample_rules(), model="m1")
    save_rules(tmp_rules_dir, "4.1.2", _sample_rules(), model="m2")

    manifest = load_manifest(tmp_rules_dir)
    assert len(manifest["extracted_sections"]) == 2
