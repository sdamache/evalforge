"""Utility script to create the Firestore collections defined in config."""

from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import firestore

from src.common.config import load_settings


def ensure_collection(client: firestore.Client, name: str) -> None:
    """Create a collection by writing a bootstrap document if it doesn't exist."""
    doc_ref = client.collection(name).document("_bootstrap_placeholder")
    doc_ref.set(
        {
            "note": "Evalforge bootstrap placeholder",
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        },
        merge=True,
    )


def main() -> None:
    settings = load_settings()
    kwargs = {}
    if settings.firestore.project_id:
        kwargs["project"] = settings.firestore.project_id
    if settings.firestore.database_id:
        kwargs["database"] = settings.firestore.database_id
    client = firestore.Client(**kwargs)

    raw_collection = f"{settings.firestore.collection_prefix}raw_traces"
    exports_collection = f"{settings.firestore.collection_prefix}exports"

    ensure_collection(client, raw_collection)
    ensure_collection(client, exports_collection)
    print(f"Created/verified collections: {raw_collection}, {exports_collection}")


if __name__ == "__main__":
    main()
