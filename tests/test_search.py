"""Tests for search module: term collection, variant generation, grep."""

from spectrace.search import (
    SearchTerm,
    collect_terms,
    generate_variants,
    _to_camel_case,
    _to_snake_case,
)


def test_collect_terms_basic():
    keywords = {
        "message_types": ["ClientHello"],
        "field_names": ["key_share"],
        "extension_names": ["key_share"],
        "alert_names": [],
        "modes_or_conditions": [],
    }
    terms = collect_terms(keywords)
    assert len(terms) == 2

    term_map = {t.term: t for t in terms}
    assert "ClientHello" in term_map
    assert "key_share" in term_map
    # key_share should have both categories
    assert "field_names" in term_map["key_share"].categories
    assert "extension_names" in term_map["key_share"].categories


def test_collect_terms_empty():
    keywords = {
        "message_types": [],
        "field_names": [],
        "extension_names": [],
        "alert_names": [],
        "modes_or_conditions": [],
    }
    terms = collect_terms(keywords)
    assert terms == []


def test_to_camel_case():
    assert _to_camel_case("key_share") == "KeyShare"
    assert _to_camel_case("client_hello") == "ClientHello"
    assert _to_camel_case("supported_groups") == "SupportedGroups"


def test_to_snake_case():
    assert _to_snake_case("ClientHello") == "client_hello"
    assert _to_snake_case("HelloRetryRequest") == "hello_retry_request"
    assert _to_snake_case("KeyShare") == "key_share"


def test_generate_variants_snake():
    terms = [SearchTerm(term="key_share", categories=["field_names"])]
    result = generate_variants(terms)
    assert "key_share" in result[0].variants
    assert "KeyShare" in result[0].variants


def test_generate_variants_camel():
    terms = [SearchTerm(term="ClientHello", categories=["message_types"])]
    result = generate_variants(terms)
    assert "ClientHello" in result[0].variants
    assert "client_hello" in result[0].variants


def test_generate_variants_allcaps():
    """ALL_CAPS terms should not generate a CamelCase variant."""
    terms = [SearchTerm(term="EC_DHE", categories=["modes_or_conditions"])]
    result = generate_variants(terms)
    # EC_DHE has underscore but no lowercase, so no camel variant
    assert result[0].variants == ["EC_DHE"]


def test_generate_variants_no_change_needed():
    """Single word terms stay as-is."""
    terms = [SearchTerm(term="Finished", categories=["message_types"])]
    result = generate_variants(terms)
    assert result[0].variants == ["Finished"]
