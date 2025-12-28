#!/usr/bin/env bash
#
# Helper script to trigger a one-time extraction run against the local or deployed extraction service.
#
# Usage:
#   ./scripts/run_extraction_once.sh                    # local (http://localhost:8002)
#   ./scripts/run_extraction_once.sh <SERVICE_URL>      # custom URL
#

set -euo pipefail

# Configuration
SERVICE_URL="${1:-http://localhost:8002}"
ENDPOINT="${SERVICE_URL}/extraction/run-once"
BATCH_SIZE="${BATCH_SIZE:-50}"
TRIGGERED_BY="${TRIGGERED_BY:-manual}"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Triggering extraction run...${NC}"
echo "  Service: ${SERVICE_URL}"
echo "  Batch size: ${BATCH_SIZE}"
echo "  Triggered by: ${TRIGGERED_BY}"
echo ""

# Make request
RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
  -X POST "${ENDPOINT}" \
  -H "Content-Type: application/json" \
  -d "{\"batchSize\":${BATCH_SIZE},\"triggeredBy\":\"${TRIGGERED_BY}\"}")

# Extract HTTP status
HTTP_STATUS=$(echo "$RESPONSE" | grep HTTP_STATUS | cut -d':' -f2)
BODY=$(echo "$RESPONSE" | sed '$d')

# Check status
if [ "$HTTP_STATUS" -eq 200 ]; then
  echo -e "${GREEN}✓ Extraction run triggered successfully${NC}"
  echo ""
  echo "Response:"
  echo "$BODY" | jq '.' 2>/dev/null || echo "$BODY"
  echo ""
  echo -e "${YELLOW}Next steps:${NC}"
  echo "  1. Check service logs for progress"
  echo "  2. Query Firestore collection 'evalforge_failure_patterns' for results"
  echo "  3. Verify source traces in 'evalforge_raw_traces' marked processed=true"
else
  echo -e "${RED}✗ Failed to trigger extraction run (HTTP ${HTTP_STATUS})${NC}"
  echo ""
  echo "Response:"
  echo "$BODY"
  exit 1
fi
