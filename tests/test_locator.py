"""Tests for the localization pipeline."""

import json
from pathlib import Path

import pytest

from spectrace.locator import localize_rule, write_localization


@pytest.fixture
def mock_codebase(tmp_path):
    """Create a tiny mock C codebase with known search terms."""
    src_dir = tmp_path / "ssl"
    src_dir.mkdir()

    (src_dir / "handshake.c").write_text("""\
#include "handshake.h"

/* Process ClientHello key_share extension */
int tls_parse_ctos_key_share(SSL *s, PACKET *pkt) {
    /* Check supported_groups */
    if (!check_group(s, group_id)) {
        SSLfatal(s, SSL_AD_ILLEGAL_PARAMETER, "bad group");
        return 0;
    }
    return 1;
}

/* Handle HelloRetryRequest selected_group */
int tls_handle_hrr_key_share(SSL *s) {
    /* Verify selected_group is in supported_groups */
    if (!verify_selected_group(s)) {
        SSLfatal(s, SSL_AD_ILLEGAL_PARAMETER, "mismatch");
        return 0;
    }
    return 1;
}

/* Unrelated function */
int tls_setup_buffers(SSL *s) {
    return allocate_buffers(s);
}
""")

    (src_dir / "alert.c").write_text("""\
/* Alert handling */
void send_alert(SSL *s, int alert_type) {
    if (alert_type == SSL_AD_ILLEGAL_PARAMETER) {
        log_alert("illegal_parameter");
    }
}
""")

    return str(tmp_path)


SAMPLE_RULE = {
    "rule_id": "rfc8446-4.2.8-R05",
    "rule_type": "consistency_check",
    "checkability": "medium",
    "protocol_keywords": {
        "message_types": ["ClientHello", "HelloRetryRequest"],
        "field_names": ["key_share", "supported_groups", "selected_group"],
        "extension_names": ["key_share", "supported_groups"],
        "alert_names": ["illegal_parameter"],
        "modes_or_conditions": [],
    },
}


def test_localize_rule_finds_candidates(mock_codebase):
    result = localize_rule(SAMPLE_RULE, mock_codebase, ["ssl/"])

    assert result["rule_id"] == "rfc8446-4.2.8-R05"
    assert len(result["candidates"]) > 0
    assert result["stats"]["total_grep_hits"] > 0


def test_localize_rule_ranks_by_distinct_terms(mock_codebase):
    result = localize_rule(SAMPLE_RULE, mock_codebase, ["ssl/"])

    candidates = result["candidates"]
    if len(candidates) >= 2:
        # First candidate should have >= distinct terms as second
        assert candidates[0]["distinct_terms_matched"] >= candidates[1]["distinct_terms_matched"]


def test_localize_rule_captures_metadata(mock_codebase):
    result = localize_rule(SAMPLE_RULE, mock_codebase, ["ssl/"])

    for c in result["candidates"]:
        meta = c["metadata"]
        assert "category_breadth" in meta
        assert "categories_present" in meta
        assert "function_name_match" in meta
        assert "terms_matched" in meta
        assert isinstance(meta["categories_present"], list)


def test_localize_rule_empty_keywords(mock_codebase):
    rule = {
        "rule_id": "rfc8446-4.2.8-R99",
        "rule_type": "algorithmic",
        "checkability": "not_checkable",
        "protocol_keywords": {
            "message_types": [],
            "field_names": [],
            "extension_names": [],
            "alert_names": [],
            "modes_or_conditions": [],
        },
    }
    result = localize_rule(rule, mock_codebase, ["ssl/"])
    assert result["candidates"] == []
    assert result["stats"]["total_grep_hits"] == 0


def test_write_localization(mock_codebase, tmp_path):
    result = localize_rule(SAMPLE_RULE, mock_codebase, ["ssl/"])
    out_dir = tmp_path / "locations"

    json_path = write_localization(result, mock_codebase, out_dir)

    assert json_path.exists()
    data = json.loads(json_path.read_text())
    assert data["rule_id"] == "rfc8446-4.2.8-R05"

    # Check that code files were written
    code_dir = out_dir / "code"
    code_files = list(code_dir.glob("*.c"))
    assert len(code_files) == len(result["candidates"])

    # Check code file content has header
    if code_files:
        content = code_files[0].read_text()
        assert "// Source:" in content
        assert "// Function:" in content
        assert "// Rule: rfc8446-4.2.8-R05" in content
