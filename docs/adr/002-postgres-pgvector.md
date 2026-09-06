# ADR-002: PostgreSQL + pgvector as the only datastore

**Status**: accepted · 2026-09-06

## Context
The reference design kept embeddings as JSON in MySQL and did cosine similarity in
NumPy, with no migrations. An air-gapped deployment should have the fewest moving
parts possible, and retrieval must scope to a project.

## Decision
- One PostgreSQL 16 container with the `pgvector` extension.
- `chunks.embedding vector(EMBEDDING_DIM)` with an HNSW cosine index; queries filter by `project_id` first.
- Alembic owns the schema; `EMBEDDING_DIM` is read at migration time.
- `rag_config.embedding_model` records which model built the index; the retriever refuses to query with a different model.
- The `jobs` table is the queue (`FOR UPDATE SKIP LOCKED`), so no Redis/Celery.

## Consequences
- Backups, auth and provisioning are one thing.
- Changing the embedding model is a deliberate migration + re-embed, not a silent mismatch.
- Hybrid search (BM25) can be added with `tsvector` in the same table (roadmap A).
- If throughput ever demands a real broker, only `core/jobs/service.py` and the worker loop change.
