# Quickstart: GCP Infrastructure Setup

**Feature**: 011-gcp-infra-automation
**Time Required**: ~15 minutes total

## Prerequisites

Before running the setup scripts, ensure you have:

1. **GCP Project with Billing Enabled**
   - Create project at https://console.cloud.google.com
   - Enable billing at https://console.cloud.google.com/billing

2. **gcloud CLI Installed and Authenticated**
   ```bash
   # Install: https://cloud.google.com/sdk/docs/install
   gcloud version  # Should show version info

   # Authenticate
   gcloud auth login
   gcloud auth application-default login
   ```

3. **Docker Installed** (for local testing only)
   ```bash
   docker --version  # Should show version info
   ```

## Step 1: Set Environment Variables

```bash
# Required: Your GCP project ID
export GCP_PROJECT_ID="your-project-id"

# Optional: Override defaults
export GCP_REGION="us-central1"          # Default: us-central1
export SERVICE_NAME="evalforge-ingestion" # Default: evalforge-ingestion
export DATADOG_SITE="us5.datadoghq.com"  # Default: us5.datadoghq.com
```

## Step 2: Run Bootstrap Script

```bash
# From repository root
./scripts/bootstrap_gcp.sh
```

**Expected output**:
```
[2025-12-12 10:00:00] [INFO] Starting GCP bootstrap for project: your-project-id
[2025-12-12 10:00:05] [INFO] Enabling API: run.googleapis.com... done
[2025-12-12 10:00:10] [INFO] Enabling API: firestore.googleapis.com... done
[2025-12-12 10:00:15] [INFO] Enabling API: secretmanager.googleapis.com... done
[2025-12-12 10:00:20] [INFO] Enabling API: cloudscheduler.googleapis.com... done
[2025-12-12 10:00:25] [INFO] Enabling API: cloudbuild.googleapis.com... done
[2025-12-12 10:00:30] [INFO] Creating Firestore database... done
[2025-12-12 10:00:35] [INFO] Creating service account: evalforge-ingestion-sa... done
[2025-12-12 10:00:40] [INFO] Granting IAM role: roles/datastore.user... done
[2025-12-12 10:00:45] [INFO] Granting IAM role: roles/secretmanager.secretAccessor... done
[2025-12-12 10:00:50] [INFO] Creating secret: datadog-api-key... done
[2025-12-12 10:00:55] [INFO] Creating secret: datadog-app-key... done
[2025-12-12 10:01:00] [INFO] Running Firestore collection bootstrap... done
[2025-12-12 10:01:05] [SUCCESS] Bootstrap complete!

=== NEXT STEPS ===
1. Update Datadog API credentials in Secret Manager:

   # Via gcloud CLI:
   echo -n "your-actual-api-key" | gcloud secrets versions add datadog-api-key --data-file=- --project=$GCP_PROJECT_ID
   echo -n "your-actual-app-key" | gcloud secrets versions add datadog-app-key --data-file=- --project=$GCP_PROJECT_ID

   # Or via GCP Console:
   https://console.cloud.google.com/security/secret-manager?project=your-project-id

2. Run the deploy script:
   ./scripts/deploy.sh
```

**Time**: ~5 minutes

## Step 3: Update Datadog Secrets

After bootstrap, update the placeholder secrets with your actual Datadog credentials:

```bash
# Get your Datadog API key from: https://app.datadoghq.com/organization-settings/api-keys
# Get your Datadog App key from: https://app.datadoghq.com/organization-settings/application-keys

# Update secrets via gcloud
echo -n "your-actual-datadog-api-key" | \
  gcloud secrets versions add datadog-api-key --data-file=- --project=$GCP_PROJECT_ID

echo -n "your-actual-datadog-app-key" | \
  gcloud secrets versions add datadog-app-key --data-file=- --project=$GCP_PROJECT_ID
```

**Time**: ~2 minutes

## Step 4: Run Deploy Script

```bash
# From repository root
./scripts/deploy.sh
```

**Expected output**:
```
[2025-12-12 10:10:00] [INFO] Starting deployment for project: your-project-id
[2025-12-12 10:10:05] [INFO] Building Docker image via Cloud Build...
[2025-12-12 10:12:00] [INFO] Image built: gcr.io/your-project-id/evalforge-ingestion:latest
[2025-12-12 10:12:05] [INFO] Deploying to Cloud Run...
[2025-12-12 10:13:00] [INFO] Service deployed: https://evalforge-ingestion-xxxxx-uc.a.run.app
[2025-12-12 10:13:05] [INFO] Creating Cloud Scheduler job...
[2025-12-12 10:13:10] [INFO] Scheduler job created: evalforge-ingestion-trigger (every 5 minutes)
[2025-12-12 10:13:15] [SUCCESS] Deployment complete!

=== SERVICE INFO ===
Service URL: https://evalforge-ingestion-xxxxx-uc.a.run.app
Scheduler Job: evalforge-ingestion-trigger
Schedule: */5 * * * * (every 5 minutes)

=== VERIFY DEPLOYMENT ===
# Trigger scheduler manually:
gcloud scheduler jobs run evalforge-ingestion-trigger --location=us-central1 --project=$GCP_PROJECT_ID

# View Cloud Run logs:
gcloud run services logs read evalforge-ingestion --region=us-central1 --project=$GCP_PROJECT_ID --limit=50
```

**Time**: ~5 minutes

## Step 5: Verify Deployment

```bash
# Manually trigger the scheduler job
gcloud scheduler jobs run evalforge-ingestion-trigger \
  --location=us-central1 \
  --project=$GCP_PROJECT_ID

# Check Cloud Run logs (wait ~30 seconds)
gcloud run services logs read evalforge-ingestion \
  --region=us-central1 \
  --project=$GCP_PROJECT_ID \
  --limit=50
```

**Expected behavior**: Logs should show ingestion execution starting.

## Troubleshooting

### Error: "GCP_PROJECT_ID not set"

```bash
export GCP_PROJECT_ID="your-project-id"
```

### Error: "Billing not enabled"

1. Go to https://console.cloud.google.com/billing
2. Link a billing account to your project

### Error: "Permission denied"

```bash
# Ensure you're authenticated
gcloud auth login

# Ensure you have sufficient permissions (Editor or Owner role on project)
gcloud projects get-iam-policy $GCP_PROJECT_ID --format="table(bindings.role)"
```

### Error: "API not enabled"

The bootstrap script should enable APIs automatically. If it fails:
```bash
gcloud services enable run.googleapis.com --project=$GCP_PROJECT_ID
gcloud services enable firestore.googleapis.com --project=$GCP_PROJECT_ID
gcloud services enable secretmanager.googleapis.com --project=$GCP_PROJECT_ID
gcloud services enable cloudscheduler.googleapis.com --project=$GCP_PROJECT_ID
gcloud services enable cloudbuild.googleapis.com --project=$GCP_PROJECT_ID
```

### Error: "Firestore database already exists"

This is expected if running bootstrap twice. The script should skip creation.

### Error: "Cloud Scheduler 403 Forbidden"

Ensure the service account has the correct OIDC audience:
```bash
# The scheduler job audience must match the Cloud Run service URL
gcloud scheduler jobs describe evalforge-ingestion-trigger \
  --location=us-central1 \
  --project=$GCP_PROJECT_ID
```

## Cleanup (Manual)

To remove all resources (excluding Firestore database):

```bash
# Delete Cloud Scheduler job
gcloud scheduler jobs delete evalforge-ingestion-trigger \
  --location=us-central1 \
  --project=$GCP_PROJECT_ID \
  --quiet

# Delete Cloud Run service
gcloud run services delete evalforge-ingestion \
  --region=us-central1 \
  --project=$GCP_PROJECT_ID \
  --quiet

# Delete secrets
gcloud secrets delete datadog-api-key --project=$GCP_PROJECT_ID --quiet
gcloud secrets delete datadog-app-key --project=$GCP_PROJECT_ID --quiet

# Delete service account
gcloud iam service-accounts delete \
  evalforge-ingestion-sa@$GCP_PROJECT_ID.iam.gserviceaccount.com \
  --project=$GCP_PROJECT_ID \
  --quiet

# NOTE: Firestore database requires manual deletion via Console
# https://console.cloud.google.com/firestore?project=$GCP_PROJECT_ID
```

## Summary

| Step | Action | Time |
|------|--------|------|
| 1 | Set `GCP_PROJECT_ID` | 1 min |
| 2 | Run `bootstrap_gcp.sh` | 5 min |
| 3 | Update Datadog secrets | 2 min |
| 4 | Run `deploy.sh` | 5 min |
| 5 | Verify deployment | 2 min |
| **Total** | | **~15 min** |

## Next Steps

1. Monitor ingestion in Cloud Run logs
2. View Firestore data in GCP Console
3. Configure alerts for failures (optional)
4. Set up CI/CD for automated deployments (post-hackathon)
