# Quickstart: Datadog Dashboard Integration

**Feature Branch**: `007-datadog-dashboard`
**Last Updated**: 2025-12-29

## Prerequisites

- [ ] Python 3.11+ installed
- [ ] Google Cloud SDK (`gcloud`) configured for project `konveyn2ai`
- [ ] Datadog account with API access
- [ ] Issue #8 Approval Workflow API deployed

## Environment Setup

### 1. Install Dependencies

```bash
# Activate virtual environment
source evalforge_venv/bin/activate

# Install dashboard dependencies
pip install datadog-api-client functions-framework
```

### 2. Configure Secrets

Add the following to Google Cloud Secret Manager:

```bash
# Datadog API Key (for metrics submission)
echo -n "your_dd_api_key" | gcloud secrets create DATADOG_API_KEY --data-file=-

# Datadog App Key (for App Builder if needed)
echo -n "your_dd_app_key" | gcloud secrets create DATADOG_APP_KEY --data-file=-
```

### 3. Update .env

```bash
# Add to .env.local
DATADOG_API_KEY=your_dd_api_key
DATADOG_APP_KEY=your_dd_app_key
DATADOG_SITE=datadoghq.com  # or datadoghq.eu, us3.datadoghq.com, etc.
```

## Local Development

### Run Metrics Publisher Locally

```bash
# Test metrics aggregation
PYTHONPATH=src python -c "
from dashboard.metrics_publisher import aggregate_and_publish
aggregate_and_publish()
"

# Run as local Cloud Function
functions-framework --target=publish_metrics --debug
```

### Verify Metrics in Datadog

1. Open Datadog Metrics Explorer
2. Search for `evalforge.suggestions.*`
3. Verify metrics appear within 2 minutes of publishing

## Deployment

### Deploy Metrics Publisher Cloud Function

```bash
# Deploy to Cloud Functions (authenticated - requires IAM for invocation)
gcloud functions deploy evalforge-metrics-publisher \
  --runtime python311 \
  --trigger-http \
  --entry-point publish_metrics \
  --source src/dashboard/ \
  --set-secrets DATADOG_API_KEY=DATADOG_API_KEY:latest \
  --region us-central1 \
  --no-allow-unauthenticated

# Create a service account for Cloud Scheduler to invoke the function
gcloud iam service-accounts create evalforge-scheduler-sa \
  --display-name="EvalForge Scheduler Service Account" \
  --project=konveyn2ai

# Grant the service account permission to invoke the Cloud Function
gcloud functions add-invoker-policy-binding evalforge-metrics-publisher \
  --region=us-central1 \
  --member="serviceAccount:evalforge-scheduler-sa@konveyn2ai.iam.gserviceaccount.com"

# Create Cloud Scheduler job with OIDC authentication (every 60 seconds)
gcloud scheduler jobs create http evalforge-metrics-job \
  --schedule="* * * * *" \
  --uri="https://us-central1-konveyn2ai.cloudfunctions.net/evalforge-metrics-publisher" \
  --http-method=POST \
  --location=us-central1 \
  --oidc-service-account-email=evalforge-scheduler-sa@konveyn2ai.iam.gserviceaccount.com \
  --oidc-token-audience=https://us-central1-konveyn2ai.cloudfunctions.net/evalforge-metrics-publisher
```

> **Security Note**: The function is deployed with `--no-allow-unauthenticated` to prevent
> unauthorized access. Cloud Scheduler uses OIDC tokens to authenticate, ensuring only
> authorized invocations can trigger the metrics publisher and protecting against
> quota/cost abuse.

## App Builder Setup

### Create App in Datadog UI

1. Navigate to **Service Management > App Builder**
2. Click **New App**
3. Name: "EvalForge Approval Queue"

### Configure HTTP Connection

1. Go to **Connections** in App Builder
2. Add new **HTTP** connection
3. Configure:
   - Name: `evalforge-api`
   - Base URL: `https://your-cloud-run-url.run.app`
   - Authentication: Token Auth
   - Token Name: `Authorization`
   - Token Value: `Bearer <your_api_key>`

### Add Table Component

1. Drag **Table** component to canvas
2. Configure data source:
   - Type: HTTP Query
   - Connection: `evalforge-api`
   - Method: GET
   - Path: `/suggestions?status=pending`
3. Configure columns:
   - ID: `${row.suggestion_id.slice(0, 8)}`
   - Type: `${row.type}` (format: status pill)
   - Severity: `${row.severity}` (format: status pill)
   - Age: `${formatRelativeTime(row.created_at)}`

### Add Action Buttons

1. Add **Row Actions** to table
2. Add "Approve" button:
   - Intent: success
   - Click Event: Execute Query
   - Query: HTTP POST to `/suggestions/${row.suggestion_id}/approve`
3. Add "Reject" button:
   - Intent: danger
   - Click Event: Execute Query
   - Query: HTTP POST to `/suggestions/${row.suggestion_id}/reject`

### Embed in Dashboard

1. Go to **Dashboards**
2. Create or edit dashboard
3. Add **App Widget**
4. Select "EvalForge Approval Queue" app

### Add Metrics Widgets

Add the following widgets to the dashboard:

| Widget Type | Metric | Title |
|-------------|--------|-------|
| Query Value | `evalforge.suggestions.pending` | Pending |
| Query Value | `evalforge.suggestions.approved` | Approved |
| Pie Chart | `evalforge.suggestions.by_type` | By Type |
| Timeseries | `evalforge.suggestions.pending` | Trend |

## Testing

### Run Live Integration Tests

```bash
# Ensure credentials are set
export RUN_LIVE_TESTS=1

# Run dashboard tests
PYTHONPATH=src python -m pytest tests/integration/test_dashboard_live.py -v
```

### Manual Smoke Test

1. Open dashboard in Datadog
2. Verify metrics widgets show data
3. Click "Approve" on a suggestion
4. Verify status updates within 3 seconds
5. Verify "Pending" count decrements

## Troubleshooting

### Metrics Not Appearing

```bash
# Check Cloud Function logs
gcloud functions logs read evalforge-metrics-publisher --limit 50

# Verify API key
curl -X POST "https://api.datadoghq.com/api/v2/series" \
  -H "DD-API-KEY: $DATADOG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"series":[{"metric":"evalforge.test","type":3,"points":[{"timestamp":'$(date +%s)',"value":1}]}]}'
```

### App Builder Actions Failing

1. Check HTTP connection status in App Builder
2. Verify Approval API is deployed and accessible
3. Check browser console for CORS errors
4. Verify Token Auth is configured correctly

### Firestore Permission Errors

```bash
# Verify service account has Firestore read access
gcloud projects get-iam-policy konveyn2ai \
  --flatten="bindings[].members" \
  --filter="bindings.role:roles/datastore.user"
```

## Architecture Reference

```
Cloud Scheduler (every 60s)
         │
         ▼
Cloud Function (metrics_publisher.py)
         │
         ├── Read: Firestore (evalforge_suggestions)
         │
         └── Write: Datadog Metrics API
                      │
                      ▼
              Datadog Dashboard
              ├── Metrics Widgets (query values, charts)
              └── App Builder App (table + action buttons)
                           │
                           ▼
                   Approval API (Issue #8)
                           │
                           ▼
                   Firestore (update status)
```
