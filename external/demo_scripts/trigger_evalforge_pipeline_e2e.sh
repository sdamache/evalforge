#!/bin/bash
TOKEN=$(gcloud auth print-identity-token)

echo "=== STEP 1: EXTRACTION ==="
echo "Processing raw traces → failure patterns..."
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  https://evalforge-extraction-72021522495.us-central1.run.app/extraction/run-once \
  -d '{"batchSize": 10}'

echo ""
echo ""
echo "=== STEP 2: DEDUPLICATION ==="
echo "Processing failure patterns → suggestions..."
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  https://evalforge-deduplication-72021522495.us-central1.run.app/dedup/run-once \
  -d '{"batchSize": 10}'

echo ""
echo ""
echo "=== STEP 3: GENERATORS ==="
echo "Generating eval tests..."
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  https://evalforge-eval-tests-72021522495.us-central1.run.app/eval-tests/run-once \
  -d '{"batchSize": 10}'

echo ""
echo ""
echo "Generating guardrails..."
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  https://evalforge-guardrails-72021522495.us-central1.run.app/guardrails/run-once \
  -d '{"batchSize": 10}'

echo ""
echo ""
echo "Generating runbooks..."
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  https://evalforge-runbooks-72021522495.us-central1.run.app/runbooks/run-once \
  -d '{"batchSize": 10}'

echo ""
echo ""
echo "=== PIPELINE COMPLETE ==="
