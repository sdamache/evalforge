# Tasks: Documentation + Devpost Submission

**Input**: Design documents from `specs/012-devpost-submission/`  
**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `quickstart.md`, `contracts/`

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Foundational (Shared)

- [x] T001 [P] [US2] Ensure local demo artifacts are ignored by git by keeping `demo/` in `.gitignore`
- [x] T002 [P] [US3] Create a Mermaid architecture diagram source at `docs/architecture.mmd` and embed it in `README.md`
- [x] T003 [P] [US3] Add a single “API Reference” section in `README.md` linking to canonical OpenAPI contracts under `specs/*/contracts/`

---

## Phase 2: User Story 1 — Run Locally from README (Priority: P1)

**Goal**: README enables a new developer/judge to run locally and verify health endpoints quickly.

**Independent Test**: Follow `README.md` Quick Start and reach `/health` endpoints on the documented ports.

- [x] T010 [US1] Update `README.md` Quick Start to match `docker-compose.yml` service names/ports and required prerequisites
- [x] T011 [US1] Update `README.md` Configuration to clearly separate “required for full demo” vs “optional for local stack”
- [x] T012 [US1] Add an “API Reference” subsection to `README.md` with base URLs + links to the OpenAPI contracts
- [x] T013 [US1] Add “Troubleshooting” notes to `README.md` for missing Datadog credentials, missing Vertex credentials, and Firestore emulator usage

---

## Phase 3: User Story 2 — Devpost Submission Ready (Priority: P1)

**Goal**: Devpost can be submitted in one pass with all required fields and assets.

**Independent Test**: Paste the prepared text into Devpost and confirm all required sections/assets are present.

- [x] T020 [US2] Write Devpost submission copy locally in `demo/devpost_submission.md` (name/tagline, inspiration, what it does, how we built it, challenges, accomplishments, what we learned, what's next, repo link, technologies used)
- [x] T021 [US2] Add screenshot plan (3–5) to `demo/devpost_submission.md` with captions and what each image should show (sanitized)
- [ ] T022 [US2] Record a <=3 minute demo video (local) and add the final YouTube/Vimeo link to `demo/devpost_submission.md`
- [ ] T023 [US2] Capture 3–5 screenshots/GIFs (local) under `demo/` for upload to Devpost (confirm `demo/` remains untracked)
- [x] T024 [US2] Add/verify the Devpost “Technologies used” tag list in `demo/devpost_submission.md` based on `pyproject.toml` and `docker-compose.yml`

---

## Phase 4: User Story 3 — Maintainable Documentation Assets (Priority: P2)

**Goal**: Documentation artifacts are source-controlled and easy to update without drift.

**Independent Test**: A maintainer can update architecture/contract links in one place and README stays consistent.

- [x] T030 [US3] Consolidate architecture + service flow description in `README.md` and keep it consistent with the Mermaid diagram
- [x] T031 [US3] Ensure `README.md` “What’s Next” roadmap reflects realistic next steps based on existing services and specs
- [x] T032 [US3] Ensure `README.md` references canonical contracts under `specs/*/contracts/` (and not scattered per-spec links)

---

## Phase 5: Polish (Cross-Cutting)

- [x] T040 [P] Final pass on `README.md` for broken links, consistency, and clarity
- [x] T041 [P] Run a quick local docs validation: verify `docker-compose.yml` ports match README and all referenced files exist
