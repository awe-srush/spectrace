"""Tests for checker module (mocks the Anthropic API)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from spectrace.checker import (
    build_focus_guidance,
    check_conformance,
    group_candidates_by_file,
    write_judgment,
    write_summary,
)


SAMPLE_RULE = {
    "rule_id": "rfc8446-4.2.8-R05",
    "source_section": "4.2.8",
    "source_text": "the client MUST verify...",
    "normative_keyword": "MUST",
    "rule_type": "consistency_check",
    "rule_statement": "Client must verify selected_group.",
    "entity": "client",
    "applies_when": "Receiving HelloRetryRequest",
    "checkability": "medium",
}

SAMPLE_CANDIDATES = [
    {
        "rank": 1,
        "file": "ssl/statem/extensions_clnt.c",
        "function": "tls_parse_stoc_key_share",
        "line_range": [2193, 2367],
        "hits": [
            {"term": "key_share", "line": 2195, "text": "/* key_share processing */"},
            {"term": "illegal_parameter", "line": 2250, "text": "SSLfatal(s, SSL_AD_ILLEGAL_PARAMETER)"},
        ],
    },
    {
        "rank": 2,
        "file": "ssl/statem/extensions_srvr.c",
        "function": "tls_parse_ctos_key_share",
        "line_range": [830, 1006],
        "hits": [
            {"term": "key_share", "line": 835, "text": "/* parse client key_share */"},
        ],
    },
]

SAMPLE_JUDGMENT_JSON = {
    "rule_id": "rfc8446-4.2.8-R05",
    "source_file": "ssl/statem/extensions_clnt.c",
    "primary_function": "tls_parse_stoc_key_share",
    "judgment": "conforms",
    "confidence": "high",
    "reasoning": "The function correctly verifies the selected_group.",
    "evidence": {
        "violating_lines": [],
        "conforming_lines": [2210],
        "key_code_snippet": "if (group_id != s->s3.group_id)",
        "expected_behavior": "Verify selected_group matches supported_groups",
        "paths_checked": 2,
        "paths_conforming": 2,
        "paths_violating": 0,
    },
    "context_used_beyond_primary_function": False,
}


def _mock_response(judgment_json: str):
    mock_resp = MagicMock()
    mock_content = MagicMock()
    mock_content.text = judgment_json
    mock_resp.content = [mock_content]
    mock_resp.usage.input_tokens = 3000
    mock_resp.usage.output_tokens = 400
    return mock_resp


def test_build_focus_guidance():
    guidance = build_focus_guidance(SAMPLE_CANDIDATES[:1])
    assert "tls_parse_stoc_key_share" in guidance
    assert "2193-2367" in guidance
    assert "key_share" in guidance


def test_group_candidates_by_file():
    localization = {"candidates": SAMPLE_CANDIDATES}
    by_file = group_candidates_by_file(localization)
    assert len(by_file) == 2
    assert "ssl/statem/extensions_clnt.c" in by_file
    assert len(by_file["ssl/statem/extensions_clnt.c"]) == 1


@patch("spectrace.checker.anthropic.Anthropic")
def test_check_conformance_basic(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _mock_response(
        json.dumps(SAMPLE_JUDGMENT_JSON)
    )

    result = check_conformance(
        SAMPLE_RULE,
        "int foo() { return 1; }",
        "ssl/statem/extensions_clnt.c",
        SAMPLE_CANDIDATES[:1],
    )

    assert result.judgment["judgment"] == "conforms"
    assert result.judgment["confidence"] == "high"
    assert result.usage["input"] == 3000
    assert result.usage["output"] == 400


@patch("spectrace.checker.anthropic.Anthropic")
def test_check_conformance_handles_code_fences(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    fenced = f"```json\n{json.dumps(SAMPLE_JUDGMENT_JSON)}\n```"
    mock_client.messages.create.return_value = _mock_response(fenced)

    result = check_conformance(
        SAMPLE_RULE, "code", "file.c", SAMPLE_CANDIDATES[:1]
    )
    assert result.judgment["judgment"] == "conforms"


@patch("spectrace.checker.anthropic.Anthropic")
def test_check_conformance_handles_bad_json(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _mock_response("not valid json {{{")

    result = check_conformance(
        SAMPLE_RULE, "code", "file.c", SAMPLE_CANDIDATES[:1]
    )
    assert result.judgment["judgment"] == "error"
    assert "Failed to parse" in result.judgment["reasoning"]


def test_write_judgment(tmp_path):
    path = write_judgment(SAMPLE_JUDGMENT_JSON, tmp_path)
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["judgment"] == "conforms"


def test_write_summary(tmp_path):
    judgments = [
        {**SAMPLE_JUDGMENT_JSON, "judgment": "conforms", "tokens_used": {"input": 100, "output": 50}},
        {**SAMPLE_JUDGMENT_JSON, "rule_id": "R02", "judgment": "violates",
         "primary_function": "foo", "confidence": "high",
         "reasoning": "Wrong alert sent",
         "tokens_used": {"input": 200, "output": 80}},
    ]
    path = write_summary(judgments, "test-model", tmp_path)
    assert path.exists()

    summary = json.loads(path.read_text())
    assert summary["total_judgments"] == 2
    assert summary["judgment_counts"]["conforms"] == 1
    assert summary["judgment_counts"]["violates"] == 1
    assert len(summary["violations"]) == 1
    assert summary["total_tokens"]["input"] == 300
