"""Failure pattern extraction service.

This package contains the Cloud Run extraction service that reads unprocessed
failure traces from Firestore, extracts structured failure patterns using
Vertex AI Gemini, validates outputs against the schema, and persists them
for downstream use (evals, guardrails, runbooks).

Shared Utilities (from src/common/):
    - config: load_extraction_settings(), ExtractionSettings, GeminiConfig
    - firestore: get_firestore_client(), collection name helpers
    - pii: redact_and_truncate(), redact_pii_text() for evidence redaction

Modules:
    models: Pydantic request/response models and FailurePattern schema
    prompt_templates: Few-shot prompt template builder
    trace_utils: Trace serialization and truncation helpers
    gemini_client: Vertex AI Gemini wrapper using google-genai SDK
    firestore_repository: Extraction-specific Firestore operations
    main: FastAPI app with /health and /extraction/run-once endpoints
"""
