# Feature Specification: Datadog Dashboard Integration

**Feature Branch**: `007-datadog-dashboard`
**Created**: 2025-12-29
**Status**: Draft
**Input**: User description: "Issue #7: Datadog Dashboard Integration - Dashboard showing pending improvements for ML engineers to review and approve suggestions during weekly quality meetings"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View Pending Suggestions Dashboard (Priority: P1)

As an ML engineer, I want to open a dashboard in Datadog that shows all pending improvement suggestions so that I can quickly see what needs my attention during my weekly quality review meeting without digging through Firestore or logs.

**Why this priority**: This is the core value proposition - without visibility into the improvement backlog, engineers don't know what to prioritize. The dashboard is the "single pane of glass" for the feedback loop.

**Independent Test**: Can be fully tested by loading the dashboard and verifying that pending suggestions appear with their type, severity, and age. Delivers immediate visibility into the approval backlog.

**Acceptance Scenarios**:

1. **Given** there are 5 pending suggestions in the system (2 eval, 2 guardrail, 1 runbook), **When** I open the EvalForge dashboard in Datadog, **Then** I see a summary showing "5 pending" with breakdown by type
2. **Given** the dashboard is open, **When** I look at the approval queue widget, **Then** I see all 5 suggestions listed with columns for ID, Type, Severity, and Age
3. **Given** the dashboard has loaded, **When** I measure the load time, **Then** the dashboard renders completely within 2 seconds
4. **Given** there are 1000+ suggestions in the system, **When** I load the dashboard, **Then** it still renders within 2 seconds without degradation

---

### User Story 2 - One-Click Suggestion Approval (Priority: P1)

As an ML engineer reviewing suggestions, I want to approve a suggestion with one click directly from the dashboard so that I can efficiently process my approval queue without leaving Datadog or using separate tools.

**Why this priority**: Without the ability to take action, the dashboard is just a read-only report. The one-click approval is what closes the feedback loop and makes the system actionable.

**Independent Test**: Can be fully tested by clicking an approve action on a pending suggestion and verifying the status updates. Delivers the core workflow of human-in-the-loop approval.

**Acceptance Scenarios**:

1. **Given** I see a pending suggestion in the approval queue, **When** I click the "Approve" action button, **Then** the suggestion status changes to "approved" within 3 seconds
2. **Given** I have just approved a suggestion, **When** I look at the summary stats widget, **Then** the "approved" count increments and "pending" count decrements in real-time
3. **Given** I see a pending suggestion, **When** I click the "Reject" action button, **Then** the suggestion status changes to "rejected" within 3 seconds

---

### User Story 3 - Track Approval Trends Over Time (Priority: P2)

As an ML engineer, I want to see a trend chart showing suggestions generated vs approved over time so that I can understand our team's approval velocity and identify if we're falling behind on reviews.

**Why this priority**: While not required for core functionality, trend visibility helps teams understand their review cadence and identify bottlenecks. This is important for process improvement.

**Independent Test**: Can be fully tested by viewing the trend chart and verifying it displays accurate historical data. Delivers insights into team velocity without affecting core approval workflow.

**Acceptance Scenarios**:

1. **Given** the dashboard is open, **When** I view the trend chart widget, **Then** I see lines for "generated" and "approved" suggestions over the last 7 days
2. **Given** suggestions have been generated and approved over the past week, **When** I hover over data points, **Then** I see the exact count for that time period

---

### User Story 4 - View Suggestion Distribution by Type (Priority: P2)

As an ML engineer, I want to see a breakdown of suggestions by type (eval, guardrail, runbook) so that I can understand what kinds of improvements the system is generating most frequently.

**Why this priority**: Type distribution helps teams understand failure patterns and prioritize which types of suggestions to focus on during reviews.

**Independent Test**: Can be fully tested by viewing the pie chart and verifying correct percentages. Delivers analytical insight without affecting core functionality.

**Acceptance Scenarios**:

1. **Given** there are suggestions of different types in the system, **When** I view the type breakdown widget, **Then** I see a pie chart showing percentage distribution across eval, guardrail, and runbook types
2. **Given** 60% of suggestions are evals, **When** I look at the pie chart, **Then** the eval slice shows approximately 60%

---

### User Story 5 - Monitor Coverage Improvement (Priority: P3)

As an ML engineer, I want to see a coverage improvement metric so that I can demonstrate the value of the feedback loop to stakeholders by showing how much our eval coverage has improved.

**Why this priority**: While not required for day-to-day operations, this metric is important for demonstrating ROI and justifying continued investment in the feedback loop.

**Independent Test**: Can be fully tested by viewing the coverage delta widget and verifying it calculates correctly. Delivers a business value metric.

**Acceptance Scenarios**:

1. **Given** 10 failures have been captured and 8 have approved eval test cases, **When** I view the coverage delta widget, **Then** I see "80% coverage improvement" or equivalent metric

---

### Edge Cases

- What happens when there are zero pending suggestions? Dashboard should display "0 pending" gracefully, not show an error
- How does the system handle a failed approval action? User should see an error message and the suggestion should remain in "pending" status
- What happens when Firestore data is stale or unavailable? Dashboard should show last known data with a "data may be stale" indicator
- How does the system handle concurrent approvals of the same suggestion? Only the first approval should succeed; subsequent attempts should show "already approved"
- What happens when the approval API is unavailable? Action buttons should be disabled or show an error, not fail silently

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST display a dashboard in Datadog UI showing pending suggestion counts with breakdown by type (eval, guardrail, runbook)
- **FR-002**: System MUST display an approval queue table showing: Suggestion ID, Type, Severity, Age, and Action buttons
- **FR-003**: System MUST provide one-click approve action that updates suggestion status to "approved"
- **FR-004**: System MUST provide one-click reject action that updates suggestion status to "rejected"
- **FR-005**: System MUST display a pie chart showing suggestion distribution by type
- **FR-006**: System MUST display a line chart showing suggestions generated vs approved over time (last 7 days)
- **FR-007**: System MUST display a coverage improvement metric (approved evals / total failures percentage)
- **FR-008**: System MUST push custom metrics to Datadog for dashboard widgets to consume
- **FR-009**: System MUST refresh dashboard data at regular intervals to show near real-time status (within 10 seconds of source data changes)
- **FR-010**: System MUST sort the approval queue by severity (critical first), then by age (oldest first)

### Key Entities

- **Dashboard**: The Datadog dashboard instance containing all widgets for EvalForge visibility
- **Suggestion**: An improvement suggestion (eval, guardrail, or runbook) with status (pending/approved/rejected), type, severity, and creation timestamp
- **Custom Metric**: A Datadog metric (evalforge.suggestions.*) representing aggregated data from Firestore suggestions
- **Action Button**: A dashboard element that triggers the approval/rejection workflow via HTTP request to the API (implemented via App Builder button component or iframe-embedded UI)

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Dashboard loads completely within 2 seconds for up to 1000 suggestions
- **SC-002**: Approve/reject actions complete within 3 seconds from click to visible status update
- **SC-003**: Dashboard data reflects Firestore changes within 10 seconds (near real-time)
- **SC-004**: Approved count increments in real-time on dashboard after approval action
- **SC-005**: ML engineers can complete a weekly review of 20 suggestions in under 10 minutes (vs. manual Firestore inspection)
- **SC-006**: 95% of dashboard page loads render successfully without errors

## Scope & Boundaries

### In Scope

- Interactive dashboard via Datadog App Builder (recommended) or Iframe Widget (fallback)
- Custom metrics pushed from a metrics publisher service
- HTTP request actions to Cloud Run approval API for approve/reject buttons
- Basic status (pending/approved/rejected) and type (eval/guardrail/runbook) filtering
- Dashboard components: summary stats, approval queue table, type breakdown chart, trend chart, coverage metric

### Out of Scope

- Datadog UI Extensions (deprecated March 2025 - do not use)
- Advanced filtering beyond basic status/type (e.g., date ranges, search, complex queries)
- Mobile-optimized dashboard layout
- Real-time streaming updates (polling-based refresh is sufficient)
- Export functionality from the dashboard (exports handled by separate API)

## Dependencies & Assumptions

### Dependencies

- **Issue #8 (Approval Workflow API)**: Dashboard action buttons link to the approval API endpoints. The API must exist and be deployed before dashboard actions can function.
- **Firestore suggestions collection**: Metrics publisher reads from `evalforge_suggestions` collection which must be populated by upstream services
- **Datadog account**: Valid Datadog API key and App key with dashboard creation permissions

### Assumptions

- Dashboard will be accessed primarily on desktop browsers during scheduled review meetings
- Typical suggestion volume is under 1000 pending items at any time
- Metrics publisher running every 60 seconds provides sufficient data freshness
- Single Datadog organization (no multi-tenant requirements for hackathon)
- Users have appropriate Datadog permissions to view dashboards and click action links

## Clarifications

### Session 2025-12-29

- Q: What Datadog integration approach for interactive approve/reject actions? → A: App Builder (recommended) or Iframe Widget (fallback). UI Extensions deprecated March 2025.
- Q: How do action buttons trigger the Approval API? → A: HTTP request actions configured in App Builder (not deep links). Supports Token Auth for API key authentication.
- Q: What is the architecture for dashboard data? → A: Metrics publisher pushes Firestore aggregates to Datadog Metrics API; App Builder fetches suggestions directly via HTTP for table display.

See `research.md` for detailed analysis of Datadog integration options.
