# Feature Specification: Approval Workflow API

**Feature Branch**: `008-approval-workflow-api`
**Created**: 2025-12-29
**Status**: Draft
**Input**: User description: "Human-in-the-loop approval gate for GenAI suggestions. Platform leads can approve or reject suggestions with one click. Includes webhook notifications, atomic status transitions, and multi-format exports."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One-Click Suggestion Approval (Priority: P1)

As a platform lead reviewing the suggestion queue, I want to approve a suggestion with a single action so that validated improvements proceed to production without unnecessary friction.

**Why this priority**: This is the core value proposition - reducing approval friction from manual processes to one-click actions. Without this, the entire feedback loop breaks.

**Independent Test**: Can be fully tested by approving a pending suggestion via the API and verifying the status transition. Delivers immediate value by enabling the approval workflow.

**Acceptance Scenarios**:

1. **Given** a suggestion exists with status "pending", **When** I call the approve endpoint with valid credentials, **Then** the suggestion status transitions to "approved" atomically and I receive confirmation within 3 seconds
2. **Given** a suggestion exists with status "pending", **When** I approve it, **Then** a webhook notification is sent to configured channels within 5 seconds
3. **Given** a suggestion has already been approved, **When** I try to approve it again, **Then** the system returns an appropriate error indicating the suggestion is not in a valid state for approval

---

### User Story 2 - Suggestion Rejection with Reasoning (Priority: P1)

As a platform lead, I want to reject suggestions that don't meet quality standards with a recorded reason so that the team understands why suggestions were not accepted and can improve future generation.

**Why this priority**: Equal priority with approval - both are core workflow actions. Rejection with reasoning enables continuous improvement of the suggestion generation system.

**Independent Test**: Can be fully tested by rejecting a pending suggestion with a reason and verifying the status and audit trail. Delivers value by filtering out false positives.

**Acceptance Scenarios**:

1. **Given** a suggestion exists with status "pending", **When** I call the reject endpoint with a reason, **Then** the suggestion status transitions to "rejected" atomically with the reason recorded
2. **Given** a suggestion is rejected, **When** I query the suggestion details, **Then** I can see the rejection reason and timestamp in the audit trail
3. **Given** a suggestion has already been rejected, **When** I try to reject it again, **Then** the system returns an appropriate error

---

### User Story 3 - Export Approved Suggestions (Priority: P2)

As an ML engineer, I want to export approved suggestions in CI-ready formats so that I can integrate them into my test pipeline without manual conversion.

**Why this priority**: Export enables the downstream integration that makes approvals actionable. Important but secondary to the core approve/reject workflow.

**Independent Test**: Can be fully tested by exporting an approved suggestion in each format and validating the output structure. Delivers value by enabling CI integration.

**Acceptance Scenarios**:

1. **Given** an approved eval suggestion exists, **When** I request export in DeepEval JSON format, **Then** I receive a valid, parseable JSON file within 3 seconds
2. **Given** an approved eval suggestion exists, **When** I request export in Pytest format, **Then** I receive syntactically valid Python test code
3. **Given** an approved guardrail suggestion exists, **When** I request export in YAML format, **Then** I receive valid YAML configuration
4. **Given** a suggestion is still pending, **When** I try to export it, **Then** the system returns an error indicating only approved suggestions can be exported

---

### User Story 4 - Browse Suggestion Queue (Priority: P2)

As a platform lead, I want to browse the queue of pending suggestions with filtering options so that I can efficiently review and prioritize my approval work.

**Why this priority**: Browsing enables efficient queue management. Important for usability but not blocking the core approve/reject flow.

**Independent Test**: Can be fully tested by querying suggestions with various filters and verifying correct results. Delivers value by enabling queue navigation.

**Acceptance Scenarios**:

1. **Given** multiple suggestions exist with different statuses, **When** I query with status filter "pending", **Then** I receive only pending suggestions sorted by creation time
2. **Given** multiple suggestions exist with different types, **When** I query with type filter "eval", **Then** I receive only eval-type suggestions
3. **Given** more than 50 suggestions exist, **When** I query with pagination parameters, **Then** I receive paginated results with a cursor for the next page and correct limit

---

### User Story 5 - Webhook Notification Configuration (Priority: P3)

As a platform lead, I want approval and rejection events to trigger webhook notifications so that relevant team members are informed immediately without checking the dashboard.

**Why this priority**: Notifications enhance awareness but approvals work without them. Nice-to-have for team coordination.

**Independent Test**: Can be fully tested by approving a suggestion and verifying the webhook payload is received at the configured endpoint.

**Acceptance Scenarios**:

1. **Given** a Slack webhook is configured, **When** a suggestion is approved, **Then** a formatted notification appears in the Slack channel within 5 seconds
2. **Given** a webhook endpoint is unavailable, **When** approval triggers notification, **Then** the approval still succeeds and the webhook failure is logged for retry

---

### Edge Cases

- **Deleted suggestion**: When approving a suggestion that was deleted between query and approval, the system MUST return 404 Not Found with message "Suggestion not found"
- **Concurrent approval**: When multiple users attempt to approve the same suggestion simultaneously, exactly one succeeds (atomic transaction) and others receive 409 Conflict with message "Suggestion is not in pending state"
- **Webhook failure**: When the webhook endpoint returns an error or times out during approval, the approval MUST still succeed; webhook failure is logged for manual retry but does not block the user
- **Invalid export format**: When requesting an unsupported export format, the system MUST return 422 Unprocessable Entity with message listing valid formats (deepeval, pytest, yaml)
- **Missing content fields**: When exporting a suggestion with missing required content fields, the system MUST return 422 Unprocessable Entity with message specifying which fields are missing

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow authenticated users to approve pending suggestions with a single API call
- **FR-002**: System MUST allow authenticated users to reject pending suggestions with a required reason field
- **FR-003**: System MUST transition suggestion status atomically (no partial updates visible)
- **FR-004**: System MUST maintain complete audit trail (version_history) of all status changes including who, when, and notes
- **FR-005**: System MUST send webhook notifications on approval within 5 seconds
- **FR-006**: System MUST support exporting approved suggestions in DeepEval JSON format
- **FR-007**: System MUST support exporting approved suggestions in Pytest Python format
- **FR-008**: System MUST support exporting approved suggestions in YAML format
- **FR-009**: System MUST validate exported files (JSON parseable, Python syntax valid, YAML loadable)
- **FR-010**: System MUST support listing suggestions with filters for status and type
- **FR-011**: System MUST support cursor-based pagination for suggestion lists (limit/cursor)
- **FR-012**: System MUST authenticate requests using API key in header
- **FR-013**: System MUST reject requests with invalid or missing API keys with appropriate error
- **FR-014**: System MUST provide health check endpoint for monitoring
- **FR-015**: System MUST complete end-to-end workflow (approve to export) within 30 seconds

### Key Entities

- **Suggestion**: The core entity representing a generated improvement (eval test, guardrail rule, or runbook entry). Has status (pending/approved/rejected), type, creation timestamp, and content.
- **Approval Metadata**: Records who approved/rejected, when, and any notes provided. Attached to suggestion on status change.
- **Version History** (`version_history`): Ordered list of status transitions providing the audit trail. Each entry includes status, timestamp, and actor.
- **Export Package**: Generated output file in requested format. Created on-demand, not pre-stored.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Platform leads can complete approval or rejection in under 3 seconds from clicking action to receiving confirmation
- **SC-002**: Full workflow from viewing suggestion to exporting approved artifact completes in under 30 seconds
- **SC-003**: Webhook notifications arrive in Slack within 5 seconds of approval action
- **SC-004**: Exported files are valid and usable 100% of the time (pass format-specific validation)
- **SC-005**: System handles at least 100 concurrent approval requests without degradation
- **SC-006**: 95% of API requests complete in under 1 second
- **SC-007**: Zero partial status updates visible to users (atomic transitions)

## Assumptions

- Single approver workflow is sufficient (no multi-reviewer approval chains needed)
- API key authentication is acceptable security for the hackathon phase
- Suggestions already exist in the system (created by upstream generation services)
- Slack is the primary webhook destination (other destinations may be added later)
- Export formats are generated on-demand, not pre-computed and stored
- The system operates in a single project/tenant context

## Out of Scope

- OAuth/OIDC authentication (API key sufficient for hackathon)
- Multi-reviewer approval workflows
- Automatic rollback of approved suggestions
- Bulk approval/rejection operations
- Custom webhook payload templates
- Export format customization beyond the three standard formats
