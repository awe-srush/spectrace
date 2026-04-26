"""Tests for NormalizedRule pydantic models."""

import pytest
from pydantic import ValidationError

from spectrace.models import (
    Checkability,
    Confidence,
    Entity,
    NormativeKeyword,
    NormalizedRule,
    ProtocolKeywords,
    RuleType,
)


def _make_rule(**overrides):
    """Create a valid NormalizedRule dict with sensible defaults."""
    base = {
        "rule_id": "rfc8446-4.2.8-R01",
        "source_section": "4.2.8",
        "source_text": "the field MUST be set to 0x0303",
        "normative_keyword": "MUST",
        "rule_type": "value_constraint",
        "rule_statement": "The field MUST be 0x0303.",
        "entity": "client",
        "applies_when": "Constructing a ClientHello",
        "protocol_keywords": {
            "message_types": ["ClientHello"],
            "field_names": ["legacy_version"],
            "extension_names": [],
            "alert_names": [],
            "modes_or_conditions": [],
        },
        "checkability": "high",
        "checkability_rationale": "Direct value check",
        "extraction_confidence": "high",
        "extraction_confidence_rationale": "Unambiguous",
    }
    base.update(overrides)
    return base


def test_valid_rule_parses():
    rule = NormalizedRule(**_make_rule())
    assert rule.rule_id == "rfc8446-4.2.8-R01"
    assert rule.normative_keyword == NormativeKeyword.MUST
    assert rule.rule_type == RuleType.VALUE_CONSTRAINT
    assert rule.entity == Entity.CLIENT


def test_optional_fields_default_to_none():
    rule = NormalizedRule(**_make_rule())
    assert rule.target_message is None
    assert rule.target_field is None
    assert rule.expected_value is None
    assert rule.violation_alert is None
    assert rule.ambiguity_notes is None


def test_optional_fields_populated():
    rule = NormalizedRule(**_make_rule(
        target_message="ClientHello",
        target_field="legacy_version",
        expected_value="0x0303",
        violation_alert="illegal_parameter",
        violation_alert_source="inline",
    ))
    assert rule.target_message == "ClientHello"
    assert rule.violation_alert == "illegal_parameter"


def test_invalid_rule_type_rejected():
    with pytest.raises(ValidationError):
        NormalizedRule(**_make_rule(rule_type="invalid_type"))


def test_invalid_entity_rejected():
    with pytest.raises(ValidationError):
        NormalizedRule(**_make_rule(entity="nobody"))


def test_invalid_normative_keyword_rejected():
    with pytest.raises(ValidationError):
        NormalizedRule(**_make_rule(normative_keyword="COULD"))


def test_must_not_keyword():
    rule = NormalizedRule(**_make_rule(normative_keyword="MUST NOT"))
    assert rule.normative_keyword == NormativeKeyword.MUST_NOT


def test_protocol_keywords_defaults():
    rule = NormalizedRule(**_make_rule(protocol_keywords={}))
    assert rule.protocol_keywords.message_types == []
    assert rule.protocol_keywords.field_names == []


def test_related_fields_list():
    rule = NormalizedRule(**_make_rule(related_fields=["supported_groups", "key_share"]))
    assert len(rule.related_fields) == 2


def test_model_dump_roundtrip():
    rule = NormalizedRule(**_make_rule())
    data = rule.model_dump()
    rule2 = NormalizedRule(**data)
    assert rule == rule2
