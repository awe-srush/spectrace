"""Pydantic models for NormalizedRule and related types."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class RuleType(str, Enum):
    VALUE_CONSTRAINT = "value_constraint"
    PRESENCE_REQUIREMENT = "presence_requirement"
    CONSISTENCY_CHECK = "consistency_check"
    UNIQUENESS_CONSTRAINT = "uniqueness_constraint"
    CONDITIONAL_ACTION = "conditional_action"
    ORDERING_CONSTRAINT = "ordering_constraint"
    BEHAVIORAL_TOLERANCE = "behavioral_tolerance"
    MESSAGE_CONSTRUCTION = "message_construction"
    ALGORITHMIC = "algorithmic"


class NormativeKeyword(str, Enum):
    MUST = "MUST"
    MUST_NOT = "MUST NOT"
    SHOULD = "SHOULD"
    SHOULD_NOT = "SHOULD NOT"
    SHALL = "SHALL"
    SHALL_NOT = "SHALL NOT"
    MAY = "MAY"
    REQUIRED = "REQUIRED"
    RECOMMENDED = "RECOMMENDED"


class Entity(str, Enum):
    CLIENT = "client"
    SERVER = "server"
    BOTH = "both"
    ENDPOINT = "endpoint"
    MIDDLEBOX = "middlebox"
    SENDER = "sender"
    RECEIVER = "receiver"


class Checkability(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NOT_CHECKABLE = "not_checkable"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ProtocolKeywords(BaseModel):
    message_types: list[str] = []
    field_names: list[str] = []
    extension_names: list[str] = []
    alert_names: list[str] = []
    modes_or_conditions: list[str] = []


class NormalizedRule(BaseModel):
    rule_id: str
    source_section: str
    source_text: str
    normative_keyword: NormativeKeyword
    rule_type: RuleType
    rule_statement: str
    entity: Entity
    applies_when: str
    target_message: Optional[str] = None
    target_field: Optional[str] = None
    expected_value: Optional[str] = None
    related_fields: list[str] = []
    violation_alert: Optional[str] = None
    violation_alert_source: Optional[str] = None
    protocol_keywords: ProtocolKeywords
    checkability: Checkability
    checkability_rationale: str
    extraction_confidence: Confidence
    extraction_confidence_rationale: str
    cross_section_context_used: list[str] = []
    ambiguity_notes: Optional[str] = None
