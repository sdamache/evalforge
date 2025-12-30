# Research: Approval Workflow API

**Branch**: `008-approval-workflow-api` | **Date**: 2025-12-29
**Research Validated**: 2025-12-29 (6 parallel research agents with web searches)

## Research Tasks Completed

### 1) Atomic Status Transitions in Firestore

**Decision**: Use Firestore transactions with `@firestore.transactional` decorator to ensure atomic status updates with `version_history` append.

**Rationale**:
- Prevents race conditions when multiple users attempt to approve the same suggestion
- Python SDK uses **pessimistic locking** - more reliable for server-side operations
- All reads MUST occur before any writes in the transaction

**Validated Implementation Pattern**:
```python
from google.cloud import firestore
from google.cloud.firestore_v1.transforms import ArrayUnion
from datetime import datetime, timezone

db = firestore.Client()

@firestore.transactional
def approve_suggestion(transaction, suggestion_ref, actor: str, notes: str = None):
    """Atomically transition status from pending to approved."""

    # Step 1: Read current state (MUST happen before writes)
    snapshot = suggestion_ref.get(transaction=transaction)

    if not snapshot.exists:
        raise ValueError("Suggestion not found")

    current_status = snapshot.get("status")
    if current_status != "pending":
        raise ValueError(f"Cannot approve: status is '{current_status}'")

    # Step 2: Prepare history entry
    history_entry = {
        "previous_status": current_status,
        "new_status": "approved",
        "actor": actor,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "notes": notes
    }

    # Step 3: Atomic update - status + history in single transaction
    transaction.update(suggestion_ref, {
        "status": "approved",
        "updated_at": firestore.SERVER_TIMESTAMP,
        "approval_metadata": {...},
        "version_history": ArrayUnion([history_entry])
    })

# Usage: transaction = db.transaction(max_attempts=5)  # Default: 5 retries
```

**Transaction Limits** (from Google Cloud docs):
| Limit | Value |
|-------|-------|
| Default max attempts | 5 retries |
| Transaction timeout | 270 seconds |
| Max documents per transaction | 500 |

**Gotchas**:
- Read-before-write rule is strict
- Don't modify external state in transaction functions (may run multiple times due to retries)
- ArrayUnion uses value equality for deduplication (timestamps make entries unique)

**Sources**:
- [Firestore Transactions (Google Cloud)](https://cloud.google.com/firestore/native/docs/manage-data/transactions)
- [Data Contention in Transactions](https://cloud.google.com/firestore/native/docs/transaction-data-contention)

---

### 2) API Key Authentication Strategy

**Decision**: Use `X-API-Key` header with FastAPI's `APIKeyHeader` and `secrets.compare_digest()` for constant-time comparison.

**Rationale**:
- Simple to implement for hackathon scope
- `auto_error=True` automatically returns 401 when header is missing
- Constant-time comparison prevents timing attacks

**Validated Implementation Pattern**:
```python
import secrets
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

API_KEY = os.getenv("APPROVAL_API_KEY")

api_key_header = APIKeyHeader(
    name="X-API-Key",
    description="API key for authentication",
    auto_error=True  # Returns 401 automatically if missing
)

def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """Validate API key with constant-time comparison."""
    if not API_KEY or not secrets.compare_digest(api_key, API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "APIKey"},
        )
    return api_key
```

**HTTP Status Codes**:
| Scenario | Status Code |
|----------|-------------|
| Missing API key | 401 Unauthorized |
| Invalid API key | 401 Unauthorized |
| Valid key, no permission | 403 Forbidden |

**Sources**:
- [FastAPI Security Reference](https://fastapi.tiangolo.com/reference/security/)
- [Python secrets module](https://docs.python.org/3/library/secrets.html)

---

### 3) Webhook Delivery Strategy

**Decision**: Fire-and-forget with 5-second timeout using FastAPI BackgroundTasks. Use Block Kit for rich formatting.

**Rationale**:
- Approval is the critical path; notifications are secondary
- Slack rate limit: 1 message per second per channel
- Webhook failures must not block approval

**Validated Implementation Pattern**:
```python
from fastapi import BackgroundTasks
import httpx

async def send_slack_notification(webhook_url: str, payload: dict) -> bool:
    """Fire-and-forget Slack delivery with 5s timeout."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(webhook_url, json=payload)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "unknown")
                logger.warning(f"Slack rate limited. Retry after: {retry_after}s")
                return False
            return response.status_code == 200
    except httpx.TimeoutException:
        logger.warning("Slack webhook timed out (continuing)")
        return False
    except Exception as e:
        logger.error(f"Slack webhook error: {e}")
        return False

# Block Kit payload format
def build_approval_payload(suggestion_id: str, action: str, actor: str) -> dict:
    return {
        "text": f"Suggestion {suggestion_id} was {action} by {actor}",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": f"Suggestion {action.title()}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*ID:* `{suggestion_id}`\n*Action:* {action}\n*By:* {actor}"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{datetime.utcnow().isoformat()}_"}]}
        ]
    }

# Usage in endpoint
@app.post("/suggestions/{id}/approve")
async def approve(id: str, background_tasks: BackgroundTasks):
    result = await process_approval(id)
    background_tasks.add_task(send_slack_notification, WEBHOOK_URL, build_approval_payload(...))
    return result  # Returns immediately
```

**Slack Rate Limits**:
| Limit | Value |
|-------|-------|
| Messages per channel | 1 per second |
| HTTP 429 response | Includes `Retry-After` header |
| Recommended timeout | 3-5 seconds |

**Sources**:
- [Slack Incoming Webhooks](https://api.slack.com/messaging/webhooks)
- [Slack Rate Limits](https://api.slack.com/docs/rate-limits)
- [Block Kit Builder](https://api.slack.com/block-kit)

---

### 4) Export Format Generation - DeepEval JSON

**Decision**: Generate DeepEval-compatible JSON with the 9-parameter LLMTestCase schema.

**DeepEval LLMTestCase Schema** (2024-2025):
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `input` | `str` | **Required** | User input/query to the LLM |
| `actual_output` | `str` | **Required** | The LLM's actual response |
| `expected_output` | `str` | Optional | Ideal/ground truth output |
| `context` | `List[str]` | Optional | Static knowledge base segments |
| `retrieval_context` | `List[str]` | Optional | Dynamic RAG retrieval results |
| `tools_called` | `List[ToolCall]` | Optional | Tools invoked during execution |
| `expected_tools` | `List[ToolCall]` | Optional | Expected tools to be called |
| `token_cost` | `float` | Optional | Cost in tokens |
| `completion_time` | `float` | Optional | Time in seconds |

**Valid DeepEval Export Format**:
```json
[
  {
    "input": "What if these shoes don't fit?",
    "actual_output": "We offer a 30-day full refund at no extra cost.",
    "expected_output": "You are eligible for a 30 day full refund.",
    "context": ["All customers are eligible for a 30 day full refund."],
    "retrieval_context": ["Only shoes can be refunded."]
  }
]
```

**Validation**:
```python
import json
# Validate JSON is parseable
json.loads(exported_content)
# For CI: deepeval test run tests/
```

**Sources**:
- [DeepEval Test Cases](https://deepeval.com/docs/evaluation-test-cases)
- [DeepEval Datasets](https://deepeval.com/docs/evaluation-datasets)

---

### 5) Suggestion Listing with Pagination

**Decision**: Use **cursor-based pagination** with `start_after()` (NOT offset) following existing codebase patterns.

**IMPORTANT CORRECTION**: Initial research suggested offset-based pagination, but web research confirms:
- `offset()` in Firestore is **NOT recommended** - skipped documents are still billed
- Existing codebase (`capture_queue.py`, `firestore_repository.py`) already uses cursor-based pagination correctly

**Validated Implementation Pattern** (from existing codebase):
```python
# First page
query = collection.where("status", "==", status_filter)
query = query.order_by("created_at", direction=firestore.Query.DESCENDING)
query = query.limit(page_size)

# Subsequent pages - use document ID as cursor
if page_cursor:
    cursor_doc = collection.document(page_cursor).get()
    if cursor_doc.exists:
        query = query.start_after(cursor_doc)

# Use limit + 1 trick to detect more results
query = query.limit(limit + 1)
docs = list(query.stream())
has_more = len(docs) > limit
results = docs[:limit]
```

**Performance Comparison**:
| Page | Offset Cost | Cursor Cost |
|------|-------------|-------------|
| Page 1 (0-50) | 50 reads | 50 reads |
| Page 10 (450-500) | 500 reads | 50 reads |
| Page 100 (4950-5000) | 5,000 reads | 50 reads |

**Sources**:
- [Paginate data with query cursors (Firebase)](https://firebase.google.com/docs/firestore/query-data/query-cursors)
- [Never use offset pagination in Firestore](https://firebeast.dev/tips/do-not-use-offset)

---

### 6) Version History Schema

**Decision**: Append-only array embedded on the Suggestion document using `ArrayUnion`.

**Rationale** (validated by research):
- Embedded array is correct for **bounded, predictable transitions** (max 1-2 status changes)
- Subcollection would be overkill - only needed for unbounded growth or cross-document queries
- Existing codebase uses `status_history` field with same pattern

**Validated Schema**:
```python
class StatusHistoryEntry(BaseModel):
    previous_status: Optional[str]  # null for creation
    new_status: str
    actor: str
    timestamp: datetime
    notes: Optional[str]

# In Firestore document
{
  "version_history": [
    {"previous_status": null, "new_status": "pending", "timestamp": "...", "actor": "deduplication-service"},
    {"previous_status": "pending", "new_status": "approved", "timestamp": "...", "actor": "user@example.com", "notes": "Validated"}
  ]
}
```

**When to Consider Subcollection Instead**:
| Scenario | Recommendation |
|----------|----------------|
| Entries grow indefinitely | Subcollection |
| Need cross-document audit queries | Subcollection |
| Approaching 1MB document limit | Subcollection |
| **Bounded transitions (1-2 max)** | **Embedded array (our case)** |

**Sources**:
- [Choose a Data Structure (Firebase)](https://firebase.google.com/docs/firestore/manage-data/structure-data)
- [Firestore Quotas and Limits](https://firebase.google.com/docs/firestore/quotas)

---

## Key Corrections from Research

| Original Assumption | Correction |
|---------------------|------------|
| Offset-based pagination | Use **cursor-based** (`start_after`) - offset bills for skipped docs |
| Simple webhook POST | Use **Block Kit** format for rich Slack messages |
| Generic JSON export | Use **DeepEval 9-parameter schema** for compatibility |

## Resolved Clarifications

- Authentication: API key in `X-API-Key` header with `secrets.compare_digest()`
- Webhook delivery: Fire-and-forget with BackgroundTasks, 5s timeout, Block Kit format
- Export generation: On-demand with DeepEval-compatible JSON schema
- Pagination: Cursor-based (`start_after`) following existing codebase patterns
- Audit trail: Append-only `version_history` array (embedded, not subcollection)
- Transactions: Default 5 retries, 500 doc limit, read-before-write required

## Next Steps

Proceed to `/speckit.tasks` with validated research findings.
