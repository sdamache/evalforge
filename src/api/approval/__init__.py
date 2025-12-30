"""Approval workflow API module.

Provides human-in-the-loop approval workflow for EvalForge suggestions.
Enables platform leads to approve or reject suggestions with one click,
trigger webhook notifications, and export approved artifacts.

Submodules:
    - router: FastAPI router for /suggestions/* endpoints
    - models: Pydantic request/response models
    - service: Business logic (approve, reject, export)
    - repository: Firestore operations (atomic updates)
    - webhook: Slack notification sender
    - exporters: Format exporters (DeepEval, Pytest, YAML)
"""

from src.api.approval.router import router

__all__ = ["router"]
