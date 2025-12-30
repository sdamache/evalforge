# Data Model: Documentation + Submission Assets

**Branch**: `012-devpost-submission` | **Date**: 2025-12-30

This feature does not introduce new runtime storage. The “data model” here captures the source-controlled artifacts required to ship a complete README + Devpost submission and how they relate to each other.

## Entity Overview

```
┌──────────────────────────┐         ┌──────────────────────────┐
│        DocArtifact        │ 1    n  │      SubmissionAsset     │
│  (in-repo source files)   │─────────│ (screenshots / video)    │
└──────────────────────────┘         └──────────────────────────┘
          │
          │ n
          │
          ▼ 1
┌──────────────────────────┐
│     TechnologyTagList     │
│ (used in README/Devpost)  │
└──────────────────────────┘
```

## Entities

### DocArtifact

Represents a deliverable stored in the repository that is required for onboarding and/or submission.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `artifact_id` | string | Yes | Stable identifier (e.g., `readme`, `architecture_diagram`, `devpost_copy`) |
| `type` | enum | Yes | Artifact classification (see `DocArtifactType`) |
| `repo_path` | string | Yes | Path to the source file in the repo |
| `purpose` | string | Yes | What this artifact is used for |
| `source_of_truth` | string | Yes | Where updates must be made (often same as `repo_path`) |
| `depends_on` | array[string] | No | Other artifacts this one references (e.g., README depends on contracts bundle) |

**Validation Rules**
- `repo_path` MUST exist in the repo at release/submission time.
- Artifacts MUST NOT include secrets, credentials, or raw user PII.

### SubmissionAsset

Represents externally uploaded assets (Devpost screenshots/GIFs + demo video link) that are *derived from* repo state.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `asset_id` | string | Yes | Stable identifier (e.g., `screenshot_01_architecture`) |
| `type` | enum | Yes | One of: `screenshot`, `gif`, `video_link` |
| `caption` | string | Yes | Human-readable caption for Devpost |
| `recommended_source` | string | Yes | What to capture (UI page, command output, diagram export) |
| `location` | string | No | Final uploaded URL (or local path before upload) |
| `status` | enum | Yes | One of: `planned`, `captured`, `edited`, `uploaded` |
| `order` | integer | Yes | Ordering for submission gallery (1..n) |
| `derived_from_artifact_ids` | array[string] | No | References `DocArtifact.artifact_id` values used to generate it |

**Validation Rules**
- Captures MUST be sanitized (no API keys, tenant data, or raw PII).
- Captures SHOULD match the ports/endpoints in `docker-compose.yml` for local demo consistency.

### TechnologyTagList

Normalized list of technologies used, referenced from README and Devpost.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tags` | array[string] | Yes | Technology names suitable for Devpost “Technologies used” |
| `source_paths` | array[string] | Yes | Where these technologies are defined/validated (e.g., `pyproject.toml`, `docker-compose.yml`) |

