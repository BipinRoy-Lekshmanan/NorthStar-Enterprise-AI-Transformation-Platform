# Decisions

## Milestone 1 — Knowledge Ingestion Foundation

- **Chunking is character-based, not token-based.** No tokenizer dependency
  was added in this milestone; `CHUNK_SIZE`/`CHUNK_OVERLAP` are character
  counts. Revisit if a future embedding step wants token-accurate sizing.
- **Chunk IDs are content-addressed**: `sha256(source_path::index::text)[:16]`.
  Editing a document changes the IDs of the chunks it touches — this is
  intentional (stable-for-identical-content, not stable-across-edits).
- **Small heading sections are merged, not dropped**, using whichever
  sub-segment contributed the most characters as the merged chunk's
  heading identity — avoids both tiny fragments and mislabeling merged
  content with an unrepresentative parent heading.
- **Table-cutting avoidance is best-effort**: chunks only get nudged past a
  Markdown table boundary within a bounded slack budget; a table larger
  than that budget can still be split.
- **Frontmatter parsing tolerates malformed/absent YAML** by falling back to
  the first Markdown heading as the document title, since several
  knowledge-base files (e.g. `03_Engineering_Organization.md`, README
  stubs) have no frontmatter at all.
- **Fixed a pre-existing bug**: several `app/` packages used `_init_.py`
  (single underscores) instead of `__init__.py`. Corrected only in the
  packages touched by Milestone 1 (`app`, `config`, `models`, `ingestion`,
  `embeddings`) — left as-is elsewhere since those packages are still
  unimplemented placeholders.
- **Repo is a standalone git repository** nested inside
  `C:\Users\bipin\projects\` (separate from whatever the parent folder
  tracks), pushed to `github.com/BipinRoy-Lekshmanan/NorthStar-Enterprise-AI-Transformation-Platform`.
