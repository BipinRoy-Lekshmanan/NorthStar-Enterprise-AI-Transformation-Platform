"""Knowledge-base index diagnostics (Milestone 8).

Separate from `app.api.services.knowledge_service` (the API-boundary
facade) -- this package is a standalone, read-only CLI diagnostic, with
no FastAPI dependency, for verifying the vector index's health outside
of any running API process.
"""
