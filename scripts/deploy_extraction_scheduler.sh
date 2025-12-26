#!/usr/bin/env bash
#
# Deploy Cloud Scheduler job to trigger extraction service on Cloud Run.
#
# This script creates or updates a Cloud Scheduler job that invokes the extraction
# service's /extraction/run-once endpoint every 30 minutes.
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - GCP_PROJECT_ID environment variable set
#   - Extraction service deployed to Cloud Run
#   - Cloud Scheduler API enabled
#
# Usage:
#   export GCP_PROJECT_ID="your-project-id"
#   ./scripts/deploy_extraction_scheduler.sh
#

set -euo pipefail

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:?GCP_PROJECT_ID environment variable must be set}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="evalforge-extraction"
JOB_NAME="evalforge-extraction-trigger"
SCHEDULE="${EXTRACTION_SCHEDULE:-*/30 * * * *}"  # Every 30 minutes by default
TIME_ZONE="America/New_York"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}Deploying Cloud Scheduler for extraction service...${NC}"
echo "  Project: ${PROJECT_ID}"
echo "  Region: ${REGION}"
echo "  Service: ${SERVICE_NAME}"
echo "  Schedule: ${SCHEDULE}"
echo ""

# Step 1: Get Cloud Run service URL
echo -e "${YELLOW}[1/4] Fetching Cloud Run service URL...${NC}"
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format='value(status.url)' 2>/dev/null || echo "")

if [ -z "$SERVICE_URL" ]; then
  echo -e "${RED}✗ Cloud Run service '${SERVICE_NAME}' not found in ${REGION}${NC}"
  echo "  Please deploy the extraction service first using ./scripts/deploy.sh"
  exit 1
fi

echo -e "${GREEN}✓ Service URL: ${SERVICE_URL}${NC}"
ENDPOINT="${SERVICE_URL}/extraction/run-once"

# Step 2: Get or create service account for invoker
echo -e "${YELLOW}[2/4] Setting up service account...${NC}"
INVOKER_SA="cloud-scheduler-invoker@${PROJECT_ID}.iam.gserviceaccount.com"

# Check if service account exists
if ! gcloud iam service-accounts describe "${INVOKER_SA}" \
  --project="${PROJECT_ID}" &>/dev/null; then

  echo "  Creating service account..."
  gcloud iam service-accounts create cloud-scheduler-invoker \
    --display-name="Cloud Scheduler Invoker" \
    --project="${PROJECT_ID}"
fi

# Grant invoker role on Cloud Run service
echo "  Granting Cloud Run Invoker role..."
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:${INVOKER_SA}" \
  --role="roles/run.invoker" \
  --quiet

echo -e "${GREEN}✓ Service account configured${NC}"

# Step 3: Create or update scheduler job
echo -e "${YELLOW}[3/4] Creating/updating Cloud Scheduler job...${NC}"

# Check if job exists
if gcloud scheduler jobs describe "${JOB_NAME}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" &>/dev/null; then

  echo "  Updating existing job..."
  gcloud scheduler jobs update http "${JOB_NAME}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}" \
    --schedule="${SCHEDULE}" \
    --time-zone="${TIME_ZONE}" \
    --uri="${ENDPOINT}" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{"batchSize":50,"triggeredBy":"cloud-scheduler"}' \
    --oidc-service-account-email="${INVOKER_SA}" \
    --oidc-token-audience="${SERVICE_URL}" \
    --quiet
else
  echo "  Creating new job..."
  gcloud scheduler jobs create http "${JOB_NAME}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}" \
    --schedule="${SCHEDULE}" \
    --time-zone="${TIME_ZONE}" \
    --uri="${ENDPOINT}" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{"batchSize":50,"triggeredBy":"cloud-scheduler"}' \
    --oidc-service-account-email="${INVOKER_SA}" \
    --oidc-token-audience="${SERVICE_URL}" \
    --quiet
fi

echo -e "${GREEN}✓ Scheduler job configured${NC}"

# Step 4: Test the job
echo -e "${YELLOW}[4/4] Testing scheduler job...${NC}"
echo "  Running job manually to verify setup..."

gcloud scheduler jobs run "${JOB_NAME}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --quiet

echo -e "${GREEN}✓ Test run triggered${NC}"
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ Extraction scheduler deployed successfully${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Job details:"
echo "  Name: ${JOB_NAME}"
echo "  Schedule: ${SCHEDULE} (${TIME_ZONE})"
echo "  Endpoint: ${ENDPOINT}"
echo ""
echo "View job:"
echo "  gcloud scheduler jobs describe ${JOB_NAME} --location=${REGION} --project=${PROJECT_ID}"
echo ""
echo "View job logs:"
echo "  gcloud logging read 'resource.type=cloud_scheduler_job AND resource.labels.job_id=${JOB_NAME}' --project=${PROJECT_ID} --limit=10"
echo ""
echo "Pause/resume job:"
echo "  gcloud scheduler jobs pause ${JOB_NAME} --location=${REGION} --project=${PROJECT_ID}"
echo "  gcloud scheduler jobs resume ${JOB_NAME} --location=${REGION} --project=${PROJECT_ID}"
