"""CLI alias: python -m app.rag.index

Indexing logic lives in `app.embeddings.indexer` (it's fundamentally an
embeddings/vector-store concern), but is exposed here too so all
user-facing RAG commands share one namespace: `app.rag.index`,
`app.rag.ask`, `app.rag.evaluate`.
"""

from app.embeddings.indexer import main

if __name__ == "__main__":
    main()
