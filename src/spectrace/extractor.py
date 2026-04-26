"""Calls Anthropic API with the extraction system prompt and RFC context."""

import json

import anthropic

from spectrace.models import NormalizedRule
from spectrace.prompts.extraction import EXTRACTION_SYSTEM_PROMPT


class ExtractionResult:
    """Result of an extraction, including rules and token usage."""

    def __init__(self, rules: list[dict], usage: dict):
        self.rules = rules
        self.usage = usage

    @property
    def input_tokens(self) -> int:
        return self.usage.get("input_tokens", 0)

    @property
    def output_tokens(self) -> int:
        return self.usage.get("output_tokens", 0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def extract_rules(context_markdown: str, model: str = "claude-sonnet-4-6") -> ExtractionResult:
    """
    Send RFC context to Claude and get back extracted NormalizedRule objects.

    Args:
        context_markdown: the full markdown blob from rfckb context
        model: Anthropic model to use

    Returns:
        ExtractionResult with validated rules and token usage
    """
    client = anthropic.Anthropic()

    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Extract all normative rules from the following RFC context. "
                    "Output ONLY a JSON array of NormalizedRule objects.\n\n"
                    f"{context_markdown}"
                ),
            }
        ],
    )

    response_text = response.content[0].text

    # Strip markdown code fences if present
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]
        response_text = response_text.rsplit("```", 1)[0]

    rules = json.loads(response_text)

    # Validate each rule against the pydantic model
    validated = [NormalizedRule(**rule) for rule in rules]

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    if hasattr(response.usage, "cache_creation_input_tokens"):
        usage["cache_creation_input_tokens"] = response.usage.cache_creation_input_tokens
    if hasattr(response.usage, "cache_read_input_tokens"):
        usage["cache_read_input_tokens"] = response.usage.cache_read_input_tokens

    return ExtractionResult([r.model_dump() for r in validated], usage)
