#!/usr/bin/env python3
"""Export EvalForge artifacts to beautiful Markdown files for judges."""
import os
import json
from datetime import datetime

os.environ['GOOGLE_CLOUD_PROJECT'] = 'konveyn2ai'

from google.cloud import firestore

db = firestore.Client(project='konveyn2ai', database='evalforge')

# Output directory
OUTPUT_DIR = "/tmp/evalforge_artifacts"
os.makedirs(OUTPUT_DIR, exist_ok=True)

print("Fetching artifacts from Firestore...")
suggestions = list(db.collection('evalforge_suggestions').stream())

# Collect artifacts
eval_tests = []
guardrails = []
runbooks = []

for s in suggestions:
    data = s.to_dict()
    content = data.get('suggestion_content', {})

    if content.get('eval_test'):
        et = content['eval_test']
        if et.get('title') and 'TODO' not in str(et.get('title', '')):
            eval_tests.append((s.id, et, data))

    if content.get('guardrail'):
        g = content['guardrail']
        if g.get('rule_name') and not g.get('rule_name', '').startswith('needs_human'):
            guardrails.append((s.id, g, data))

    if content.get('runbook_snippet'):
        r = content['runbook_snippet']
        if r.get('title') and not r.get('title', '').startswith('Needs human'):
            runbooks.append((s.id, r, data))

# ============================================================================
# Generate Eval Tests Markdown
# ============================================================================
eval_md = f"""# EvalForge - Generated Eval Tests

> **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> **Source**: Production LLM failure traces from Datadog LLM Observability
> **Total Tests**: {len(eval_tests)}

---

## Overview

These eval tests were automatically generated from real LLM failures detected in production. Each test captures a specific failure pattern and defines assertions to prevent regression.

---

"""

for i, (sid, et, data) in enumerate(eval_tests, 1):
    eval_md += f"""## {i}. {et.get('title', 'Untitled Test')}

| Property | Value |
|----------|-------|
| **Suggestion ID** | `{sid}` |
| **Status** | {et.get('status', 'pending')} |
| **Severity** | {data.get('severity', 'N/A')} |

### Rationale

{et.get('rationale', '_No rationale provided_')}

### Test Input

```
{et.get('test_input', '_No test input specified_')}
```

### Assertions

#### Required (Must Pass)
"""
    assertions = et.get('assertions', {})
    required = assertions.get('required', [])
    if required:
        for req in required:
            eval_md += f"- {req}\n"
    else:
        eval_md += "_No required assertions specified_\n"

    eval_md += "\n#### Forbidden (Must Not Occur)\n"
    forbidden = assertions.get('forbidden', [])
    if forbidden:
        for forb in forbidden:
            eval_md += f"- {forb}\n"
    else:
        eval_md += "_No forbidden patterns specified_\n"

    eval_md += "\n---\n\n"

with open(f"{OUTPUT_DIR}/eval_tests.md", "w") as f:
    f.write(eval_md)
print(f"  Wrote {OUTPUT_DIR}/eval_tests.md ({len(eval_tests)} tests)")

# ============================================================================
# Generate Guardrails Markdown
# ============================================================================
guardrail_md = f"""# EvalForge - Generated Guardrails

> **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> **Source**: Production LLM failure traces from Datadog LLM Observability
> **Total Guardrails**: {len(guardrails)}

---

## Overview

These guardrails were automatically generated from failure patterns detected in production. They can be exported as YAML for use with Datadog AI Guard or similar systems.

---

"""

for i, (sid, g, data) in enumerate(guardrails, 1):
    guardrail_md += f"""## {i}. {g.get('rule_name', 'Untitled Rule')}

| Property | Value |
|----------|-------|
| **Suggestion ID** | `{sid}` |
| **Guardrail Type** | `{g.get('guardrail_type', 'N/A')}` |
| **Severity** | {data.get('severity', 'N/A')} |

### Description

{g.get('description', '_No description provided_')}

### Configuration

```json
{json.dumps(g.get('config', {}), indent=2)}
```

### YAML Export (Datadog AI Guard Format)

```yaml
rules:
  - name: {g.get('rule_name', 'unnamed_rule')}
    type: {g.get('guardrail_type', 'custom')}
    config:
{chr(10).join('      ' + line for line in json.dumps(g.get('config', {}), indent=2).split(chr(10)))}
```

### API Export Endpoint

```bash
curl "https://evalforge-api-72021522495.us-central1.run.app/guardrails/{sid}?format=yaml" \\
  -H "X-API-Key: YOUR_API_KEY"
```

---

"""

with open(f"{OUTPUT_DIR}/guardrails.md", "w") as f:
    f.write(guardrail_md)
print(f"  Wrote {OUTPUT_DIR}/guardrails.md ({len(guardrails)} guardrails)")

# ============================================================================
# Generate Runbooks Markdown
# ============================================================================
runbook_md = f"""# EvalForge - Generated Runbooks

> **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> **Source**: Production LLM failure traces from Datadog LLM Observability
> **Total Runbooks**: {len(runbooks)}

---

## Overview

These SRE runbooks were automatically generated from failure patterns detected in production. Each runbook provides symptoms to watch for, diagnosis steps, and mitigation procedures.

---

"""

for i, (sid, r, data) in enumerate(runbooks, 1):
    runbook_md += f"""## {i}. {r.get('title', 'Untitled Runbook')}

| Property | Value |
|----------|-------|
| **Suggestion ID** | `{sid}` |
| **Severity** | {r.get('severity', data.get('severity', 'N/A'))} |

### Summary

{r.get('summary', '_No summary provided_')}

### Symptoms

"""
    symptoms = r.get('symptoms', [])
    if symptoms:
        for sym in symptoms:
            runbook_md += f"- {sym}\n"
    else:
        runbook_md += "_No symptoms specified_\n"

    runbook_md += "\n### Mitigation Steps\n\n"
    mitigation = r.get('mitigation_steps', [])
    if mitigation:
        for j, step in enumerate(mitigation, 1):
            if isinstance(step, dict):
                runbook_md += f"{j}. **{step.get('action', 'Step')}**: {step.get('description', str(step))}\n"
            else:
                runbook_md += f"{j}. {step}\n"
    else:
        runbook_md += "_No mitigation steps specified_\n"

    # If there's full markdown content, include it
    md_content = r.get('markdown_content', '')
    if md_content and len(md_content) > 100:
        runbook_md += f"""
### Full Runbook Content

<details>
<summary>Click to expand full runbook ({len(md_content)} characters)</summary>

{md_content}

</details>
"""

    runbook_md += "\n---\n\n"

with open(f"{OUTPUT_DIR}/runbooks.md", "w") as f:
    f.write(runbook_md)
print(f"  Wrote {OUTPUT_DIR}/runbooks.md ({len(runbooks)} runbooks)")

# ============================================================================
# Generate Combined Summary
# ============================================================================
summary_md = f"""# EvalForge - Artifact Summary

> **Project**: Incident-to-Insight Loop for LLM Production Failures
> **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## What is EvalForge?

EvalForge automatically transforms LLM production failures into actionable artifacts:

1. **Eval Tests** - Regression tests to catch similar failures
2. **Guardrails** - Runtime protection rules (exportable to Datadog AI Guard)
3. **Runbooks** - SRE playbooks for incident response

## Pipeline Overview

```
Datadog LLM Observability
        │
        ▼
   ┌─────────┐
   │Ingestion│ ──► Fetches error traces
   └────┬────┘
        │
        ▼
  ┌───────────┐
  │Extraction │ ──► Extracts failure patterns (Gemini 2.5 Flash)
  └─────┬─────┘
        │
        ▼
┌──────────────┐
│Deduplication │ ──► Merges similar patterns (86.6% threshold)
└──────┬───────┘
        │
        ▼
┌───────────────────────────────────────┐
│           Generator Services           │
├─────────────┬───────────┬─────────────┤
│ Eval Tests  │ Guardrails│  Runbooks   │
│   ({len(eval_tests)})      │    ({len(guardrails)})    │    ({len(runbooks)})      │
└─────────────┴───────────┴─────────────┘
        │
        ▼
   ┌─────────┐
   │   API   │ ──► Approval workflow & exports
   └─────────┘
```

## Generated Artifacts

| Type | Count | File |
|------|-------|------|
| Eval Tests | {len(eval_tests)} | [eval_tests.md](./eval_tests.md) |
| Guardrails | {len(guardrails)} | [guardrails.md](./guardrails.md) |
| Runbooks | {len(runbooks)} | [runbooks.md](./runbooks.md) |
| **Total** | **{len(eval_tests) + len(guardrails) + len(runbooks)}** | |

## API Access

**Base URL**: `https://evalforge-api-72021522495.us-central1.run.app`

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /approval/suggestions` | List all suggestions |
| `GET /approval/suggestions/{{id}}` | Get suggestion details |
| `GET /guardrails/{{id}}?format=yaml` | Export guardrail as YAML |
| `POST /approval/suggestions/{{id}}/approve` | Approve suggestion |
| `POST /approval/suggestions/{{id}}/reject` | Reject suggestion |

## Google Cloud Products Used

- **Cloud Run** - 7 containerized microservices
- **Firestore** - Document database (named: `evalforge`)
- **Vertex AI** - Gemini 2.5 Flash for extraction & generation
- **Secret Manager** - Secure credential storage
- **Cloud Build** - CI/CD pipeline
- **Artifact Registry** - Container image storage

## Other Technologies

- **Datadog LLM Observability** - Source of LLM traces
- **FastAPI** - Python web framework
- **HuggingFace Datasets** - AgentErrorBench test data
- **ddtrace** - Datadog SDK

---

*Generated by EvalForge - Transforming LLM failures into actionable insights*
"""

with open(f"{OUTPUT_DIR}/README.md", "w") as f:
    f.write(summary_md)
print(f"  Wrote {OUTPUT_DIR}/README.md (summary)")

print(f"\n{'='*60}")
print(f"Markdown files exported to: {OUTPUT_DIR}/")
print(f"{'='*60}")
print(f"""
Files created:
  - README.md      (Summary & overview)
  - eval_tests.md  ({len(eval_tests)} eval tests)
  - guardrails.md  ({len(guardrails)} guardrails)
  - runbooks.md    ({len(runbooks)} runbooks)

View with:
  cat {OUTPUT_DIR}/README.md

Or copy to project:
  cp -r {OUTPUT_DIR}/* docs/artifacts/
""")
