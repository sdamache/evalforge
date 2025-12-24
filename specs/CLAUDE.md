# Spec-Kit Implementation Guidelines

This file provides mandatory instructions for implementing features defined in `specs/` subdirectories.

## CRITICAL: Before Starting ANY New Spec

### Check Deferred Decisions from Previous Specs

Before implementing a new feature, scan `plan.md` files in previous specs for **Deferred Decisions** that this new feature might trigger:

```bash
# Find all deferred decisions across specs
grep -r "Deferred Decisions" specs/*/plan.md -A 20
```

**Ask**: "Does this new spec trigger any pending deferred decisions?"

| If Trigger Matches... | Then... |
|----------------------|---------|
| DD involves same domain (e.g., Gemini for generators) | Address consolidation as part of this spec |
| DD involves shared utility | Consider consolidation spec first |
| DD doesn't match | Proceed, document any new deferred decisions |

---

## CRITICAL: Before Writing ANY New Code

### 1. Explore Existing Code First (MANDATORY)

Before creating any new file, you MUST search the codebase for existing implementations:

```bash
# Search for similar patterns in src/
grep -r "pattern_name" src/
ls -la src/common/  # Check what shared utilities exist
ls -la src/*/       # See all service directories
```

**Ask yourself these questions:**

| Before Creating... | Check For... |
|-------------------|--------------|
| `config.py` | Does `src/common/config.py` already have the helpers I need? |
| `models.py` | Are there shared enums/dataclasses in existing models? |
| PII/redaction code | Does `src/common/pii.py` or `src/ingestion/pii_sanitizer.py` exist? |
| Firestore operations | Is there a pattern in `src/common/firestore.py` or existing services? |
| API endpoints | How do existing services (`src/ingestion/main.py`, `src/api/main.py`) structure their endpoints? |
| Logging | Always use `src/common/logging.py` - never create new logging helpers |

### 2. Reuse vs. Extend vs. Create Decision Framework

```
┌─────────────────────────────────────────────────────────────────┐
│                    Does similar code exist?                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              │                           │
              ▼                           ▼
        YES exists                    NO, doesn't exist
              │                           │
              ▼                           ▼
┌─────────────────────────┐    ┌─────────────────────────┐
│  Is it in src/common/?  │    │  Will other services    │
│                         │    │  likely need this?      │
└───────────┬─────────────┘    └───────────┬─────────────┘
            │                              │
    ┌───────┴───────┐              ┌───────┴───────┐
    ▼               ▼              ▼               ▼
   YES              NO            YES              NO
    │               │              │               │
    ▼               ▼              ▼               ▼
 IMPORT &       EXTEND &       CREATE in      CREATE in
  USE IT       CONSOLIDATE    src/common/    src/<service>/
                to common
```

### 3. Design Questions to Ask BEFORE Implementation

When starting implementation of any task, explicitly ask these questions:

1. **Config**: "Does `src/common/config.py` have helpers I should import?"
2. **Models**: "Are there shared enums or dataclasses I should reuse?"
3. **Utilities**: "What helper functions exist in `src/common/`?"
4. **Patterns**: "How do existing services implement similar functionality?"
5. **Terminology**: "Am I using the same terms (trace vs span) as existing code?"

### 4. Standard Import Pattern

When writing a new service module, start with this template:

```python
"""Module docstring explaining purpose."""

# Standard library
from typing import Any, Dict, List, Optional

# Shared utilities - ALWAYS check these first
from src.common.config import (
    ConfigError,
    FirestoreConfig,
    GeminiConfig,
    load_firestore_config,
    load_gemini_config,
)
from src.common.firestore import get_firestore_client, FirestoreError
from src.common.logging import get_logger, log_decision, log_error
from src.common.pii import redact_pii_text, strip_pii_fields

# Service-specific imports
from src.<service>.models import ...

logger = get_logger(__name__)
```

## Shared Modules Reference

### `src/common/config.py`
- `ConfigError`: Base exception for config errors
- `_get_env()`, `_int_env()`, `_float_env()`, `_optional_env()`: Env var helpers
- `FirestoreConfig`: Firestore connection settings
- `GeminiConfig`: Gemini model settings
- `load_settings()`: Full settings for ingestion
- `load_firestore_config()`: Just Firestore config
- `load_gemini_config()`: Just Gemini config

### `src/common/firestore.py`
- `get_firestore_client()`: Get configured client
- `compute_backlog_size()`: Count documents in collection
- `raw_traces_collection()`, `failure_patterns_collection()`: Collection name helpers

### `src/common/pii.py`
- `PII_FIELDS_TO_STRIP`: Field paths to remove
- `PII_PATTERNS`: Regex patterns for text redaction
- `redact_pii_text()`: Redact PII from strings
- `strip_pii_fields()`: Remove fields from dicts
- `filter_pii_tags()`: Clean tag lists
- `hash_user_id()`: Pseudonymize user IDs

### `src/common/logging.py`
- `get_logger()`: JSON-formatted logger
- `log_decision()`: Structured decision logging
- `log_error()`: Error logging with trace correlation
- `log_audit()`: Audit trail logging

## Anti-Patterns to Avoid

❌ **DON'T**: Copy-paste helper functions from another module
✅ **DO**: Import from `src/common/` or extract to common if needed

❌ **DON'T**: Create service-specific config loaders that duplicate common helpers
✅ **DO**: Extend the common Settings class or compose with existing configs

❌ **DON'T**: Define new PII patterns without checking existing ones
✅ **DO**: Use `src/common/pii.py` and extend if needed

❌ **DON'T**: Create inline Firestore client initialization
✅ **DO**: Use `get_firestore_client()` from `src/common/firestore.py`

❌ **DON'T**: Assume terminology (trace vs span, pattern vs capture)
✅ **DO**: Check existing code and ask for clarification if unclear
