# NormalizedRule Extraction Schema — v1.1

You are extracting structured rules from an RFC section. This document defines the
output schema and the rule taxonomy. For each MUST, MUST NOT, SHOULD, SHOULD NOT,
SHALL, SHALL NOT, REQUIRED, or RECOMMENDED statement in the RFC text, produce one
NormalizedRule JSON object.

## Rule type taxonomy

Every rule has a structural shape. Classify each rule into exactly one of the following
types. When a rule could fit multiple types, choose the type that best captures the
**essential constraint** — the thing an implementation could violate.

### value_constraint
A field or parameter must equal, not equal, or fall within a specific range of values.
The rule specifies a concrete expected value or valid set.

**Use when:** the rule says "field X MUST be set to Y" or "field X MUST NOT be Z" or
"field X MUST be in the range [A, B]."

**Examples:**
- "the legacy_version field MUST be set to 0x0303"
- "this vector MUST contain exactly one byte, set to zero"
- "The length MUST NOT exceed 2^14 + 256 bytes"

**Checkability:** typically HIGH — look for where the field is assigned or validated.

### presence_requirement
A field, extension, or message element must be present or absent under specified
conditions. The rule is about existence, not about specific values.

**Use when:** the rule says "MUST contain extension X" or "MUST NOT send X when Y" or
"MUST include field X" or "X is REQUIRED."

**Examples:**
- "MUST NOT send a KeyShareEntry when using the psk_ke PskKeyExchangeMode"
- "it MUST also contain a 'key_share' extension"
- "'supported_versions' is REQUIRED for all ClientHello messages"

**Checkability:** typically HIGH — look for conditional inclusion/exclusion of fields.

### consistency_check
Two or more fields, extensions, or messages must agree on some property. The rule
constrains a relationship between values, not a single value in isolation.

**Use when:** the rule says "field X MUST match field Y" or "X MUST correspond to Y" or
"X MUST be in the set offered by Y" or "X and Y MUST be the same."

**Examples:**
- "This value MUST be in the same group as the KeyShareEntry offered by the client"
- "the client MUST verify that the selected NamedGroup in the ServerHello is the same as that in the HelloRetryRequest"
- "Each KeyShareEntry MUST correspond to a group offered in the supported_groups extension"

**Checkability:** MEDIUM — requires tracing two related values, possibly across functions.

### uniqueness_constraint
A list or set must not contain duplicates, or each element must be distinct by some
property.

**Use when:** the rule says "MUST NOT offer multiple X for the same Y" or "each X MUST
be unique."

**Examples:**
- "Clients MUST NOT offer multiple KeyShareEntry values for the same group"

**Checkability:** HIGH — look for duplicate-checking logic on list construction.

### conditional_action
If a condition is met, the implementation must perform a specific action. The action is
typically sending an alert, aborting the handshake, or performing a validation check.
The condition is the trigger; the action is the obligation.

**Use when:** the rule has an if-then structure: "if X, then MUST do Y" or "upon
receiving X, MUST do Y." The action is a discrete, one-time response to a trigger.

**Do NOT use** for ongoing behavioral changes after a trigger (use ordering_constraint
instead) or for specifying what to include in messages (use message_construction).

**Examples:**
- "If this check fails, the client MUST abort the handshake with an 'illegal_parameter' alert"
- "If an implementation receives any other value, it MUST terminate the connection with an 'illegal_parameter' alert"
- "if a server has negotiated TLS 1.3 and receives a ClientHello at any other time, it MUST terminate the connection with an 'unexpected_message' alert"

**Checkability:** HIGH when alert-based (look for alert-sending code paths); MEDIUM when
the action is a validation (need to verify the check exists).

### ordering_constraint
A rule that specifies temporal or sequential relationships between actions, messages,
or state transitions. "MUST do X before Y," "after X, MUST do Y for all subsequent
traffic," "MUST receive X before accepting Y."

**Use when:** the essential constraint is about **when** or **in what order** things happen,
not just whether they happen. The word "before," "after," "prior to," "subsequent,"
or "until" in the rule text is a strong signal.

**Do NOT confuse** with conditional_action. A conditional_action says "if X, do Y" as a
one-time response. An ordering_constraint says "X must happen before/after Y" as a
sequential relationship.

**Examples:**
- "the receiver MUST send a KeyUpdate of its own prior to sending its next Application Data record"
- "After sending a KeyUpdate message, the sender SHALL send all its traffic using the next generation of keys"
- "both sides MUST enforce that a KeyUpdate with the old key is received before accepting any messages encrypted with the new key"
- "Both sender and receiver MUST encrypt their KeyUpdate messages with the old keys"

**Checkability:** typically LOW — verifying ordering requires understanding runtime
control flow, not just static code structure.

### behavioral_tolerance
The implementation must accept, ignore, or gracefully handle something rather than
reject it. These rules constrain what an implementation must NOT treat as an error.

**Use when:** the rule says "MUST ignore X" or "MUST accept X" or "MUST process X as
usual" despite some unexpected or unrecognized input.

**Examples:**
- "the server MUST ignore those cipher suites and process the remaining ones as usual"
- "Servers MUST ignore unrecognized extensions"

**Checkability:** LOW — verifying that code does NOT reject something is harder than
verifying it DOES reject. Requires confirming absence of error-handling code paths
for the specified condition.

### message_construction
A rule about what to include, exclude, or modify when constructing or sending a
specific protocol message. The constraint is on the content or structure of a
message being built.

**Use when:** the rule specifies how to assemble a message: "MUST include X in message Y,"
"MUST replace X with Y," "MUST set field X to value Y when constructing message Z."

**Note:** If the rule is primarily about a field having a specific value, prefer
value_constraint. Use message_construction when the rule is about the act of building
or modifying the message, especially when multiple fields or structural changes are
involved.

**Examples:**
- "the client MUST replace the original 'key_share' extension with one containing only a new KeyShareEntry for the group indicated in the selected_group field"
- "the client MUST send the same ClientHello without modification, except as follows: [list]"

**Checkability:** MEDIUM — need to find message-construction code and verify the right
fields are included.

### algorithmic
The implementation must compute, generate, or derive something in a specific way.
The constraint is about the method of computation, not the result.

**Use when:** the rule says "MUST generate X independently" or "MUST compute X using
procedure Y" or "MUST derive X from Y."

**Examples:**
- "The key_exchange values for each KeyShareEntry MUST be generated independently"
- "MUST compute the Diffie-Hellman shared secret and abort if all-zero"

**Checkability:** typically NOT_CHECKABLE — implementation intent and computation method
cannot be verified by examining code structure alone. Exception: some algorithmic rules
have verifiable postconditions (e.g., "abort if all-zero") which are checkable as
conditional_action.

---

## JSON Schema

For each normative statement (MUST/SHOULD/SHALL and their negatives), produce one JSON
object with the following fields. All "required" fields must be present. "Optional"
fields should be populated when applicable; use null when not applicable.

```json
{
  "rule_id": "(required) string — Stable identifier. Format: rfc{N}-{section}-R{seq}. Example: rfc8446-4.2.8-R03",

  "source_section": "(required) string — Section ID where the rule text appears. Example: 4.2.8",

  "source_text": "(required) string — Verbatim RFC text containing the rule. Copy the exact sentence(s) from the RFC. A human must be able to find this text in the original document.",

  "normative_keyword": "(required) string — The RFC 2119 keyword. One of: MUST, MUST NOT, SHOULD, SHOULD NOT, SHALL, SHALL NOT, MAY, REQUIRED, RECOMMENDED.",

  "rule_type": "(required) string — One of: value_constraint, presence_requirement, consistency_check, uniqueness_constraint, conditional_action, ordering_constraint, behavioral_tolerance, message_construction, algorithmic.",

  "rule_statement": "(required) string — The rule restated as a clear, atomic, structured sentence. Must be unambiguous enough that an engineer could check it against code. Include the entity, condition, constraint, and consequence if applicable.",

  "entity": "(required) string — Who is bound by this rule. One of: client, server, both, endpoint, middlebox, sender, receiver.",

  "applies_when": "(required) string — Precondition for the rule to be active. Describe the handshake state, message type, mode, or condition. Example: 'When constructing a TLS 1.3 ClientHello' or 'Upon receiving a KeyUpdate message before Finished'.",

  "target_message": "(optional, nullable) string — The protocol message this rule constrains. Example: ClientHello, ServerHello, KeyUpdate. Null if not message-specific.",

  "target_field": "(optional, nullable) string — The specific protocol field being constrained. Example: legacy_version, key_share, request_update. Null if not field-specific.",

  "expected_value": "(optional, nullable) string — For value_constraint: what the value should be. For presence_requirement: 'present' or 'absent'. Null for other types.",

  "related_fields": "(optional) array of strings — For consistency_check: other fields that must agree. For ordering_constraint: the other action/message in the ordering relationship. Empty array if not applicable.",

  "violation_alert": "(optional, nullable) string — The alert name to send on violation, if stated anywhere in the provided context. Example: illegal_parameter, unexpected_message. Null if no alert consequence is found.",

  "violation_alert_source": "(optional, nullable) string — Where the alert is stated. 'inline' if in the same sentence as the rule. A section ID (e.g., '6.2') if stated in a different section that was provided as context. Null if no alert found.",

  "protocol_keywords": "(required) object — Typed keyword slots for code localization. Populate every slot that applies. These keywords will be used to search the target codebase.",
  "protocol_keywords.message_types": "array of strings — e.g., ['ClientHello', 'ServerHello', 'KeyUpdate']",
  "protocol_keywords.field_names": "array of strings — e.g., ['key_share', 'request_update', 'legacy_version']",
  "protocol_keywords.extension_names": "array of strings — e.g., ['key_share', 'supported_versions']",
  "protocol_keywords.alert_names": "array of strings — e.g., ['illegal_parameter', 'unexpected_message']",
  "protocol_keywords.modes_or_conditions": "array of strings — e.g., ['psk_ke', 'EC_DHE', 'compatibility_mode']",

  "checkability": "(required) string — One of: high, medium, low, not_checkable. How verifiable is this rule through static code analysis?",

  "checkability_rationale": "(required) string — Brief explanation. Example: 'Direct value assignment check' or 'Requires runtime ordering verification'.",

  "extraction_confidence": "(required) string — One of: high, medium, low. Your confidence in this extraction.",

  "extraction_confidence_rationale": "(required) string — Brief explanation of confidence level.",

  "cross_section_context_used": "(required) array of strings — Section IDs that were in your context during extraction. Record all sections you could see, not just ones you used.",

  "ambiguity_notes": "(optional, nullable) string — Any edge cases, unclear phrasing, or caveats. Null if the rule is unambiguous."
}
```

---

## Instructions for extraction

1. Read the entire RFC section provided.
2. Identify every sentence containing a normative keyword (MUST, SHOULD, SHALL, and their negatives, plus REQUIRED/RECOMMENDED).
3. For each normative statement, produce one NormalizedRule JSON object.
4. If a single sentence contains multiple independent normative constraints, split them into separate rules. Example: "Clients MUST NOT offer multiple KeyShareEntry values for the same group. Clients MUST NOT offer any KeyShareEntry values for groups not listed in the client's 'supported_groups' extension." → two rules.
5. If a single normative constraint spans multiple sentences (e.g., "the client MUST verify that (1)... and (2)..."), keep it as one rule — it's one compound check.
6. For violation_alert: check the provided context sections (priority sections like §6.2, §9.2) for alert definitions that apply to this rule, even if the rule's own section doesn't name an alert.
7. For protocol_keywords: be thorough. These keywords drive code search. Include all protocol terms mentioned in the rule, even if they seem obvious. Prefer RFC terminology (e.g., "ClientHello" not "client hello").
8. For checkability: be honest. If a rule requires runtime state or execution ordering to verify, say LOW or NOT_CHECKABLE. Do not overestimate what static analysis can do.
9. Output a JSON array of NormalizedRule objects, ordered by their appearance in the RFC text.

---

## Worked examples

### Example 1: Simple value constraint (§4.1.2)

```json
{
  "rule_id": "rfc8446-4.1.2-R01",
  "source_section": "4.1.2",
  "source_text": "the legacy_version field MUST be set to 0x0303, which is the version number for TLS 1.2.",
  "normative_keyword": "MUST",
  "rule_type": "value_constraint",
  "rule_statement": "In a TLS 1.3 ClientHello, the legacy_version field MUST be set to 0x0303.",
  "entity": "client",
  "applies_when": "Constructing a TLS 1.3 ClientHello",
  "target_message": "ClientHello",
  "target_field": "legacy_version",
  "expected_value": "0x0303",
  "related_fields": [],
  "violation_alert": null,
  "violation_alert_source": null,
  "protocol_keywords": {
    "message_types": ["ClientHello"],
    "field_names": ["legacy_version"],
    "extension_names": [],
    "alert_names": [],
    "modes_or_conditions": []
  },
  "checkability": "high",
  "checkability_rationale": "Direct value assignment — look for where legacy_version is set in ClientHello construction code.",
  "extraction_confidence": "high",
  "extraction_confidence_rationale": "Unambiguous value constraint with explicit field name and value.",
  "cross_section_context_used": ["4.1.2", "6.2", "9.2", "9.3"],
  "ambiguity_notes": "No alert stated for violation in this section. Server-side handling of wrong legacy_version is in §4.1.3."
}
```

### Example 2: Compound consistency check with alert (§4.2.8)

```json
{
  "rule_id": "rfc8446-4.2.8-R05",
  "source_section": "4.2.8",
  "source_text": "Upon receipt of this extension in a HelloRetryRequest, the client MUST verify that (1) the selected_group field corresponds to a group which was provided in the \"supported_groups\" extension in the original ClientHello and (2) the selected_group field does not correspond to a group which was provided in the \"key_share\" extension in the original ClientHello. If either of these checks fails, then the client MUST abort the handshake with an \"illegal_parameter\" alert.",
  "normative_keyword": "MUST",
  "rule_type": "consistency_check",
  "rule_statement": "When a client receives a HelloRetryRequest containing a key_share extension, it MUST verify that the selected_group is present in the original ClientHello's supported_groups AND not present in the original ClientHello's key_share. If either check fails, MUST abort with illegal_parameter.",
  "entity": "client",
  "applies_when": "Client receives a HelloRetryRequest containing a key_share extension",
  "target_message": "HelloRetryRequest",
  "target_field": "selected_group",
  "expected_value": null,
  "related_fields": ["supported_groups", "key_share"],
  "violation_alert": "illegal_parameter",
  "violation_alert_source": "inline",
  "protocol_keywords": {
    "message_types": ["HelloRetryRequest", "ClientHello"],
    "field_names": ["selected_group", "key_share", "supported_groups"],
    "extension_names": ["key_share", "supported_groups"],
    "alert_names": ["illegal_parameter"],
    "modes_or_conditions": []
  },
  "checkability": "medium",
  "checkability_rationale": "Requires tracing selected_group from HelloRetryRequest handler back to original ClientHello state. Both values are in code but may be in different functions.",
  "extraction_confidence": "high",
  "extraction_confidence_rationale": "Rule is clearly stated with explicit checks and explicit alert consequence.",
  "cross_section_context_used": ["4.2.8", "6.2", "9.2", "9.3"],
  "ambiguity_notes": null
}
```

### Example 3: Ordering constraint (§4.6.3)

```json
{
  "rule_id": "rfc8446-4.6.3-R04",
  "source_section": "4.6.3",
  "source_text": "If the request_update field is set to \"update_requested\", then the receiver MUST send a KeyUpdate of its own with request_update set to \"update_not_requested\" prior to sending its next Application Data record.",
  "normative_keyword": "MUST",
  "rule_type": "ordering_constraint",
  "rule_statement": "When a receiver gets a KeyUpdate with request_update = update_requested, it MUST send a responding KeyUpdate (with request_update = update_not_requested) before sending any further Application Data.",
  "entity": "receiver",
  "applies_when": "Receiver receives a KeyUpdate message with request_update set to update_requested",
  "target_message": "KeyUpdate",
  "target_field": "request_update",
  "expected_value": null,
  "related_fields": ["Application Data"],
  "violation_alert": null,
  "violation_alert_source": null,
  "protocol_keywords": {
    "message_types": ["KeyUpdate"],
    "field_names": ["request_update"],
    "extension_names": [],
    "alert_names": [],
    "modes_or_conditions": ["update_requested", "update_not_requested"]
  },
  "checkability": "low",
  "checkability_rationale": "Ordering constraint requires verifying that no Application Data is sent between receiving the KeyUpdate and sending the response. This is a runtime control flow property.",
  "extraction_confidence": "high",
  "extraction_confidence_rationale": "Clear ordering requirement with explicit trigger and action.",
  "cross_section_context_used": ["4.6.3", "6.2", "9.2", "9.3"],
  "ambiguity_notes": "The RFC notes that implementations receiving multiple KeyUpdates while silent should respond with a single update — this interacts with the ordering requirement but does not change it."
}
```

### Example 4: Conditional action with alert (§4.6.3)

```json
{
  "rule_id": "rfc8446-4.6.3-R01",
  "source_section": "4.6.3",
  "source_text": "Implementations that receive a KeyUpdate message prior to receiving a Finished message MUST terminate the connection with an \"unexpected_message\" alert.",
  "normative_keyword": "MUST",
  "rule_type": "conditional_action",
  "rule_statement": "If a KeyUpdate message is received before a Finished message has been received, the implementation MUST terminate the connection with an unexpected_message alert.",
  "entity": "both",
  "applies_when": "Implementation receives a KeyUpdate message before Finished has been received",
  "target_message": "KeyUpdate",
  "target_field": null,
  "expected_value": null,
  "related_fields": ["Finished"],
  "violation_alert": "unexpected_message",
  "violation_alert_source": "inline",
  "protocol_keywords": {
    "message_types": ["KeyUpdate", "Finished"],
    "field_names": [],
    "extension_names": [],
    "alert_names": ["unexpected_message"],
    "modes_or_conditions": []
  },
  "checkability": "medium",
  "checkability_rationale": "Need to verify that the KeyUpdate handler checks whether Finished has been received and sends the correct alert if not. Requires understanding handshake state tracking in the implementation.",
  "extraction_confidence": "high",
  "extraction_confidence_rationale": "Unambiguous conditional with explicit trigger, action, and alert.",
  "cross_section_context_used": ["4.6.3", "6.2", "9.2", "9.3"],
  "ambiguity_notes": null
}
```
