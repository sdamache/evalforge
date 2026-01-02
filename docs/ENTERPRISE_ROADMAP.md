# Enterprise Roadmap: Platform Engineering Issues

This document contains GitHub issue templates derived from out-of-scope and deferred items across all feature specifications. These improvements will make EvalForge enterprise-grade and help develop platform engineering proficiency.

---

## Issue #1: Infrastructure as Code with Terraform

**Labels**: `infrastructure`, `priority:high`, `platform-engineering`

### Description

Migrate from shell-based GCP automation scripts to Terraform for infrastructure-as-code (IaC). This enables version-controlled, reviewable, and reproducible infrastructure deployments.

### Background

From `specs/011-gcp-infra-automation`:
> "Terraform migration - Shell scripts sufficient for hackathon - Future"

### Acceptance Criteria

- [ ] Terraform modules for all GCP resources:
  - [ ] Cloud Run services (ingestion, api, runbook-generator, guardrail-generator)
  - [ ] Firestore database
  - [ ] Cloud Scheduler jobs
  - [ ] Secret Manager secrets
  - [ ] Service accounts with IAM bindings
- [ ] State management with GCS backend
- [ ] Variable files for environment-specific configuration
- [ ] `terraform plan` output in PR comments
- [ ] Documentation with architecture diagrams
- [ ] Terratest integration tests

### Learning Objectives (Platform Engineering)

- Terraform HCL syntax and module design
- State management strategies (remote state, locking)
- GCP provider configuration
- Infrastructure testing with Terratest
- GitOps workflows for infrastructure

### Resources

- [Terraform GCP Provider](https://registry.terraform.io/providers/hashicorp/google/latest)
- [Terratest](https://terratest.gruntwork.io/)
- [GCP Best Practices for Terraform](https://cloud.google.com/docs/terraform/best-practices-for-terraform)

---

## Issue #2: CI/CD Pipeline with GitHub Actions

**Labels**: `infrastructure`, `automation`, `priority:high`, `platform-engineering`

### Description

Implement automated CI/CD pipelines using GitHub Actions for testing, building, and deploying EvalForge services.

### Background

From `specs/011-gcp-infra-automation`:
> "CI/CD pipeline - Manual deployment acceptable for hackathon - Future"

### Acceptance Criteria

- [ ] CI Pipeline (on every PR):
  - [ ] Lint and type checking
  - [ ] Unit tests with coverage reporting
  - [ ] Contract tests
  - [ ] Security scanning (Snyk/Dependabot)
  - [ ] Docker image build validation
- [ ] CD Pipeline (on merge to main):
  - [ ] Build and push Docker images to Artifact Registry
  - [ ] Deploy to staging environment
  - [ ] Run integration tests against staging
  - [ ] Manual approval gate for production
  - [ ] Deploy to production
  - [ ] Smoke tests post-deployment
- [ ] Infrastructure Pipeline:
  - [ ] `terraform plan` on PR
  - [ ] `terraform apply` on merge (with approval)
- [ ] Deployment notifications to Slack

### Learning Objectives (Platform Engineering)

- GitHub Actions workflow syntax
- Multi-stage pipelines with dependencies
- Secrets management in CI/CD
- Container registry integration
- Deployment gates and approvals

### Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Workload Identity Federation for GCP](https://cloud.google.com/iam/docs/workload-identity-federation)
- [GitHub Actions for GCP](https://github.com/google-github-actions)

---

## Issue #3: Multi-Environment Management (Dev/Staging/Prod)

**Labels**: `infrastructure`, `priority:high`, `platform-engineering`

### Description

Implement proper environment separation with dev, staging, and production environments, each with isolated resources and configurations.

### Background

From `specs/011-gcp-infra-automation`:
> "Multi-environment support - Single project for hackathon - Future"

### Acceptance Criteria

- [ ] Environment-specific GCP projects or resource prefixes:
  - [ ] `evalforge-dev` - Development/testing
  - [ ] `evalforge-staging` - Pre-production validation
  - [ ] `evalforge-prod` - Production
- [ ] Environment-specific configurations:
  - [ ] Firestore collections with environment prefixes
  - [ ] Separate Secret Manager secrets per environment
  - [ ] Environment-specific service accounts
- [ ] Promotion workflow:
  - [ ] Deploy to dev automatically on PR merge
  - [ ] Promote to staging with manual trigger
  - [ ] Promote to prod with approval gates
- [ ] Environment parity validation scripts
- [ ] Cost allocation by environment (resource labels)

### Learning Objectives (Platform Engineering)

- GCP project organization and folder structure
- Environment isolation strategies
- Configuration management across environments
- Promotion pipelines and gates
- Cost management and allocation

### Resources

- [GCP Resource Hierarchy](https://cloud.google.com/resource-manager/docs/cloud-platform-resource-hierarchy)
- [12-Factor App Config](https://12factor.net/config)

---

## Issue #4: OAuth/OIDC Authentication for APIs

**Labels**: `security`, `priority:high`, `platform-engineering`

### Description

Replace API key authentication with OAuth 2.0/OIDC for production-grade security, supporting both machine-to-machine and user authentication.

### Background

From `specs/008-approval-workflow-api`:
> "OAuth/OIDC authentication - API key auth sufficient for demo; upgrade path clear"

### Acceptance Criteria

- [ ] Identity Provider integration:
  - [ ] Google Cloud Identity Platform setup
  - [ ] Service account authentication for M2M
  - [ ] User authentication with JWT tokens
- [ ] API Gateway integration:
  - [ ] Cloud Endpoints or API Gateway configuration
  - [ ] JWT validation at gateway level
  - [ ] Rate limiting per client
- [ ] RBAC implementation:
  - [ ] Define roles: `viewer`, `approver`, `admin`
  - [ ] Role-based endpoint access control
  - [ ] Audit logging of authorization decisions
- [ ] Token management:
  - [ ] Token refresh flow
  - [ ] Token revocation capability
- [ ] Backward compatibility with API keys during migration

### Learning Objectives (Platform Engineering)

- OAuth 2.0 and OIDC protocols
- JWT token validation and claims
- Identity Platform configuration
- API Gateway security policies
- Zero-trust security principles

### Resources

- [Google Cloud Identity Platform](https://cloud.google.com/identity-platform)
- [Cloud Endpoints Authentication](https://cloud.google.com/endpoints/docs/openapi/authenticating-users)
- [OWASP API Security](https://owasp.org/www-project-api-security/)

---

## Issue #5: Observability Stack (Monitoring, Alerts, SLOs)

**Labels**: `observability`, `priority:high`, `platform-engineering`

### Description

Implement comprehensive observability with monitoring dashboards, alerting, and SLO-based reliability management.

### Background

From `specs/011-gcp-infra-automation`:
> "Monitoring/alerting infrastructure (dashboards, alerts, SLOs) - deferred"

### Acceptance Criteria

- [ ] Metrics Collection:
  - [ ] Application metrics (request latency, error rates, throughput)
  - [ ] Business metrics (suggestions processed, approvals, exports)
  - [ ] Infrastructure metrics (CPU, memory, request count)
- [ ] Dashboards:
  - [ ] Service health overview dashboard
  - [ ] Per-service detailed dashboards
  - [ ] Business metrics dashboard
  - [ ] On-call dashboard with runbook links
- [ ] Alerting:
  - [ ] Error rate alerts (>1% errors)
  - [ ] Latency alerts (p99 > 5s)
  - [ ] Availability alerts (<99.5% uptime)
  - [ ] Business alerts (queue backlog, stuck suggestions)
  - [ ] PagerDuty/Slack integration
- [ ] SLOs:
  - [ ] Define SLIs for each service
  - [ ] Set SLO targets (e.g., 99.5% availability)
  - [ ] Error budget tracking
  - [ ] SLO burn rate alerts

### Learning Objectives (Platform Engineering)

- SRE principles (SLIs, SLOs, error budgets)
- Metrics design and cardinality management
- Alert design to reduce noise
- Incident response integration
- Cloud Monitoring and Datadog integration

### Resources

- [Google SRE Book](https://sre.google/sre-book/table-of-contents/)
- [Cloud Monitoring SLOs](https://cloud.google.com/monitoring/slos)
- [Datadog SLOs](https://docs.datadoghq.com/monitors/service_level_objectives/)

---

## Issue #6: Deployment Strategies (Blue/Green, Canary)

**Labels**: `infrastructure`, `deployment`, `priority:medium`, `platform-engineering`

### Description

Implement advanced deployment strategies to reduce deployment risk and enable rapid rollback.

### Background

From `specs/011-gcp-infra-automation`:
> "Blue/green or canary deployment strategies - deferred"

### Acceptance Criteria

- [ ] Blue/Green Deployments:
  - [ ] Traffic splitting configuration in Cloud Run
  - [ ] Health check validation before traffic switch
  - [ ] One-command rollback capability
  - [ ] Deployment history tracking
- [ ] Canary Deployments:
  - [ ] Gradual traffic shifting (1% → 10% → 50% → 100%)
  - [ ] Automated rollback on error rate spike
  - [ ] Canary metrics comparison
- [ ] Feature Flags:
  - [ ] Feature flag service integration (LaunchDarkly or Firebase Remote Config)
  - [ ] Flag-based feature rollout
  - [ ] Emergency kill switches
- [ ] Deployment validation:
  - [ ] Synthetic monitoring during rollout
  - [ ] Automatic rollback triggers

### Learning Objectives (Platform Engineering)

- Traffic management and splitting
- Progressive delivery patterns
- Feature flag architecture
- Deployment risk mitigation
- Rollback automation

### Resources

- [Cloud Run Traffic Management](https://cloud.google.com/run/docs/managing/revisions)
- [Progressive Delivery](https://www.split.io/glossary/progressive-delivery/)

---

## Issue #7: Disaster Recovery and Backup Automation

**Labels**: `infrastructure`, `reliability`, `priority:medium`, `platform-engineering`

### Description

Implement automated backup, restore, and disaster recovery procedures for data and infrastructure.

### Background

From `specs/011-gcp-infra-automation`:
> "Automated backup/restore procedures for database - deferred"
> "Automated teardown script (US3) - deferred"

### Acceptance Criteria

- [ ] Firestore Backups:
  - [ ] Scheduled daily backups to GCS
  - [ ] Point-in-time recovery capability
  - [ ] Cross-region backup replication
  - [ ] Backup retention policy (30 days)
- [ ] Restore Procedures:
  - [ ] Documented restore runbook
  - [ ] Automated restore script
  - [ ] Restore testing (monthly drill)
- [ ] Teardown Automation:
  - [ ] Resource inventory script
  - [ ] Safe teardown with confirmation prompts
  - [ ] Cost report before teardown
  - [ ] Selective teardown by environment
- [ ] Disaster Recovery:
  - [ ] RTO/RPO definitions
  - [ ] DR runbook with step-by-step procedures
  - [ ] Annual DR drill schedule
  - [ ] Multi-region failover (stretch goal)

### Learning Objectives (Platform Engineering)

- Backup strategies and retention policies
- RTO/RPO planning
- Disaster recovery testing
- Data lifecycle management
- GCS lifecycle policies

### Resources

- [Firestore Export/Import](https://cloud.google.com/firestore/docs/manage-data/export-import)
- [GCS Lifecycle Management](https://cloud.google.com/storage/docs/lifecycle)
- [DR Planning Guide](https://cloud.google.com/architecture/dr-scenarios-planning-guide)

---

## Issue #8: Secret Management and Rotation

**Labels**: `security`, `priority:medium`, `platform-engineering`

### Description

Implement automated secret rotation and enhanced secret lifecycle management.

### Background

From `specs/011-gcp-infra-automation`:
> "Automated secret rotation policies and lifecycle management - deferred"

### Acceptance Criteria

- [ ] Secret Rotation:
  - [ ] Automatic rotation schedule (90 days)
  - [ ] Zero-downtime rotation for API keys
  - [ ] Rotation notification alerts
  - [ ] Rotation audit logging
- [ ] Secret Versioning:
  - [ ] Version tracking in Secret Manager
  - [ ] Previous version access for rollback
  - [ ] Automatic old version destruction
- [ ] Secret Access:
  - [ ] Least-privilege access policies
  - [ ] Just-in-time secret access (stretch goal)
  - [ ] Access audit trail
- [ ] Secret Scanning:
  - [ ] Pre-commit secret detection
  - [ ] Repository secret scanning
  - [ ] Alert on exposed secrets

### Learning Objectives (Platform Engineering)

- Secret lifecycle management
- Zero-downtime secret rotation patterns
- IAM least-privilege design
- Secret scanning and prevention
- Compliance and audit requirements

### Resources

- [Secret Manager Best Practices](https://cloud.google.com/secret-manager/docs/best-practices)
- [Secret Rotation Patterns](https://cloud.google.com/architecture/identity/key-rotation)
- [gitleaks](https://github.com/gitleaks/gitleaks)

---

## Issue #9: PagerDuty Integration for Incident Management

**Labels**: `integration`, `observability`, `priority:medium`, `platform-engineering`

### Description

Integrate with PagerDuty for automated incident creation, escalation, and on-call management.

### Background

From `specs/006-runbook-generation`:
> "Integration with PagerDuty or incident management tools - out of scope"

### Acceptance Criteria

- [ ] PagerDuty Integration:
  - [ ] Service configuration in PagerDuty
  - [ ] Alert routing rules by severity
  - [ ] Escalation policies
  - [ ] On-call schedules
- [ ] Incident Automation:
  - [ ] Auto-create incidents from critical alerts
  - [ ] Attach runbooks to incidents
  - [ ] Incident timeline enrichment
  - [ ] Auto-resolve on recovery
- [ ] Runbook Linking:
  - [ ] Runbook URLs in incident details
  - [ ] One-click runbook access from PagerDuty
  - [ ] Runbook effectiveness feedback loop
- [ ] Metrics:
  - [ ] MTTA (Mean Time to Acknowledge)
  - [ ] MTTR (Mean Time to Resolve)
  - [ ] Incident frequency by service

### Learning Objectives (Platform Engineering)

- Incident management workflows
- On-call best practices
- Alert fatigue reduction
- MTTA/MTTR optimization
- Runbook-driven incident response

### Resources

- [PagerDuty Integration Guide](https://developer.pagerduty.com/)
- [PagerDuty + GCP Integration](https://www.pagerduty.com/integrations/google-cloud-platform/)
- [Incident Response Best Practices](https://response.pagerduty.com/)

---

## Issue #10: Interactive Slack Approvals

**Labels**: `integration`, `ux`, `priority:medium`

### Description

Implement interactive Slack approvals allowing reviewers to approve/reject suggestions directly from Slack messages.

### Background

From `specs/008-approval-workflow-api`:
> "Interactive Slack approvals (approve/reject via Slack buttons) - current implementation is notification-only; interactive approvals require full Slack App with OAuth and Events API"

### Acceptance Criteria

- [ ] Slack App Setup:
  - [ ] Slack App manifest with required scopes
  - [ ] OAuth 2.0 flow for workspace installation
  - [ ] Events API subscription
  - [ ] Interactive Components configuration
- [ ] Interactive Messages:
  - [ ] Approve/Reject buttons in notification
  - [ ] Reviewer dropdown (optional)
  - [ ] Comment modal for rejection reason
  - [ ] Confirmation message after action
- [ ] Backend Integration:
  - [ ] Slack action webhook handler
  - [ ] User identity verification
  - [ ] Action audit logging
  - [ ] Rate limiting for actions
- [ ] UX Enhancements:
  - [ ] Message update after action (show result)
  - [ ] Thread replies for discussion
  - [ ] Bulk approval from Slack

### Learning Objectives (Platform Engineering)

- Slack App development
- OAuth 2.0 implementation
- Webhook security and verification
- Event-driven architecture
- ChatOps patterns

### Resources

- [Slack Block Kit](https://api.slack.com/block-kit)
- [Slack Interactivity](https://api.slack.com/interactivity)
- [Slack Events API](https://api.slack.com/events-api)

---

## Issue #11: Guardrail Conflict Detection

**Labels**: `feature`, `ai`, `priority:medium`

### Description

Implement automatic detection of conflicts between multiple guardrail rules to prevent contradictory or overlapping rules.

### Background

From `specs/005-guardrail-generation`:
> "Guardrail conflict detection across multiple rules - out of scope"

### Acceptance Criteria

- [ ] Conflict Detection:
  - [ ] Detect overlapping regex patterns
  - [ ] Detect contradictory rules (allow vs block same content)
  - [ ] Detect redundant rules (subset of another rule)
  - [ ] Severity-based conflict resolution suggestions
- [ ] Conflict Visualization:
  - [ ] Conflict report in approval workflow
  - [ ] Visual diff of conflicting rules
  - [ ] Suggested resolution actions
- [ ] Prevention:
  - [ ] Pre-generation conflict check
  - [ ] Warning before approving conflicting rules
  - [ ] Automatic deduplication suggestions

### Learning Objectives

- Rule engine design
- Conflict resolution algorithms
- AI-assisted deduplication
- Policy management patterns

---

## Issue #12: Cross-Artifact Linking (Eval ↔ Guardrail ↔ Runbook)

**Labels**: `feature`, `ux`, `priority:low`

### Description

Implement cross-linking between related artifacts (eval tests, guardrails, runbooks) generated from the same failure pattern.

### Background

From `specs/006-runbook-generation`:
> "Cross-linking between runbook and generated eval test/guardrail (deferred to future)"

### Acceptance Criteria

- [ ] Data Model:
  - [ ] `related_artifacts` field on suggestions
  - [ ] Bidirectional links between artifacts
  - [ ] Link type (same_failure, similar_pattern, manual)
- [ ] Linking Logic:
  - [ ] Auto-link artifacts from same failure pattern
  - [ ] Suggest links based on semantic similarity
  - [ ] Manual linking via API
- [ ] API Enhancements:
  - [ ] Include related artifacts in suggestion response
  - [ ] Filter suggestions by related artifacts
  - [ ] Bulk link/unlink operations
- [ ] Export Enhancements:
  - [ ] Include related artifacts in exports
  - [ ] Cross-reference in generated runbooks

---

## Issue #13: Runbook Versioning System

**Labels**: `feature`, `priority:low`

### Description

Implement version control for runbooks to track changes, enable rollback, and maintain change history.

### Background

From `specs/006-runbook-generation`:
> "Runbook versioning system (store in Firestore only for hackathon)"

### Acceptance Criteria

- [ ] Versioning:
  - [ ] Version number auto-increment on edit
  - [ ] Full content diff between versions
  - [ ] Version metadata (author, timestamp, change summary)
- [ ] Rollback:
  - [ ] Restore previous version
  - [ ] Rollback audit logging
- [ ] Git-like Features:
  - [ ] Branch runbooks for experimentation (stretch)
  - [ ] Merge runbook branches (stretch)

---

## Issue #14: Cost Management and Budgets

**Labels**: `infrastructure`, `finops`, `priority:medium`, `platform-engineering`

### Description

Implement cost tracking, budgets, and alerts for GCP resource usage.

### Background

From `specs/011-gcp-infra-automation`:
> "Cost budgets and quota alerts - deferred"

### Acceptance Criteria

- [ ] Cost Visibility:
  - [ ] Resource labeling for cost allocation
  - [ ] Cost dashboard by service/environment
  - [ ] Daily/weekly cost reports
- [ ] Budgets:
  - [ ] Monthly budget alerts (50%, 90%, 100%)
  - [ ] Per-environment budgets
  - [ ] Anomaly detection alerts
- [ ] Optimization:
  - [ ] Idle resource identification
  - [ ] Right-sizing recommendations
  - [ ] Committed use discount analysis

### Learning Objectives (Platform Engineering)

- FinOps principles
- GCP Billing and Cost Management
- Resource tagging strategies
- Cost optimization techniques

### Resources

- [GCP Cost Management](https://cloud.google.com/cost-management)
- [FinOps Foundation](https://www.finops.org/)

---

## Issue #15: Infrastructure Testing Framework

**Labels**: `testing`, `infrastructure`, `priority:low`, `platform-engineering`

### Description

Implement infrastructure testing to validate Terraform configurations before deployment.

### Background

From `specs/011-gcp-infra-automation`:
> "Infrastructure testing frameworks (terratest, etc.) - deferred"

### Acceptance Criteria

- [ ] Static Analysis:
  - [ ] `terraform validate` in CI
  - [ ] `tflint` for best practices
  - [ ] `checkov` for security scanning
- [ ] Unit Tests:
  - [ ] Terratest for module testing
  - [ ] Mock GCP API responses
- [ ] Integration Tests:
  - [ ] Ephemeral environment creation
  - [ ] Resource validation
  - [ ] Cleanup after tests

### Learning Objectives (Platform Engineering)

- Infrastructure testing patterns
- Policy-as-code with OPA
- Ephemeral environment management
- Terratest and Go testing

### Resources

- [Terratest](https://terratest.gruntwork.io/)
- [Checkov](https://www.checkov.io/)
- [OPA/Conftest](https://www.conftest.dev/)

---

## Priority Summary

| Priority | Issues | Focus Area |
|----------|--------|------------|
| **High** | #1, #2, #3, #4, #5 | Core infrastructure & security |
| **Medium** | #6, #7, #8, #9, #10, #14 | Reliability & operations |
| **Low** | #11, #12, #13, #15 | Advanced features |

## Recommended Learning Path

1. **Foundation** (Issues #1-3): IaC, CI/CD, environments
2. **Security** (Issues #4, #8): Authentication, secrets
3. **Reliability** (Issues #5, #6, #7): Observability, deployments, DR
4. **Operations** (Issues #9, #10, #14): Incident management, cost
5. **Advanced** (Issues #11-13, #15): Features and testing

---

*Generated from EvalForge specification out-of-scope and deferred items*
