"""app.rag.index / app.rag.evaluate are thin aliases so all user-facing
RAG commands (index, ask, evaluate) live under one namespace -- verify
they actually point at the real implementations, not a stale copy."""

import app.embeddings.indexer as real_indexer
import app.evaluation.rag_evaluator as real_evaluator
import app.rag.evaluate as evaluate_alias
import app.rag.index as index_alias


def test_index_alias_points_at_real_indexer_main():
    assert index_alias.main is real_indexer.main


def test_evaluate_alias_points_at_real_evaluator_main():
    assert evaluate_alias.main is real_evaluator.main
