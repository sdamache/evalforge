<!--
Sync Impact Report:
- Version change: 0.0.0 → 1.0.0
- Modified principles: (new) Observability-First Insight Trail, Human-Governed Fail-Safe Loops, Cost-Conscious Experimentation, Reliability & Cognitive Ease, Demo-Ready Transparency & UX
- Added sections: Platform & Compliance Constraints; Workflow & Quality Gates
- Removed sections: None
- Templates requiring updates:
  - ✅ .specify/templates/spec-template.md (already enforces user-value focus, no change needed)
  - ✅ .specify/templates/plan-template.md (Constitution Check will reference this version)
  - ✅ .specify/templates/tasks-template.md (task grouping rules already align)
- Follow-up TODOs: None
-->
# Evalforge Constitution

## Core Principles

### Observability-First Insight Trail
Every component must emit trace IDs, structured logs, and metrics that link decisions, API calls, and state transitions end-to-end. Prompts, intermediate responses, and generated artifacts are persisted with hashed identifiers so investigators can reproduce any improvement path without exposing raw PII. Instrumentation is non-negotiable and reviewed before merge.

### Human-Governed Fail-Safe Loops
The platform degrades gracefully whenever Datadog, Vertex AI/Gemini, or other dependencies fail—never blocking user workflows. All generated evals, guardrails, or runbooks remain in a pending state until a human explicitly approves them. Every suggestion must include plain-language reasoning and cite its source trace.

### Cost-Conscious Experimentation
LLM usage is minimized through caching, batching, and prompt discipline. Each feature tracks end-to-end compute and API spend; any workflow forecasted to exceed $0.10 per execution must provide a lower-cost fallback (smaller model, cached response, or unit test). Decisions that impact spend are logged alongside their expected impact.

### Reliability & Cognitive Ease
Services handle upstream errors with at least three exponential-backoff retries and emit clear health signals. Runbooks must be executable in under five minutes, avoid jargon, and highlight only the data needed for action. High-severity workflows prioritize fail-stop behavior with safe defaults over partial, confusing outputs.

### Demo-Ready Transparency & UX
Hackathon-ready impact beats polish: deliver working prototypes that showcase the Incident-to-Insight loop end-to-end. Every interaction favors one-click actions, progressive disclosure of detail, and visible reasoning so stakeholders understand “what happened” immediately.

## Platform & Compliance Constraints

- All workloads run on Google Cloud Run using stateless services; VM-based deployments are prohibited.
- Datadog must be accessed via the live API with authenticated requests—no mock data outside sanctioned test fixtures.
- Vertex AI/Gemini is the only LLM provider; OpenAI or other vendors are not permitted.
- Prompts, responses, and intermediate steps are stored for diagnostics, but raw user PII is stripped or hashed before persistence.
- API keys and secrets are retrieved exclusively from Secret Manager, never committed to source or logs, and all network traffic uses HTTPS.
- Pattern extraction must complete in under 10 seconds per trace, suggestion generation under 30 seconds, and dashboard queries under 2 seconds.

## Workflow & Quality Gates

- Integration tests must hit real Datadog and Gemini endpoints; cached golden responses are allowed solely to keep CI costs predictable.
- Avoid mock tests by default; only simulate services when a real call would exceed the $0.10/test budget and no cache exists.
- Cost, latency, observability, and approval status are reviewed in every `/speckit.plan` Constitution Check before work begins.
- Failover playbooks must document step-by-step actions and link to captured logs so on-call engineers can resolve incidents quickly.
- UX reviews confirm that each surfaced recommendation includes reasoning, impact, and a single-click follow-up action.

## Governance

This constitution supersedes ad-hoc preferences. Amendments require a PR referencing the change rationale, updated version, and confirmation that templates still align. Semantic versioning applies: MAJOR for principle reversals or removals, MINOR for new principles/sections, PATCH for clarifications. Constitution compliance is checked at planning time and during PR review; any violations must document compensating controls before merge.

**Version**: 1.0.0 | **Ratified**: 2025-12-04 | **Last Amended**: 2025-12-04
