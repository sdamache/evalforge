"""Guardrail rule draft generator service.

This package turns guardrail-type suggestions into structured JSON guardrail
rule drafts and stores them on `suggestion_content.guardrail`. The service
maps failure types to guardrail types using a deterministic mapping
(hallucination→validation_rule, runaway_loop→rate_limit, etc.) and generates
actionable configurations with concrete thresholds and justifications.
"""
