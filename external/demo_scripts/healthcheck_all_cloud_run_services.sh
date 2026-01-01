#!/bin/bash
TOKEN=$(gcloud auth print-identity-token)

echo "=== INGESTION ==="
curl -s -H "Authorization: Bearer $TOKEN" https://evalforge-ingestion-72021522495.us-central1.run.app/health

echo ""
echo "=== EXTRACTION ==="
curl -s -H "Authorization: Bearer $TOKEN" https://evalforge-extraction-72021522495.us-central1.run.app/health

echo ""
echo "=== DEDUPLICATION ==="
curl -s -H "Authorization: Bearer $TOKEN" https://evalforge-deduplication-72021522495.us-central1.run.app/health

echo ""
echo "=== EVAL-TESTS ==="
curl -s -H "Authorization: Bearer $TOKEN" https://evalforge-eval-tests-72021522495.us-central1.run.app/health

echo ""
echo "=== GUARDRAILS ==="
curl -s -H "Authorization: Bearer $TOKEN" https://evalforge-guardrails-72021522495.us-central1.run.app/health

echo ""
echo "=== RUNBOOKS ==="
curl -s -H "Authorization: Bearer $TOKEN" https://evalforge-runbooks-72021522495.us-central1.run.app/health
