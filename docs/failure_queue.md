# Failure Queue

## Purpose
Provide reviewers a grouped view of captured failures with filters (time, severity, agent) to triage incidents without querying Datadog.

## Data Source
- Firestore collection: `{FIRESTORE_COLLECTION_PREFIX}raw_traces` (written by ingestion).
- Grouping key: `(failure_type, service_name, severity)`.
- Aggregations: sum `recurrence_count`, collect `trace_ids`, track `latest_fetched_at`.

## API
- `GET /capture-queue`
  - Query params:
    - `startTime`, `endTime`: ISO datetimes (UTC recommended).
    - `severity`: e.g., `high`, `medium`, `low`.
    - `agent`: `service_name` filter.
    - `pageSize`: 1–500 (default 50).
    - `cursor`: pagination cursor (last `fetched_at`).
  - Response: `{ "items": [ { failure_type, service_name, severity, recurrence_count, latest_fetched_at, trace_ids } ], "nextCursor": "<cursor>" }`

## Filtering & Pagination
- Firestore query applies time, severity, and agent filters.
- Ordered by `fetched_at` desc; pagination uses `start_after(cursor)` with `pageSize` limit.
- Next cursor is the `fetched_at` of the last returned item; pass it back as `cursor` for the next page.

## Error Handling & Logging
- Structured error logs include filter context and trace correlation where available.
- Query failures return HTTP 500 with generic message; 400 on invalid datetime formats.

## Usage (local)
```bash
evalforge_venv/bin/uvicorn src.api.main:app --reload
curl "http://localhost:8000/capture-queue?severity=high&agent=llm-agent&pageSize=25"
```

## Known Gaps / Next Steps
- Add auth and rate limiting for queue endpoints.
- Add sort options (e.g., severity-first).
- Surface recurrence trend metrics in the response.
