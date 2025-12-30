# API Contracts (Index)

This folder intentionally does **not** duplicate OpenAPI files. It exists as a single index pointing to the source-of-truth contracts under their original feature specs (avoids drift and keeps reviews small).

## Canonical contracts

- Ingestion: `specs/001-capture-datadog-failures/contracts/ingestion-openapi.yaml`
- Extraction: `specs/002-extract-failure-patterns/contracts/extraction-openapi.yaml`
- Deduplication: `specs/003-suggestion-deduplication/contracts/deduplication-openapi.yaml`
- Eval generator: `specs/004-eval-test-case-generator/contracts/eval-generator-openapi.yaml`
- Approval API: `specs/008-approval-workflow-api/contracts/approval-api-openapi.yaml`
