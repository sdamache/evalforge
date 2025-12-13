# Tasks: GCP Infrastructure Automation

**Input**: Design documents from `/specs/011-gcp-infra-automation/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, quickstart.md

**Tests**: Manual integration tests only (per hackathon scope - no automated test suite)

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

**Target Time**: ~2 hours total implementation

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

## Path Conventions

- **Scripts**: `scripts/` at repository root
- **Container**: `Dockerfile`, `.dockerignore`, `.gcloudignore` at repository root
- **Existing**: `src/` (Python service code), `scripts/bootstrap_firestore.py` (Firestore setup)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project structure validation and container configuration
**Estimated Time**: ~10 min

- [x] T001 Verify scripts/ directory exists and contains bootstrap_firestore.py in scripts/
- [x] T002 [P] Create .dockerignore to exclude .git, tests/, venv/, __pycache__/, *.pyc, .env* at repository root
- [x] T003 [P] Create .gcloudignore to exclude .git, tests/, venv/, __pycache__/, *.pyc, .env*, docs/ at repository root

**Checkpoint**: Project structure ready for script and container development

---

## Phase 2: Foundational (Container Image)

**Purpose**: Dockerfile that MUST exist before deployment script can work
**Estimated Time**: ~15 min

**⚠️ CRITICAL**: Deploy script (US2) cannot work without this Dockerfile

- [x] T004 Create Dockerfile with python:3.11-slim base image at repository root
- [x] T005 Add pip install -e . to install package from pyproject.toml in Dockerfile
- [x] T006 Configure PORT environment variable and uvicorn entrypoint in Dockerfile
- [x] T007 Test local Docker build with `docker build -t evalforge-ingestion .` at repository root

**Checkpoint**: Container image builds locally - deployment script development can begin

---

## Phase 3: User Story 1 - One-Command Infrastructure Bootstrap (Priority: P0) 🎯 MVP

**Goal**: Single command to provision all GCP infrastructure (APIs, service account, secrets, Firestore)

**Independent Test**: Run `./scripts/bootstrap_gcp.sh` in fresh GCP project with billing enabled, verify:
- All APIs enabled: `gcloud services list --enabled | grep -E 'firestore|run|secretmanager|cloudscheduler|cloudbuild'`
- Service account exists: `gcloud iam service-accounts list | grep evalforge-ingestion-sa`
- Secrets exist: `gcloud secrets list | grep datadog`

**Estimated Time**: ~60 min

### Implementation for User Story 1

- [x] T008 [US1] Create bootstrap_gcp.sh skeleton with shebang and set -euo pipefail in scripts/bootstrap_gcp.sh
- [x] T009 [US1] Add log_info() and log_error() helper functions with timestamps in scripts/bootstrap_gcp.sh
- [x] T010 [US1] Add environment variable validation (GCP_PROJECT_ID required, GCP_REGION optional with default) in scripts/bootstrap_gcp.sh
- [x] T011 [US1] Add gcloud project configuration and auth check in scripts/bootstrap_gcp.sh
- [x] T012 [US1] Implement enable_api() function with idempotent check in scripts/bootstrap_gcp.sh
- [x] T013 [US1] Add API enablement calls for firestore, run, secretmanager, cloudscheduler, cloudbuild in scripts/bootstrap_gcp.sh
- [x] T014 [US1] Implement create_firestore_database() with existence check in scripts/bootstrap_gcp.sh
- [x] T015 [US1] Implement create_service_account() with existence check and description "Managed by evalforge automation" in scripts/bootstrap_gcp.sh
- [x] T016 [US1] Implement grant_iam_role() for datastore.user and secretmanager.secretAccessor in scripts/bootstrap_gcp.sh
- [x] T017 [US1] Implement create_secret() with placeholder value, label "managed-by=evalforge", and existence check in scripts/bootstrap_gcp.sh
- [x] T018 [US1] Add secret creation calls for datadog-api-key and datadog-app-key in scripts/bootstrap_gcp.sh
- [x] T019 [US1] Implement grant_secret_access() for service account in scripts/bootstrap_gcp.sh
- [x] T020 [US1] Add call to existing bootstrap_firestore.py for collection setup in scripts/bootstrap_gcp.sh
- [x] T021 [US1] Add final success message with next steps instructions in scripts/bootstrap_gcp.sh
- [x] T022 [US1] Make script executable with chmod +x scripts/bootstrap_gcp.sh
- [x] T023 [US1] Test idempotency by running bootstrap_gcp.sh twice in same project

**Checkpoint**: Bootstrap script complete - infrastructure provisioning works in <10 minutes

---

## Phase 4: User Story 2 - One-Command Service Deployment (Priority: P0)

**Goal**: Single command to build Docker image, deploy to Cloud Run, configure Cloud Scheduler

**Independent Test**: Run `./scripts/deploy.sh` after bootstrap completes, verify:
- Service accessible: `curl -s -o /dev/null -w "%{http_code}" https://[SERVICE_URL]/health` returns 200 (or 401 for auth)
- Scheduler exists: `gcloud scheduler jobs list --location=us-central1 | grep evalforge-ingestion-trigger`
- Manual trigger works: `gcloud scheduler jobs run evalforge-ingestion-trigger --location=us-central1`

**Estimated Time**: ~45 min

**Dependency**: Requires Phase 2 (Dockerfile) and US1 (bootstrap) to be complete

### Implementation for User Story 2

- [x] T024 [US2] Create deploy.sh skeleton with shebang and set -euo pipefail in scripts/deploy.sh
- [x] T025 [US2] Add log_info() and log_error() helper functions (can copy from bootstrap) in scripts/deploy.sh
- [x] T026 [US2] Add environment variable validation and defaults in scripts/deploy.sh
- [x] T027 [US2] Implement build_image() using gcloud builds submit in scripts/deploy.sh
- [x] T028 [US2] Implement deploy_cloud_run() with service account, secrets attachment, and label "managed-by=evalforge" in scripts/deploy.sh
- [x] T029 [US2] Add environment variable injection for DATADOG_SITE, FIRESTORE_COLLECTION_PREFIX in scripts/deploy.sh
- [x] T030 [US2] Implement get_service_url() to retrieve deployed service URL in scripts/deploy.sh
- [x] T031 [US2] Implement create_scheduler_job() with OIDC authentication and label "managed-by=evalforge" in scripts/deploy.sh
- [x] T032 [US2] Add idempotent scheduler job handling (delete if exists, then create) in scripts/deploy.sh
- [x] T033 [US2] Add final success message with service URL and scheduler info in scripts/deploy.sh
- [x] T034 [US2] Make script executable with chmod +x scripts/deploy.sh
- [x] T035 [US2] Test deployment end-to-end in GCP project

**Checkpoint**: Deploy script complete - full deployment works in <5 minutes

---

## Phase 5: Integration Testing & Validation

**Purpose**: Verify end-to-end workflow and idempotency
**Estimated Time**: ~15 min

- [ ] T036 Test fresh project workflow: bootstrap → update secrets → deploy in new GCP project
- [ ] T037 Test idempotency: run bootstrap twice, verify "already exists" messages
- [ ] T038 Test idempotency: run deploy twice, verify service updates without errors
- [ ] T039 Test scheduler trigger: manually run job and verify Cloud Run logs show execution
- [ ] T040 Verify quickstart.md instructions match actual script behavior

**Checkpoint**: All user stories validated, ready for hackathon use

---

## Phase 6: Polish & Documentation

**Purpose**: Final cleanup and documentation updates
**Estimated Time**: ~10 min (optional, can skip for hackathon)

- [ ] T041 [P] Add inline comments explaining key sections in scripts/bootstrap_gcp.sh
- [ ] T042 [P] Add inline comments explaining key sections in scripts/deploy.sh
- [ ] T043 Update README.md with infrastructure setup instructions at repository root
- [ ] T044 Verify all scripts follow constitution observability requirements (structured logs)

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup) ─────────────────┐
                                 │
Phase 2 (Foundational/Docker) ───┼──▶ Phase 3 (US1 Bootstrap)
                                 │           │
                                 └───────────┼──▶ Phase 4 (US2 Deploy)
                                             │           │
                                             └───────────┴──▶ Phase 5 (Testing)
                                                                      │
                                                                      ▼
                                                              Phase 6 (Polish)
```

### User Story Dependencies

- **User Story 1 (Bootstrap)**: Can start after Phase 2 (Dockerfile exists) - No dependencies on other stories
- **User Story 2 (Deploy)**: Requires Dockerfile (Phase 2) AND bootstrap to have run at least once (but can develop in parallel if testing separately)

### Critical Path for 2-Hour Target

```
T001-T003 (Setup)     ──▶ 10 min
T004-T007 (Docker)    ──▶ 15 min
T008-T023 (Bootstrap) ──▶ 60 min  ← Most time here
T024-T035 (Deploy)    ──▶ 45 min
T036-T040 (Testing)   ──▶ 15 min
                          ───────
                          ~2.5 hours (some parallel opportunity)
```

**Parallel Opportunity**: T002-T003 can run in parallel. T041-T042 can run in parallel.

### Within Each User Story

1. Script skeleton and helpers first
2. Environment validation
3. Core functions (idempotent implementations)
4. Integration with existing scripts (bootstrap_firestore.py)
5. Success messages and next steps
6. Make executable and test

---

## Parallel Example: Setup Phase

```bash
# Launch these tasks together:
Task: "Create .dockerignore" (T002)
Task: "Create .gcloudignore" (T003)
```

## Parallel Example: User Story 1 Development

```bash
# These helper functions can be written in parallel by different developers:
# (In practice, likely sequential for single developer)
Task: "Implement enable_api() function" (T012)
Task: "Implement create_firestore_database() function" (T014)
Task: "Implement create_service_account() function" (T015)
Task: "Implement create_secret() function" (T017)
```

---

## Implementation Strategy

### MVP First (Bootstrap Only)

1. Complete Phase 1: Setup (~10 min)
2. Complete Phase 2: Dockerfile (~15 min)
3. Complete Phase 3: User Story 1 - Bootstrap (~60 min)
4. **STOP and VALIDATE**: Test bootstrap independently
5. At this point: Infrastructure can be provisioned automatically ✅

### Full Delivery

1. Complete Bootstrap (MVP) ✅
2. Complete Phase 4: User Story 2 - Deploy (~45 min)
3. Complete Phase 5: Integration Testing (~15 min)
4. **VALIDATE**: Full end-to-end workflow works
5. Deploy to production project ✅

### Hackathon Optimization

For fastest hackathon delivery:
1. Skip T041-T044 (polish/documentation)
2. Minimal inline comments
3. Focus on working scripts over perfect scripts
4. Manual testing is sufficient (no automated test suite needed)

---

## Task Summary

| Phase | Tasks | Estimated Time | Story |
|-------|-------|----------------|-------|
| Setup | T001-T003 | 10 min | - |
| Foundational | T004-T007 | 15 min | - |
| US1 Bootstrap | T008-T023 | 60 min | US1 |
| US2 Deploy | T024-T035 | 45 min | US2 |
| Testing | T036-T040 | 15 min | - |
| Polish | T041-T044 | 10 min | - |
| **Total** | **44 tasks** | **~2.5 hours** | |

**MVP Scope** (US1 only): T001-T023 (~85 min)
**Full Scope** (US1 + US2): T001-T040 (~2.5 hours)

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- US3 (Teardown) is DEFERRED - not included in this task list
- Manual testing against live GCP project (no mocked tests)
- Scripts must be idempotent (safe to run multiple times)
- Commit after each major function or logical group
- Stop at any checkpoint to validate independently

## Resource Labels

All GCP resources that support labels will be tagged with `managed-by=evalforge` to enable:
- Filtering: `gcloud run services list --filter="labels.managed-by=evalforge"`
- Identification of automation-created vs manually-created resources
- Future selective cleanup

**Label applied to**: Secrets, Cloud Run, Cloud Scheduler
**Not supported**: Service Account (uses description instead), Firestore DB
