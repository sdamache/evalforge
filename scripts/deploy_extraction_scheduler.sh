#!/bin/bash

# Deploy EvalForge Extraction Service to Google Cloud Run
# This script builds and deploys the extraction service with Cloud Scheduler

set -e

# Configuration variables from environment
PROJECT_ID=${GOOGLE_CLOUD_PROJECT:-"konveyn2ai"}
REGION=${GOOGLE_CLOUD_LOCATION:-"us-central1"}
REPOSITORY_NAME="evalforge"
SERVICE_NAME="evalforge-extraction"
SERVICE_ACCOUNT_EMAIL="evalforge-extraction-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# Load environment variables from .env file if it exists
if [ -f .env ]; then
    echo "📄 Loading environment variables from .env file..."
    export $(grep -v '^#' .env | xargs)
fi

echo "🚀 Deploying EvalForge Extraction Service to Google Cloud Run"
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo "Service: $SERVICE_NAME"
echo ""

# Deployment configuration
EXTRACTION_SCHEDULE="${EXTRACTION_SCHEDULE:-*/30 * * * *}"  # Every 30 minutes
GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.5-flash}"
GEMINI_TEMPERATURE="${GEMINI_TEMPERATURE:-0.2}"
BATCH_SIZE="${BATCH_SIZE:-50}"
DEPLOYMENT_TIMEOUT=600
HEALTH_CHECK_RETRIES=5
RETRY_DELAY=30

# Validate Docker and gcloud CLI availability
echo "🔧 Validating required tools..."
if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker is not installed or not in PATH"
    exit 1
fi

if ! command -v gcloud &> /dev/null; then
    echo "❌ Error: Google Cloud CLI is not installed or not in PATH"
    exit 1
fi

echo "✅ All validations passed"

# Configure Docker authentication for Artifact Registry
echo "🔐 Configuring Docker authentication for Artifact Registry..."
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet

# Build timestamp for image tagging
BUILD_TIMESTAMP=$(date +%Y%m%d-%H%M%S)
IMAGE_TAG="${BUILD_TIMESTAMP}-${RANDOM}"

echo "🏷️  Using image tag: $IMAGE_TAG"

# Function to wait for service deployment with timeout
wait_for_deployment() {
    local service_name=$1
    local timeout=$2
    local start_time=$(date +%s)

    echo "⏳ Waiting for $service_name deployment to complete (timeout: ${timeout}s)..."

    while true; do
        local current_time=$(date +%s)
        local elapsed=$((current_time - start_time))

        if [ $elapsed -gt $timeout ]; then
            echo "❌ Deployment timeout after ${timeout}s for $service_name"
            return 1
        fi

        # Check deployment status
        local status=$(gcloud run services describe $service_name --region=${REGION} --project=${PROJECT_ID} --format="value(status.conditions[0].status)" 2>/dev/null || echo "")

        if [ "$status" = "True" ]; then
            echo "✅ $service_name deployment completed successfully"
            return 0
        elif [ "$status" = "False" ]; then
            echo "❌ $service_name deployment failed"
            return 1
        fi

        echo "⏳ Still deploying $service_name... (${elapsed}s elapsed)"
        sleep 10
    done
}

# Function to test health endpoint with retry logic
test_health_endpoint() {
    local service_name=$1
    local service_url=$2
    local health_url="${service_url}/health"

    echo "🏥 Testing $service_name health endpoint..."

    for i in $(seq 1 $HEALTH_CHECK_RETRIES); do
        if curl -f --connect-timeout 10 "$health_url" > /dev/null 2>&1; then
            echo "✅ $service_name health check passed"
            return 0
        else
            echo "⚠️  $service_name health check failed (attempt $i/$HEALTH_CHECK_RETRIES)"
            if [ $i -lt $HEALTH_CHECK_RETRIES ]; then
                sleep $RETRY_DELAY
            fi
        fi
    done

    echo "❌ $service_name health check failed after $HEALTH_CHECK_RETRIES attempts"
    return 1
}

# Build and push Docker image
echo "🔨 Building and pushing Docker image..."
echo "📦 Building Extraction Service..."

# Check if Dockerfile.extraction exists
if [[ ! -f "Dockerfile.extraction" ]]; then
    echo "❌ Dockerfile.extraction not found in repository root"
    exit 1
fi

docker build --platform linux/amd64 -f Dockerfile.extraction \
    --build-arg GOOGLE_CLOUD_PROJECT="${PROJECT_ID}" \
    -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY_NAME}/${SERVICE_NAME}:${IMAGE_TAG} \
    -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY_NAME}/${SERVICE_NAME}:latest \
    .

# Verify build succeeded
if [ $? -eq 0 ]; then
    echo "✅ Extraction service build successful"
else
    echo "❌ Extraction service build failed"
    exit 1
fi

docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY_NAME}/${SERVICE_NAME}:${IMAGE_TAG}
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY_NAME}/${SERVICE_NAME}:latest

# Deploy to Cloud Run
echo "☁️  Deploying service to Cloud Run..."

gcloud run deploy ${SERVICE_NAME} \
    --image=${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY_NAME}/${SERVICE_NAME}:${IMAGE_TAG} \
    --region=${REGION} \
    --platform=managed \
    --memory=1Gi \
    --cpu=1 \
    --min-instances=0 \
    --max-instances=5 \
    --port=8080 \
    --timeout=600 \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},FIRESTORE_COLLECTION_PREFIX=evalforge_,VERTEX_AI_LOCATION=${REGION},GEMINI_MODEL=${GEMINI_MODEL},GEMINI_TEMPERATURE=${GEMINI_TEMPERATURE},GEMINI_MAX_OUTPUT_TOKENS=4096,BATCH_SIZE=${BATCH_SIZE},PER_TRACE_TIMEOUT_SEC=10" \
    --service-account=${SERVICE_ACCOUNT_EMAIL} \
    --no-allow-unauthenticated \
    --project=${PROJECT_ID}

# Wait for deployment to complete
wait_for_deployment "${SERVICE_NAME}" $DEPLOYMENT_TIMEOUT
if [ $? -ne 0 ]; then
    echo "❌ Extraction service deployment failed or timed out"
    exit 1
fi

# Get service URL
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region=${REGION} --project=${PROJECT_ID} --format="value(status.url)")
echo "✅ Extraction service deployed at: $SERVICE_URL"

# Test health endpoint
test_health_endpoint "${SERVICE_NAME}" "$SERVICE_URL"
HEALTH_STATUS=$?

# Setup Cloud Scheduler
echo "⏰ Setting up Cloud Scheduler..."
SCHEDULER_JOB_NAME="${SERVICE_NAME}-trigger"

# Check if job already exists
if gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}" &>/dev/null; then
    echo "♻️  Scheduler job exists, updating..."

    gcloud scheduler jobs update http "${SCHEDULER_JOB_NAME}" \
        --location="${REGION}" \
        --project="${PROJECT_ID}" \
        --schedule="${EXTRACTION_SCHEDULE}" \
        --uri="${SERVICE_URL}/extraction/run-once" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body='{"triggeredBy":"scheduled"}' \
        --oidc-service-account-email="${SERVICE_ACCOUNT_EMAIL}" \
        --quiet

    echo "✅ Cloud Scheduler job updated"
else
    echo "📅 Creating new Cloud Scheduler job..."

    gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
        --location="${REGION}" \
        --project="${PROJECT_ID}" \
        --schedule="${EXTRACTION_SCHEDULE}" \
        --uri="${SERVICE_URL}/extraction/run-once" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body='{"triggeredBy":"scheduled"}' \
        --oidc-service-account-email="${SERVICE_ACCOUNT_EMAIL}" \
        --time-zone="UTC" \
        --quiet

    echo "✅ Cloud Scheduler job created"
fi

# Grant invoker permission
echo "🔐 Granting Cloud Run Invoker permission..."
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="roles/run.invoker" \
    --quiet

echo "✅ Permissions granted"

# Output deployment summary
echo ""
echo "🎉 Deployment Complete!"
echo "===================="
echo "Extraction Service:   $SERVICE_URL"
echo "Schedule:             $EXTRACTION_SCHEDULE"
echo "Batch Size:           $BATCH_SIZE traces per run"
echo "Model:                $GEMINI_MODEL"
echo ""
echo "📋 Service Configuration:"
echo "- Memory: 1Gi"
echo "- CPU: 1"
echo "- Min instances: 0 (scales to zero)"
echo "- Max instances: 5"
echo "- Timeout: 10 minutes"
echo "- Service account: $SERVICE_ACCOUNT_EMAIL"
echo ""
echo "🔧 Useful Commands:"
echo "View logs:      gcloud logs tail --project=$PROJECT_ID --service=${SERVICE_NAME}"
echo "Manual trigger: gcloud scheduler jobs run ${SCHEDULER_JOB_NAME} --location=${REGION} --project=${PROJECT_ID}"
echo "View schedule:  gcloud scheduler jobs describe ${SCHEDULER_JOB_NAME} --location=${REGION} --project=${PROJECT_ID}"
echo "Pause job:      gcloud scheduler jobs pause ${SCHEDULER_JOB_NAME} --location=${REGION} --project=${PROJECT_ID}"
echo ""

if [ $HEALTH_STATUS -eq 0 ]; then
    echo "🎊 All health checks passed! Service is ready."
else
    echo "⚠️  Service deployed but health checks need verification."
    echo "💡 Check logs: gcloud logs tail --project=$PROJECT_ID --service=${SERVICE_NAME}"
fi
