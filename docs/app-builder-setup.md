# Datadog App Builder Setup Guide

Step-by-step instructions for configuring the EvalForge Approval Dashboard using Datadog App Builder.

## Prerequisites

- Datadog account with App Builder access
- EvalForge Approval API deployed (Issue #8)
- Metrics Publisher Cloud Function deployed (Issue #7)
- API key for Approval API authentication

## Overview

The dashboard consists of:
1. **App Builder App**: Interactive table with approve/reject buttons
2. **Metrics Widgets**: Query values, pie chart, and trend line

---

## Part 1: Create App Builder App

### Step 1: Create New App

1. Navigate to **Service Management → App Builder**
2. Click **+ New App**
3. Configure:
   - **Name**: `EvalForge Approval Queue`
   - **Description**: `Approve or reject EvalForge improvement suggestions`
4. Click **Create**

### Step 2: Configure HTTP Connection

1. In the App Builder editor, click **Connections** in the left panel
2. Click **+ New Connection**
3. Select **HTTP**
4. Configure connection:

| Field | Value |
|-------|-------|
| **Name** | `evalforge-api` |
| **Base URL** | `https://your-approval-api.run.app/approval` |
| **Authentication** | None (use custom header instead) |

5. Click **Headers** tab and add custom header:

| Header Name | Header Value |
|-------------|--------------|
| `X-API-Key` | `<your_api_key>` |

6. Click **Save**

> **Note**: The API uses `X-API-Key` header authentication, not Bearer tokens.
> Datadog's Token Auth sends `Authorization: Bearer ...` which won't work.

### Step 3: Create Data Query

1. Click **Queries** in the left panel
2. Click **+ New Query**
3. Configure:

| Field | Value |
|-------|-------|
| **Name** | `getPendingSuggestions` |
| **Type** | HTTP |
| **Connection** | `evalforge-api` |
| **Method** | GET |
| **Path** | `/suggestions?status=pending&limit=100` |

4. Click **Run** to test
5. Click **Save**

---

## Part 2: Add Approval Queue Table (T019)

### Step 4: Add Table Component

1. Drag **Table** component from Components panel to canvas
2. Configure data binding:
   - **Data Source**: `getPendingSuggestions`
   - **Data Path**: `suggestions` (or root if array)

### Step 5: Configure Table Columns

| Column | Source | Format |
|--------|--------|--------|
| **ID** | `${row.suggestion_id.slice(0, 8)}` | Text |
| **Type** | `${row.type}` | Status Pill |
| **Severity** | `${row.severity}` | Status Pill |
| **Age** | `${formatRelativeTime(row.created_at)}` | Text |

**Status Pill Colors for Type**:
- `eval` → Blue
- `guardrail` → Orange
- `runbook` → Green

**Status Pill Colors for Severity**:
- `critical` → Red
- `high` → Orange
- `medium` → Yellow
- `low` → Gray

### Step 6: Configure Table Sorting (T019a)

1. Click on the table component
2. Go to **Settings → Sorting**
3. Add sort rules:
   - **Primary**: `severity` (Descending) - Critical first
   - **Secondary**: `created_at` (Ascending) - Oldest first

---

## Part 3: Add Action Buttons (Phase 4 - T021-T025)

### Step 7: Create Approve Query (T021)

1. Click **Queries → + New Query**
2. Configure:

| Field | Value |
|-------|-------|
| **Name** | `approveSuggestion` |
| **Type** | HTTP |
| **Connection** | `evalforge-api` |
| **Method** | POST |
| **Path** | `/suggestions/${row.suggestion_id}/approve` |
| **Body** | `{}` |

### Step 8: Create Reject Query

1. Click **Queries → + New Query**
2. Configure:

| Field | Value |
|-------|-------|
| **Name** | `rejectSuggestion` |
| **Type** | HTTP |
| **Connection** | `evalforge-api` |
| **Method** | POST |
| **Path** | `/suggestions/${row.suggestion_id}/reject` |
| **Body** | `{"reason": "Rejected via dashboard"}` |

### Step 9: Add Row Actions (T022-T023)

1. Select the Table component
2. Go to **Settings → Row Actions**
3. Add **Approve** button:
   - **Label**: `✓ Approve`
   - **Intent**: Success (green)
   - **On Click**: Execute Query → `approveSuggestion`

4. Add **Reject** button:
   - **Label**: `✗ Reject`
   - **Intent**: Danger (red)
   - **On Click**: Execute Query → `rejectSuggestion`

### Step 10: Add Toast Notifications (T024)

1. For each action query, add **On Success** handler:
   ```javascript
   showToast({
     message: "Suggestion ${action}d successfully",
     intent: "success"
   });
   ```

2. Add **On Error** handler:
   ```javascript
   showToast({
     message: "Failed to ${action} suggestion: ${error.message}",
     intent: "danger"
   });
   ```

### Step 11: Configure Table Refresh (T025)

1. After each action query, add:
   - **Then**: Trigger Query → `getPendingSuggestions`

   This refreshes the table after approve/reject.

---

## Part 4: Add Metrics Widgets

### Step 12: Add Pending Count Widget (T018)

1. Create a new Datadog Dashboard or edit existing
2. Add **Query Value** widget
3. Configure:

| Field | Value |
|-------|-------|
| **Metric** | `evalforge.suggestions.pending` |
| **Title** | `Pending Suggestions` |
| **Aggregator** | `last` |
| **Tags** | `env:production` |

### Step 13: Add Approved Count Widget

1. Add another **Query Value** widget
2. Configure:

| Field | Value |
|-------|-------|
| **Metric** | `evalforge.suggestions.approved` |
| **Title** | `Approved` |
| **Aggregator** | `last` |

### Step 14: Embed App in Dashboard

1. In the Dashboard, click **Add Widget**
2. Select **Apps**
3. Choose `EvalForge Approval Queue`
4. Resize to desired dimensions

---

## Part 5: Add Trend Chart (Phase 5 - T028)

### Step 15: Add Timeseries Widget

1. Add **Timeseries** widget to dashboard
2. Configure:

| Field | Value |
|-------|-------|
| **Title** | `Suggestions Trend (7 days)` |
| **Display** | Line |

3. Add metrics:
   - **Line 1**: `evalforge.suggestions.pending` (label: "Pending")
   - **Line 2**: `evalforge.suggestions.approved` (label: "Approved")

4. Set time range: **Past 7 Days**

---

## Part 6: Add Pie Chart (Phase 6 - T030)

### Step 16: Add Pie Chart Widget

1. Add **Pie Chart** widget
2. Configure:

| Field | Value |
|-------|-------|
| **Title** | `Suggestions by Type` |
| **Metric** | `evalforge.suggestions.by_type` |
| **Group By** | `type` |

---

## Part 7: Add Coverage Widget (Phase 7 - T032)

### Step 17: Add Coverage Query Value

1. Add **Query Value** widget
2. Configure:

| Field | Value |
|-------|-------|
| **Metric** | `evalforge.coverage.improvement` |
| **Title** | `Coverage Improvement` |
| **Unit** | `percent` |

---

## Troubleshooting (T035)

### App Builder Actions Failing

1. **Check HTTP Connection**:
   - Verify Base URL is correct
   - Test connection in App Builder Connections panel
   - Check API key is valid

2. **CORS Errors**:
   - Ensure Approval API allows requests from `*.datadoghq.com`
   - Check browser console for specific CORS headers

3. **Authentication Errors**:
   - Verify Token Auth is configured correctly
   - Token format: `Bearer <api_key>` (with space)

### Metrics Not Appearing

1. **Check Cloud Function**:
   ```bash
   gcloud functions logs read evalforge-metrics-publisher --limit 50
   ```

2. **Verify API Key**:
   ```bash
   curl -X POST "https://api.us5.datadoghq.com/api/v2/series" \
     -H "DD-API-KEY: $DATADOG_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"series":[{"metric":"evalforge.test","type":3,"points":[{"timestamp":'$(date +%s)',"value":1}]}]}'
   ```

3. **Check Metrics Explorer**:
   - Open Datadog Metrics Explorer
   - Search for `evalforge.*`
   - Metrics may take up to 2 minutes to appear

### Table Not Loading

1. **Test Query Manually**:
   - In App Builder, click **Run** on `getPendingSuggestions`
   - Check response format

2. **Verify Data Path**:
   - If response is `{"suggestions": [...]}`, set Data Path to `suggestions`
   - If response is `[...]`, leave Data Path empty

---

## Dashboard Layout Suggestion

```
┌──────────────────────────────────────────────────────────────┐
│  Pending: 12  │  Approved: 45  │  Rejected: 3  │  Coverage: 5%│
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │            EvalForge Approval Queue (App)              │  │
│  │  ┌────────┬────────┬──────────┬──────┬───────────────┐ │  │
│  │  │ ID     │ Type   │ Severity │ Age  │ Actions       │ │  │
│  │  ├────────┼────────┼──────────┼──────┼───────────────┤ │  │
│  │  │ abc123 │ eval   │ critical │ 2h   │ [✓] [✗]      │ │  │
│  │  │ def456 │ guard. │ high     │ 5h   │ [✓] [✗]      │ │  │
│  │  └────────┴────────┴──────────┴──────┴───────────────┘ │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────┐  ┌────────────────────────────┐ │
│  │   Type Distribution     │  │   Suggestions Trend        │ │
│  │      (Pie Chart)        │  │      (Line Chart)          │ │
│  │                         │  │                            │ │
│  │    [eval] [guard] [run] │  │  ___/\___/\___             │ │
│  └─────────────────────────┘  └────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```
