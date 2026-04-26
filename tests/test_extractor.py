"""Tests for extractor module (mocks the Anthropic API)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from spectrace.extractor import extract_rules


def _mock_response(rules_json: str):
    """Create a mock Anthropic API response."""
    mock_resp = MagicMock()
    mock_content = MagicMock()
    mock_content.text = rules_json
    mock_resp.content = [mock_content]
    mock_resp.usage.input_tokens = 100
    mock_resp.usage.output_tokens = 200
    mock_resp.usage.cache_creation_input_tokens = 0
    mock_resp.usage.cache_read_input_tokens = 0
    return mock_resp


SAMPLE_RULES = [
    {
        "rule_id": "rfc8446-4.6.3-R01",
        "source_section": "4.6.3",
        "source_text": "Implementations that receive a KeyUpdate message prior to receiving a Finished message MUST terminate the connection with an \"unexpected_message\" alert.",
        "normative_keyword": "MUST",
        "rule_type": "conditional_action",
        "rule_statement": "If a KeyUpdate is received before Finished, MUST terminate with unexpected_message.",
        "entity": "both",
        "applies_when": "KeyUpdate received before Finished",
        "target_message": "KeyUpdate",
        "target_field": None,
        "expected_value": None,
        "related_fields": ["Finished"],
        "violation_alert": "unexpected_message",
        "violation_alert_source": "inline",
        "protocol_keywords": {
            "message_types": ["KeyUpdate", "Finished"],
            "field_names": [],
            "extension_names": [],
            "alert_names": ["unexpected_message"],
            "modes_or_conditions": [],
        },
        "checkability": "medium",
        "checkability_rationale": "Need to check handshake state tracking.",
        "extraction_confidence": "high",
        "extraction_confidence_rationale": "Unambiguous.",
        "cross_section_context_used": ["4.6.3"],
        "ambiguity_notes": None,
    }
]


@patch("spectrace.extractor.anthropic.Anthropic")
def test_extract_rules_basic(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _mock_response(json.dumps(SAMPLE_RULES))

    result = extract_rules("some context markdown")

    assert len(result.rules) == 1
    assert result.rules[0]["rule_id"] == "rfc8446-4.6.3-R01"
    assert result.rules[0]["normative_keyword"] == "MUST"
    assert result.input_tokens == 100
    assert result.output_tokens == 200
    assert result.total_tokens == 300


@patch("spectrace.extractor.anthropic.Anthropic")
def test_extract_rules_strips_code_fences(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    fenced = f"```json\n{json.dumps(SAMPLE_RULES)}\n```"
    mock_client.messages.create.return_value = _mock_response(fenced)

    result = extract_rules("some context")

    assert len(result.rules) == 1
    assert result.rules[0]["rule_id"] == "rfc8446-4.6.3-R01"


@patch("spectrace.extractor.anthropic.Anthropic")
def test_extract_rules_validates_pydantic(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    bad_rules = [{"rule_id": "test", "invalid_field": "x"}]
    mock_client.messages.create.return_value = _mock_response(json.dumps(bad_rules))

    with pytest.raises(Exception):
        extract_rules("some context")


@patch("spectrace.extractor.anthropic.Anthropic")
def test_extract_rules_passes_model(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _mock_response(json.dumps(SAMPLE_RULES))

    extract_rules("context", model="claude-opus-4-5-20250514")

    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["model"] == "claude-opus-4-5-20250514"
