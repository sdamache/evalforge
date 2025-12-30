# Datadog Dashboard Integration Research

**Feature Branch**: `007-datadog-dashboard`
**Research Date**: 2025-12-29
**Status**: Verified via Web Search

## Executive Summary

Research confirms that **Datadog App Builder** is the recommended approach for interactive dashboard functionality. The previously considered **UI Extensions** were deprecated on March 31, 2025. For hackathon speed, an **Iframe Widget** embedding our own approval UI is the fastest option.

---

## Integration Options Comparison

| Option | Difficulty | Time | Best For | Hackathon Viability |
|--------|------------|------|----------|---------------------|
| **Iframe Widget** | Very Low | 5-10 min | Embed external web page | Fastest option |
| **App Builder** | Moderate | 1-2 hrs | Interactive approve/reject buttons | Recommended |
| **Webhooks** | Low | 15-20 min | Send alerts to our API | Good for notifications |
| **Dashboard API** | Moderate | 1-2 hrs | Programmatic dashboard creation | No interactivity |
| **UI Extensions** | N/A | N/A | Custom React components | Deprecated Mar 2025 |

---

## Option A: Iframe Widget (Fastest - 5-10 min)

### How It Works
Embed a custom web page directly in a Datadog dashboard using the Iframe widget.

### Implementation
1. Build a simple HTML/React approval UI that calls the Evalforge Approval API
2. Host it (e.g., Cloud Run static site or Firebase Hosting)
3. Add an Iframe widget to the Datadog dashboard with the hosted URL

### Verified Capabilities
- Available on FREE layout dashboards
- Accepts any HTTPS URL
- Configuration is just entering the URL in the widget settings
- API-compatible for programmatic dashboard creation

### Limitations
- External site must allow framing (X-Frame-Options header)
- HTTP URLs require browser configuration for non-secure content
- Limited integration with Datadog template variables
- Separate web application to build and host

### Source
- [Iframe Widget Documentation](https://docs.datadoghq.com/dashboards/widgets/iframe/)

---

## Option B: App Builder (Recommended - 1-2 hrs)

### How It Works
Build a low-code app in Datadog's App Builder with drag-and-drop UI components that trigger HTTP requests to our API.

### Verified Capabilities

**UI Components Available:**
- **Buttons**: Configurable with intents (default, danger, success, warning), click events trigger actions
- **Tables**: Sortable, filterable, searchable with row action buttons
- **Modals**: For confirmation dialogs
- **Text inputs, selection lists**: For forms

**Event Handling:**
Buttons support click events with reactions including:
- Custom functions
- Query execution (HTTP requests)
- Modal management
- URL navigation
- Toast notifications

**Dashboard Integration:**
- Apps embed as "App Widget" in dashboards
- Sync with dashboard template variables and timeframes
- Access dashboard context: `${global?.dashboard?.templateVariables?.find(v => v.name === '<NAME>')?.value}`

**HTTP Request Configuration:**
- Full control over request methods (GET, POST, etc.)
- Multiple authentication methods: Token Auth, Basic Auth, API Key, OAuth, mTLS
- Configurable headers, body, URL parameters
- Error handling with status code triggers

### Architecture for Evalforge

```
┌─────────────────────────────────────────────────────────┐
│              Datadog App Builder App                    │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Table: Pending Suggestions                      │   │
│  │  ┌──────────────────────────────────────────┐   │   │
│  │  │ ID    │ Type     │ Severity │ Actions    │   │   │
│  │  │ sg_01 │ Guardrail│ High     │ [✓] [✗]   │   │   │
│  │  │ sg_02 │ Eval     │ Medium   │ [✓] [✗]   │   │   │
│  │  └──────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
         │ Button Click                    │
         ▼                                 ▼
   POST /suggestions/{id}/approve    POST /suggestions/{id}/reject
         │                                 │
         └─────────────────────────────────┘
                       │
                       ▼
              Evalforge Approval API
```

### Sources
- [App Builder Product Page](https://www.datadoghq.com/product/app-builder/)
- [App Builder Documentation](https://docs.datadoghq.com/actions/app_builder/)
- [Embedded Apps](https://docs.datadoghq.com/actions/app_builder/embedded_apps/)
- [Components](https://docs.datadoghq.com/actions/app_builder/components/)
- [HTTP Connections](https://docs.datadoghq.com/actions/connections/http/)

---

## UI Extensions Deprecation (CRITICAL)

### Status: DEPRECATED

> **Datadog UI Extensions were discontinued on March 31, 2025.**

The DataDog/apps repository was archived on September 18, 2025 and is now read-only.

### Migration Path
Datadog recommends migrating to **App Builder** which provides equivalent functionality:
- Read and write to external providers
- Custom UI components
- HTTP request integration

### Source
- [LaunchDarkly Datadog Integration](https://launchdarkly.com/docs/integrations/datadog)
- [DataDog/apps GitHub Repository](https://github.com/DataDog/apps) (Archived)

---

## Recommendation for Evalforge

### Primary: App Builder (for production-quality demo)

**Pros:**
- Native Datadog experience
- No external hosting required
- Built-in authentication options
- Integrates with dashboard context
- Professional appearance

**Implementation Steps:**
1. Create App Builder app with table component showing suggestions
2. Add row action buttons (Approve/Reject)
3. Configure HTTP request actions to call Approval API
4. Set up Token Auth with API key
5. Embed as App Widget in dashboard

### Fallback: Iframe Widget (for speed)

**Pros:**
- Fastest implementation (5-10 min)
- Full control over UI
- Can reuse existing React components

**Implementation Steps:**
1. Create simple React/HTML approval UI
2. Host on Cloud Run or Firebase Hosting
3. Embed URL in Iframe widget

---

## Metrics Publisher Architecture

Regardless of dashboard approach, we need a metrics publisher to push Firestore data to Datadog:

```
Cloud Scheduler (every 60s)
         │
         ▼
Cloud Function / Cloud Run
         │
         ├── Read from Firestore (evalforge_suggestions)
         │
         └── Push to Datadog Metrics API
               ├── evalforge.suggestions.pending
               ├── evalforge.suggestions.approved
               ├── evalforge.suggestions.rejected
               ├── evalforge.suggestions.by_type (tagged)
               └── evalforge.suggestions.by_severity (tagged)
```

### Datadog Metrics API
- Submit metrics via POST to `https://api.datadoghq.com/api/v2/series`
- Authentication: DD-API-KEY header
- Python SDK: `datadog-api-client` library

---

## Impact on Specification

### Changes Required

1. **Remove**: References to "deep links" for action buttons (App Builder uses HTTP requests instead)
2. **Add**: App Builder as primary implementation approach
3. **Clarify**: Dashboard creation is via App Builder UI, not Dashboard API programmatically
4. **Keep**: Metrics publisher architecture (still needed for dashboard widgets)

### Scope Adjustment

| Original Assumption | Updated Understanding |
|--------------------|-----------------------|
| Dashboard API for programmatic creation | App Builder for interactive apps |
| Deep links to Approval API | HTTP request actions triggered by buttons |
| UI Extensions possible | UI Extensions deprecated - use App Builder |

---

## References

### Official Documentation
- [App Builder](https://docs.datadoghq.com/actions/app_builder/)
- [Embedded Apps](https://docs.datadoghq.com/actions/app_builder/embedded_apps/)
- [Components](https://docs.datadoghq.com/actions/app_builder/components/)
- [HTTP Connections](https://docs.datadoghq.com/actions/connections/http/)
- [Iframe Widget](https://docs.datadoghq.com/dashboards/widgets/iframe/)

### Blog Posts
- [Build custom monitoring and remediation tools with Datadog App Builder](https://www.datadoghq.com/blog/datadog-app-builder-low-code-internal-tools/)
- [Remediate faster with apps built using Datadog App Builder](https://www.datadoghq.com/blog/app-builder-remediation/)
