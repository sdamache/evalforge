#!/usr/bin/env python3
"""Display generated artifacts beautifully for judges."""
import os
import json
os.environ['GOOGLE_CLOUD_PROJECT'] = 'konveyn2ai'

from google.cloud import firestore

db = firestore.Client(project='konveyn2ai', database='evalforge')

print("=" * 80)
print("🚀 EVALFORGE - AI-Generated Artifacts from Production LLM Failures")
print("   Incident-to-Insight: Automatically transform LLM failures into")
print("   eval tests, guardrails, and runbooks")
print("=" * 80)

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

# Display Eval Tests
print(f"\n{'='*80}")
print(f"📋 EVAL TESTS ({len(eval_tests)} generated from real failures)")
print(f"{'='*80}")

for i, (sid, et, data) in enumerate(eval_tests, 1):
    print(f"\n┌{'─'*78}┐")
    print(f"│ [{i}] {et.get('title', 'N/A')[:70]:<70} │")
    print(f"├{'─'*78}┤")
    print(f"│ ID: {sid:<72} │")
    print(f"│ Status: {et.get('status', 'N/A'):<68} │")
    print(f"└{'─'*78}┘")

    rationale = et.get('rationale', '')
    if rationale:
        print(f"\n  📝 Rationale:")
        for line in [rationale[i:i+70] for i in range(0, min(len(rationale), 280), 70)]:
            print(f"     {line}")

    assertions = et.get('assertions', {})
    if assertions.get('required'):
        print(f"\n  ✅ Required assertions:")
        for req in assertions['required'][:4]:
            print(f"     • {req[:70]}")

    if assertions.get('forbidden'):
        print(f"\n  ❌ Forbidden patterns:")
        for forb in assertions['forbidden'][:3]:
            print(f"     • {forb[:70]}")

# Display Guardrails
print(f"\n\n{'='*80}")
print(f"🛡️  GUARDRAILS ({len(guardrails)} generated)")
print(f"{'='*80}")

for i, (sid, g, data) in enumerate(guardrails, 1):
    print(f"\n┌{'─'*78}┐")
    print(f"│ [{i}] {g.get('rule_name', 'N/A'):<70} │")
    print(f"├{'─'*78}┤")
    print(f"│ Type: {g.get('guardrail_type', 'N/A'):<70} │")
    print(f"│ ID: {sid:<72} │")
    print(f"└{'─'*78}┘")

    desc = g.get('description', '')
    if desc:
        print(f"\n  📝 Description:")
        for line in [desc[i:i+70] for i in range(0, min(len(desc), 280), 70)]:
            print(f"     {line}")

    config = g.get('config', {})
    if config:
        print(f"\n  ⚙️  Configuration:")
        print(f"     {json.dumps(config, indent=2)[:300]}")

# Display Runbooks
print(f"\n\n{'='*80}")
print(f"📖 RUNBOOKS ({len(runbooks)} generated)")
print(f"{'='*80}")

for i, (sid, r, data) in enumerate(runbooks, 1):
    print(f"\n┌{'─'*78}┐")
    print(f"│ [{i}] {r.get('title', 'N/A')[:70]:<70} │")
    print(f"├{'─'*78}┤")
    print(f"│ ID: {sid:<72} │")
    print(f"└{'─'*78}┘")

    summary = r.get('summary', '')
    if summary:
        print(f"\n  📝 Summary:")
        for line in [summary[i:i+70] for i in range(0, min(len(summary), 350), 70)]:
            print(f"     {line}")

    symptoms = r.get('symptoms', [])
    if symptoms:
        print(f"\n  🔍 Symptoms to watch for:")
        for sym in symptoms[:3]:
            print(f"     • {sym[:70]}...")

    mitigation = r.get('mitigation_steps', [])
    if mitigation:
        print(f"\n  🔧 Mitigation Steps: ({len(mitigation)} steps)")
        for j, step in enumerate(mitigation[:3], 1):
            if isinstance(step, dict):
                print(f"     {j}. {step.get('description', str(step))[:65]}...")
            else:
                print(f"     {j}. {str(step)[:65]}...")

    md = r.get('markdown_content', '')
    if md:
        print(f"\n  📄 Full Runbook: {len(md)} characters (exportable as Markdown)")

# Summary
print(f"\n\n{'='*80}")
print(f"📊 ARTIFACT SUMMARY")
print(f"{'='*80}")
print(f"""
  📋 Eval Tests Generated:  {len(eval_tests)}
  🛡️  Guardrails Generated:  {len(guardrails)}
  📖 Runbooks Generated:    {len(runbooks)}

  Total Suggestions:        {len(suggestions)}
  Total Failure Patterns:   {db.collection('evalforge_failure_patterns').count().get()[0][0].value}
  Total Raw Traces:         {db.collection('evalforge_raw_traces').count().get()[0][0].value}
""")

print(f"{'='*80}")
print("🌐 API ENDPOINTS")
print(f"{'='*80}")
print("""
┌─────────────────────────────────────────────────────────────────────────────┐
│ MAIN API (Approval Workflow)                                                │
│ https://evalforge-api-72021522495.us-central1.run.app                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ GET  /approval/suggestions           - List suggestions with artifacts     │
│ GET  /approval/suggestions/{id}      - Get suggestion details              │
│ POST /approval/suggestions/{id}/approve - Approve a suggestion             │
│ POST /approval/suggestions/{id}/reject  - Reject a suggestion              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ GENERATOR SERVICES                                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ Eval Tests:  POST https://evalforge-eval-tests-*.run.app/eval-tests/run-once│
│ Guardrails:  POST https://evalforge-guardrails-*.run.app/guardrails/run-once│
│ Runbooks:    POST https://evalforge-runbooks-*.run.app/runbooks/run-once   │
│                                                                             │
│ YAML Export: GET /guardrails/{id}?format=yaml (Datadog AI Guard format)    │
└─────────────────────────────────────────────────────────────────────────────┘
""")
