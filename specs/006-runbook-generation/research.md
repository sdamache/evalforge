# Research: Runbook Draft Generator

**Feature**: 006-runbook-generation
**Date**: 2025-12-30

## Research Questions

### RQ-1: Can we reuse the eval_tests GeminiClient for Markdown generation?

**Decision**: Yes, with minimal adaptation

**Rationale**:
- The existing `GeminiClient` in `eval_tests/gemini_client.py` uses `response_mime_type="application/json"` with `response_schema` for structured output
- For runbooks, we need structured JSON containing Markdown content (not raw Markdown output)
- The same pattern works: define a `get_runbook_draft_response_schema()` that returns JSON schema with `markdown_content` as a string field
- Gemini will return valid JSON with Markdown embedded in the string fields

**Alternatives Considered**:
| Alternative | Rejected Because |
|-------------|------------------|
| Raw Markdown output (no JSON wrapper) | Harder to parse, no structured fields for symptoms/commands |
| New client from scratch | Unnecessary duplication; same retry logic, hashing, error handling |

### RQ-2: What Gemini temperature is optimal for runbook generation?

**Decision**: Use 0.3 (slightly higher than eval's 0.2)

**Rationale**:
- Eval tests need high determinism for assertions (0.2)
- Runbooks benefit from slightly more creative language for natural documentation (0.3)
- Still low enough to maintain consistent structure
- Can be tuned after SRE review of sample outputs

**Alternatives Considered**:
| Alternative | Rejected Because |
|-------------|------------------|
| 0.2 (same as eval) | May produce overly rigid, template-like text |
| 0.5+ (higher creativity) | Risk of inconsistent structure, hallucinated commands |

### RQ-3: How should RunbookDraft store both structured and Markdown content?

**Decision**: Hybrid model with both structured fields AND full Markdown

**Rationale**:
- Structured fields (`symptoms[]`, `diagnosis_commands[]`, `mitigation_steps[]`) enable programmatic access
- Full `markdown_content` field provides ready-to-render output for Confluence/GitHub
- Matches the pattern used in eval_tests where `input` and `assertions` are structured but renderable

**Schema Design**:
```python
class RunbookDraft:
    runbook_id: str
    title: str
    markdown_content: str  # Full rendered Markdown

    # Structured extraction for programmatic access
    symptoms: List[str]
    diagnosis_commands: List[str]
    mitigation_steps: List[str]
    escalation_criteria: str

    # Metadata
    source: RunbookDraftSource
    status: RunbookDraftStatus
    edit_source: EditSource
    generated_at: datetime
    updated_at: datetime
    generator_meta: RunbookDraftGeneratorMeta
```

### RQ-4: What failure types map to specific runbook patterns?

**Decision**: Map failure types to diagnosis command templates

**Rationale**:
- Different failure types require different diagnostic approaches
- Prompts should include type-specific command suggestions

**Mapping**:
| Failure Type | Primary Diagnosis Commands |
|--------------|---------------------------|
| hallucination | `datadog trace search "service:X @llm.quality_score:<0.5"`, check knowledge base freshness |
| toxicity | `datadog trace search "service:X @llm.toxicity:>0.7"`, review content filter logs |
| runaway_loop | Check API call counts, review retry logic, check circuit breaker state |
| pii_leak | Audit redaction patterns, check PII detection rules, review output logs |
| stale_data | Verify cache TTL, check data source sync timestamps, validate freshness |
| prompt_injection | Review input sanitization logs, check guardrail trigger events |

### RQ-5: What's the optimal prompt structure for SRE runbooks?

**Decision**: Use explicit section markers with examples

**Rationale**:
- SRE runbooks have a well-defined structure (Google SRE book)
- Explicit section markers in prompt ensure consistent output
- Including one example per section guides Gemini on expected detail level

**Prompt Structure**:
```
You are an SRE creating operational runbooks for LLM agent failures.

Generate a runbook with these exact sections:
1. Summary: 1-2 sentence description of the failure mode
2. Symptoms: Observable indicators (metrics, logs, errors)
3. Diagnosis Steps: Specific commands and queries (Datadog, logs, dashboards)
4. Immediate Mitigation: Actions to reduce customer impact NOW
5. Root Cause Fix: Long-term prevention steps
6. Escalation: When/who/threshold

REQUIREMENTS:
- Include at least 2 specific commands in Diagnosis Steps
- Commands must be runnable (real Datadog queries, actual log paths)
- No vague instructions like "check logs" - be specific
- Use Markdown formatting with headers and bullet points
```

## Validation Results

### Test: Gemini Markdown Generation Quality
- **Method**: Manual testing with sample failure patterns from Issue #2
- **Result**: Gemini 2.5 Flash produces coherent Markdown with proper headers
- **Finding**: Explicit section markers in prompt produce more consistent structure

### Test: Reuse Viability
- **Method**: Code review of `eval_tests/` modules
- **Result**: All modules can be adapted with search-and-replace level changes
- **Finding**: Only `prompt_templates.py` requires substantial new content

## Recommendations

1. **Proceed with reuse strategy** - Copy all eval_tests modules with targeted modifications
2. **Use temperature 0.3** - Balance between consistency and natural language
3. **Implement hybrid schema** - Both structured fields and full Markdown
4. **Include failure-type-specific prompts** - Map failure types to diagnostic approaches
5. **Require minimum 2 commands** - Enforce actionability in prompt instructions
