# Research: Guardrail Suggestion Engine

**Feature**: 005-guardrail-generation
**Date**: 2025-12-30

## Research Summary

This feature follows the proven architecture of 004-eval-test-case-generator. Research focuses on guardrail-specific adaptations rather than foundational decisions (already validated in 004).

---

## 1. Guardrail Output Schema

### Decision
Use a structured JSON schema for GuardrailDraft that parallels EvalTestDraft but includes guardrail-specific fields: `guardrail_type`, `rule_name`, `configuration`, `justification`, `estimated_prevention_rate`.

### Rationale
- Mirrors the eval test draft pattern for consistency
- Includes actionable configuration values (not placeholders)
- Supports YAML export for Datadog AI Guard compatibility
- Embeds on `suggestion_content.guardrail` (parallel to `suggestion_content.eval_test`)

### Alternatives Considered
1. **Store as separate collection**: Rejected - adds query complexity, breaks suggestion-centric model
2. **Generic rule format**: Rejected - loses guardrail-type-specific configuration structure
3. **Datadog YAML only**: Rejected - JSON primary enables validation; YAML export is secondary

---

## 2. Failure Type to Guardrail Type Mapping

### Decision
Use deterministic mapping from failure_type → guardrail_type with sensible defaults.

| Failure Type | Guardrail Type | Rationale |
|--------------|----------------|-----------|
| hallucination | validation_rule | Requires fact-checking against knowledge base |
| toxicity | content_filter | Output filtering with threshold-based blocking |
| runaway_loop | rate_limit | Prevents cost blowouts with call limits |
| pii_leak | redaction_rule | Pattern-based sensitive data stripping |
| wrong_tool | scope_limit | Restricts tool availability |
| stale_data | freshness_check | Data recency validation |
| prompt_injection | input_sanitization | Input pattern blocking |
| *default* | validation_rule | Fallback for unmapped types |

### Rationale
- Deterministic mapping enables consistent behavior
- Each guardrail type has a clear prevention mechanism
- Default fallback ensures all failure types get a guardrail

### Alternatives Considered
1. **LLM-determined type**: Rejected - non-deterministic, harder to test
2. **No default fallback**: Rejected - leaves edge cases unhandled

---

## 3. Gemini Prompt Strategy

### Decision
Use structured prompt with:
1. Failure context (type, trigger, severity, reproduction)
2. Guardrail type hint (from deterministic mapping)
3. Example configurations for each guardrail type
4. Response schema enforcement via `response_mime_type="application/json"`

### Rationale
- Follows 004 proven pattern with `response_schema` for structured output
- Guardrail type hint reduces hallucination risk
- Examples guide concrete configuration values

### Prompt Template Structure
```
You are generating a guardrail rule to prevent this failure type.

Failure Pattern:
- Type: {failure_type}
- Trigger: {trigger_condition}
- Severity: {severity}
- Context: {reproduction_context}

Guardrail Type: {guardrail_type} (pre-determined)

Generate a guardrail configuration with:
- rule_name: Descriptive snake_case name
- description: What this rule prevents
- configuration: Specific values (thresholds, limits, patterns)
- justification: Why this prevents recurrence
- estimated_prevention_rate: 0.0-1.0

Output JSON only:
```

---

## 4. Configuration Value Generation

### Decision
Gemini generates concrete configuration values based on failure context. Validation ensures values are within reasonable ranges.

### Configuration Schemas by Type

**rate_limit**:
```json
{
  "max_calls": 10,       // 1-100
  "window_seconds": 60,  // 1-3600
  "action": "block_and_alert"  // block|warn|block_and_alert
}
```

**content_filter**:
```json
{
  "filter_type": "output",  // input|output|both
  "threshold": 0.7,         // 0.0-1.0
  "action": "block"
}
```

**redaction_rule**:
```json
{
  "patterns": ["email", "phone", "ssn"],  // known patterns
  "action": "redact"  // redact|block|warn
}
```

**validation_rule**:
```json
{
  "check_type": "pre_response",  // pre_response|post_response
  "condition": "description of check"
}
```

### Rationale
- Concrete values enable one-click deployment
- Validation prevents unreasonable configurations
- Sensible defaults when Gemini produces edge values

---

## 5. Code Reuse from 004

### Decision
Copy and adapt 5 modules from `src/generators/eval_tests/` to `src/generators/guardrails/`:

| Module | Reuse Type | Adaptation Required |
|--------|------------|---------------------|
| models.py | Copy & modify | Replace EvalTestDraft with GuardrailDraft |
| gemini_client.py | Copy & modify | Change response_schema |
| firestore_repository.py | Copy & modify | Query `type="guardrail"`, write to `suggestion_content.guardrail` |
| service.py | Copy & modify | Add failure-type mapping, use guardrail prompt |
| main.py | Copy & modify | Change endpoint prefix to `/guardrails` |

### Rationale
- Proven patterns reduce risk
- Consistent architecture across generators
- Shared patterns (overwrite protection, cost budget, canonical selection) work identically

---

## 6. Testing Strategy (Minimal Mode)

### Decision
One live integration test per user story:
1. **Batch generation**: Create guardrail suggestions, run batch, verify drafts
2. **Single generation**: Generate for specific suggestion, verify overwrite protection
3. **Retrieval**: GET endpoint returns draft with approval metadata

### Rationale
- Live tests catch real API integration issues
- No mocks means no mock drift
- Follows 004 test pattern for consistency

### Test File
`tests/integration/test_guardrail_generator_live.py`
- Guarded by `RUN_LIVE_TESTS=1`
- Uses unique collection prefix for isolation
- Cleanup after each test

---

## 7. YAML Export Capability

### Decision
Export guardrail drafts to YAML format on-demand via GET endpoint query parameter.

### Implementation
- Store primary format as JSON in Firestore
- Export endpoint: `GET /guardrails/{id}?format=yaml`
- Use PyYAML for conversion
- Validate YAML structure matches Datadog AI Guard expectations

### Rationale
- JSON primary enables schema validation
- YAML export supports deployment tooling
- On-demand conversion avoids storage duplication

---

## Open Questions (Resolved)

| Question | Resolution |
|----------|------------|
| Where to store guardrail drafts? | `suggestion_content.guardrail` (parallel to eval_test) |
| How to determine guardrail type? | Deterministic mapping from failure_type |
| What configuration format? | JSON with guardrail-type-specific schemas |
| How to handle unmapped failure types? | Default to `validation_rule` |
| Testing approach? | Live integration tests only (minimal mode) |
