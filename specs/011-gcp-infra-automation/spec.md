# Feature Specification: Automated Infrastructure Provisioning

**Feature Branch**: `011-gcp-infra-automation`
**Created**: 2025-12-12
**Status**: Draft
**Input**: User description: "Automated GCP infrastructure provisioning for EvalForge stack - eliminate 3+ hour manual setup process, enable zero-manual-step deployment in <10 minutes"

## Clarifications

### Session 2025-12-12

- Q: Should we skip teardown (US3) to meet 2-hour hackathon target? → A: Yes, skip teardown entirely - defer to post-hackathon. Focus only on bootstrap + deploy (P0 items).

## Context

Infrastructure provisioning is a critical bottleneck for development velocity. During hackathon development of Issue #001, we lost 3+ hours to manual cloud setup: clicking through console to enable APIs, creating service accounts, configuring IAM policies, setting up secret management. This friction compounds for:

- **New team members joining the project**: 2-4 hour onboarding tax
- **Disaster recovery scenarios**: No documented recovery path
- **Multi-environment expansion**: Each environment requires full manual setup
- **Configuration drift**: Manual changes not tracked, environments diverge

**The Goal**: Eliminate infrastructure provisioning as a blocker. Any developer should be able to stand up the complete EvalForge stack (database, container runtime, secret management, job scheduling) in a new cloud project with zero manual steps and <10 minutes of wall-clock time.

## Personas

**Primary: Hackathon Developer (Mid-level ML Engineer)**
- **Pain**: Lost first 3 hours of hackathon to cloud console setup instead of coding
- **Needs**: One-command bootstrap so they can focus on feature development
- **Success**: Runs one script, gets coffee, returns to deployed service

**Secondary: New Team Member (Junior Engineer)**
- **Pain**: No clear setup instructions, cryptic errors when missing steps
- **Needs**: Reproducible setup path with clear error messages
- **Success**: Deploys full stack on day 1 without asking for help

**Tertiary: Platform Team Lead**
- **Pain**: Manual setup causes configuration drift, no audit trail
- **Needs**: Infrastructure-as-code for consistency and compliance
- **Success**: All environments provisioned identically, changes tracked in version control

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One-Command Infrastructure Bootstrap (Priority: P0 - Critical)

**As a** developer setting up EvalForge in a new cloud project
**I need** automated infrastructure provisioning
**So that** I don't waste hours clicking through cloud console and can deploy the stack in <10 minutes

**Why this priority**: This is the foundation - without automated bootstrap, every other workflow is blocked. A developer cannot deploy services, cannot test integrations, cannot onboard new team members efficiently. This represents 3+ hours of saved time per setup and eliminates the #1 friction point identified in Issue #001.

**Independent Test**: Can be fully tested by running the bootstrap command in a fresh cloud project with only billing enabled, and verifying all required APIs, service accounts, secrets infrastructure, and IAM policies are created without manual intervention. Delivers immediate value by enabling all subsequent deployment workflows.

**Acceptance Scenarios**:

1. **Given** a new cloud project with billing enabled and developer has authenticated CLI access, **When** running bootstrap command with project ID environment variable, **Then** all required cloud APIs are enabled without manual console interaction
2. **Given** bootstrap command executing, **When** service account creation runs, **Then** service account is created with minimal required permissions (no Owner/Editor roles)
3. **Given** bootstrap command executing, **When** secret management setup runs, **Then** secrets are created with placeholder values and clear instructions are displayed for adding actual credentials
4. **Given** bootstrap command has already run successfully once, **When** running bootstrap command again (idempotent test), **Then** command succeeds without errors, detects existing resources, and logs "already exists" messages for each resource
5. **Given** required environment variable is missing (e.g., project ID not set), **When** running bootstrap command, **Then** command fails immediately with actionable error message specifying which variable is missing and how to set it
6. **Given** all bootstrap prerequisites met, **When** bootstrap command completes, **Then** entire process finishes in <10 minutes
7. **Given** bootstrap command output, **When** developer reviews logs, **Then** all configuration is sourced from environment variables with no hardcoded project IDs visible in scripts

---

### User Story 2 - One-Command Service Deployment (Priority: P0 - Critical)

**As a** developer with bootstrapped infrastructure
**I need** automated deployment to container runtime
**So that** I can deploy the ingestion service and scheduler without understanding containerization or cloud deployment commands

**Why this priority**: After infrastructure exists, the next blocker is deploying actual application code. This eliminates the second major friction point: building container images, pushing to registries, configuring container services, and setting up job scheduling. Without this, developers still need deep cloud platform expertise.

**Independent Test**: Can be fully tested by running the deploy command after bootstrap completes, and verifying the service is accessible via HTTPS URL and scheduler triggers every 5 minutes. Delivers immediate value by making the application accessible to end users.

**Acceptance Scenarios**:

1. **Given** infrastructure has been bootstrapped successfully, **When** running deploy command, **Then** container image builds, deploys to container runtime, and configures job scheduler in single operation
2. **Given** deploy command has already run successfully once, **When** running deploy command again (idempotent test), **Then** command updates existing deployment without errors or downtime
3. **Given** all required environment variables configured, **When** running deploy command, **Then** deployment succeeds without any manual cloud commands
4. **Given** deployment completes successfully, **When** checking service accessibility, **Then** service is accessible via HTTPS URL and scheduler triggers every 5 minutes
5. **Given** deployment fails (e.g., container image build error), **When** command outputs error, **Then** clear error message with troubleshooting steps is displayed
6. **Given** deployment command completes, **When** checking execution time, **Then** entire process (build + deploy) finishes in <5 minutes

---

### User Story 3 - Easy Cleanup for Cost Management (Priority: P1 - DEFERRED)

> **DEFERRED**: Skipped for hackathon to meet 2-hour implementation target. Developers can delete resources manually via GCP console. Will be implemented post-hackathon.

**As a** developer working in test/staging environment
**I need** automated teardown of all resources
**So that** I can clean up test deployments to avoid unexpected cloud charges

**Acceptance Scenarios**: Deferred to post-hackathon.

---

### Edge Cases

- **What happens when cloud project doesn't have billing enabled?** Bootstrap command should detect this early and fail with actionable error message explaining billing requirement
- **What happens when developer lacks required cloud permissions?** Bootstrap/deploy commands should fail early with specific permission errors and list required roles
- **What happens when API enablement quota is exhausted?** Command should detect quota errors and provide clear guidance on requesting quota increases
- **What happens when service account creation conflicts with existing service account?** Idempotent behavior should detect existing service account and skip creation (not fail)
- **What happens when secrets already exist with different values?** Bootstrap should detect existing secrets and skip creation, not overwrite (preserve existing values)
- **What happens when container image build fails mid-deployment?** Deploy command should fail fast, output clear error with build logs, and leave existing deployment unchanged
- **What happens when developer runs teardown on production accidentally?** Confirmation prompt should clearly display environment/project being torn down, requiring explicit acknowledgment
- **What happens when network connectivity drops during bootstrap?** Command should fail gracefully with resume instructions (or auto-resume due to idempotent design)
- **What happens when developer cancels command mid-execution (Ctrl+C)?** Partially created resources should be safe to clean up by re-running the command (idempotent recovery)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide single command to enable all required cloud APIs without manual console interaction (database, container runtime, secret management, job scheduling, container build)
- **FR-002**: System MUST create service accounts with least-privilege IAM permissions automatically (no Owner/Editor roles)
- **FR-003**: System MUST create secret management infrastructure with placeholder values and display clear instructions for adding actual credentials
- **FR-004**: System MUST be idempotent - running bootstrap/deploy commands multiple times must succeed without errors or duplicate resources
- **FR-005**: System MUST externalize all configuration via environment variables (no hardcoded project IDs in scripts)
- **FR-006**: System MUST complete infrastructure bootstrap in <10 minutes given cloud project with billing enabled
- **FR-007**: System MUST fail immediately with actionable error messages when required environment variables are missing
- **FR-008**: System MUST detect existing resources on subsequent runs and log "already exists" messages instead of failing
- **FR-009**: System MUST provide single command to build container image, deploy to container runtime, and configure job scheduler in one operation
- **FR-010**: System MUST update existing deployments without downtime when deploy command runs on already-deployed service
- **FR-011**: System MUST deploy services to container runtime with HTTPS accessibility and job scheduler triggering every 5 minutes
- **FR-012**: System MUST output clear error messages with troubleshooting steps when deployment failures occur
- **FR-013**: System MUST complete deployment (build + deploy) in <5 minutes
- **FR-014**: ~~DEFERRED~~ Teardown command - deferred to post-hackathon
- **FR-015**: System MUST emit structured logs with timestamps and operation status for debugging and observability (per constitution: Observability-First principle)
- **FR-019**: System MUST prevent secrets from being logged, echoed, or committed to version control
- **FR-020**: System MUST enforce that container services are not publicly accessible (authenticated access only)
- **FR-021**: System MUST apply `managed-by=evalforge` label to all GCP resources that support labels (Cloud Run, Cloud Scheduler, Secret Manager secrets) to enable filtering automation-created resources from manually-created ones

### Key Entities

- **Bootstrap Script**: Orchestrates cloud API enablement, service account creation, IAM policy configuration, and secret management setup. Takes project ID via environment variable, validates prerequisites, and executes idempotent provisioning steps.
- **Deploy Script**: Orchestrates container image building, container runtime deployment, and job scheduler configuration. Takes configuration from environment variables, builds from source code, and deploys with zero-downtime updates.
- **Teardown Script**: ~~DEFERRED~~ - Deferred to post-hackathon. Manual GCP console deletion for now.
- **Service Account**: Cloud identity for running deployed services. Created with minimal required permissions (no Owner/Editor), used by container runtime for accessing database and secrets.
- **Secret Store**: Managed secret storage for credentials (API keys, database connection strings). Created during bootstrap with placeholder values, populated manually by developer, accessed by deployed services.
- **Configuration**: Environment variables defining project ID, region, service names, and deployment parameters. Externalized to avoid hardcoding, documented in setup instructions, validated before execution.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Developer can complete infrastructure bootstrap from zero to fully provisioned in <10 minutes with single command (vs 3+ hours manual setup)
- **SC-002**: Developer executes exactly 1 manual step (setting project ID environment variable) vs ~20 manual console clicks for setup
- **SC-003**: Bootstrap/deploy commands succeed on first attempt with 100% success rate when prerequisites are met (clear errors guide user to fix missing prerequisites)
- **SC-004**: Developer can deploy application code to production-ready container runtime in <5 minutes with single command (vs 30+ minutes manual deployment)
- **SC-005**: Developer requires zero knowledge of containerization or cloud deployment commands to successfully deploy services
- **SC-006**: ~~DEFERRED~~ Teardown success criteria - deferred to post-hackathon
- **SC-007**: Scripts emit structured logs that enable debugging failures within 5 minutes (observability)
- **SC-008**: Running bootstrap or deploy commands multiple times (idempotent test) succeeds 100% of the time without creating duplicate resources
- **SC-009**: New team members can deploy full stack on day 1 without assistance from existing team (self-service onboarding)
- **SC-010**: All environments (test/staging/production) are provisioned identically via version-controlled automation (zero configuration drift)

## Assumptions

- **Assumption 1**: Developers have cloud project with billing already enabled (billing enablement cannot be automated and requires admin access)
- **Assumption 2**: Developers have cloud CLI tool installed and authenticated on their local machine before running scripts
- **Assumption 3**: Developers have container runtime (Docker) installed locally for building and testing container images
- **Assumption 4**: Cloud project has sufficient API quotas for enabling required services (standard quotas are sufficient for hackathon/small team usage)
- **Assumption 5**: Developers are working in single cloud environment (production) for hackathon - multi-environment management deferred to post-hackathon
- **Assumption 6**: Shell scripts are acceptable automation method for hackathon speed - infrastructure-as-code templates (Terraform/Pulumi) deferred to post-hackathon
- **Assumption 7**: Secret rotation policies are manual for hackathon - automated rotation deferred to post-hackathon
- **Assumption 8**: Standard deployment strategy is acceptable for hackathon - blue/green or canary deployments deferred to post-hackathon
- **Assumption 9**: Database (Firestore) requires manual deletion due to data protection safeguards - this is acceptable for cost management
- **Assumption 10**: Container services use OIDC authentication (not public access) as security baseline

## Out of Scope

The following capabilities are explicitly deferred to future iterations:

**Deferred to Post-Hackathon:**
- **Automated teardown script (US3)** - Manual GCP console deletion for hackathon
- Multi-environment management (dev/staging/prod environments with separate configurations)
- Infrastructure-as-code templates using Terraform or Pulumi
- Automated secret rotation policies and lifecycle management
- Blue/green or canary deployment strategies
- Infrastructure testing frameworks (terratest, etc.)
- Cost budgets and quota alerts
- Custom VPC networking or firewall rules
- Monitoring/alerting infrastructure (dashboards, alerts, SLOs)
- Automated backup/restore procedures for database
- CI/CD pipeline integration (GitHub Actions, GitLab CI, etc.)

**Explicitly NOT Doing:**
- Kubernetes or GKE deployment (container runtime is sufficient for hackathon scale)
- Multi-cloud support (single cloud provider only)
- On-premises deployment options
- GUI or web-based infrastructure management interface
- Automated billing enablement (requires admin privileges outside developer scope)
- Custom domain configuration and SSL certificate management
- Database schema migration automation (handled separately in application code)

## Constraints

### Platform Constraints
- Must run on cloud platform infrastructure (cannot be self-hosted)
- Must use managed container runtime for stateless execution
- Must use managed database for data persistence
- Must use managed secret storage for credential management

### Prerequisite Constraints
- Requires cloud project with billing enabled (cannot automate billing setup)
- Requires cloud CLI tool installed and authenticated on developer machine
- Requires container runtime (Docker) installed locally for image testing
- Requires developer to have appropriate cloud IAM permissions (project editor or equivalent)

### Security Constraints
- Service accounts must use least-privilege IAM (no Owner/Editor roles)
- Container services must not be publicly accessible (authenticated access only)
- Secrets must never be logged, echoed, or committed to version control
- All cloud resources must be created in single project for isolation

### Operational Constraints
- Scripts must complete in <10 minutes on standard developer machine
- Scripts must be idempotent (safe to run multiple times without side effects)
- Scripts must provide clear, actionable error messages (no cryptic cloud errors)
- Scripts must fail fast when prerequisites are not met (detect early, fail early)
- Teardown must require explicit confirmation to prevent accidental deletions
