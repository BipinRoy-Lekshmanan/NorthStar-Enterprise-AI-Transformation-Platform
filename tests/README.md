# tests/

Pytest suite for the Milestone 1 ingestion pipeline.

```bash
pip install -r requirements-dev.txt
python -m pytest
```

| File | Covers |
|---|---|
| `test_settings.py` | `IngestionSettings` env parsing and fail-fast validation |
| `test_document_loader.py` | Recursive discovery, hidden/generated-file filtering, deterministic order, missing-directory handling |
| `test_markdown_loader.py` | UTF-8 loading, per-file error isolation, content hashing |
| `test_metadata_extractor.py` | YAML frontmatter parsing, heading extraction, missing-metadata fallbacks |
| `test_chunking.py` | Heading-hierarchy segmentation, fragment merging, size/overlap splitting, table-boundary avoidance, stable chunk IDs |
| `test_pipeline.py` | End-to-end discover → load → chunk → persist, including artifact contents |

`pytest.ini` sets `pythonpath = .` so `import app...` resolves without an
installed package.
