"""CLI alias: python -m app.rag.evaluate

Evaluation logic lives in `app.evaluation.rag_evaluator` (it's an
evaluation-layer concern, and future milestones' evaluators belong
alongside it), but is exposed here too so all user-facing RAG commands
share one namespace: `app.rag.index`, `app.rag.ask`, `app.rag.evaluate`.
"""

from app.evaluation.rag_evaluator import main

if __name__ == "__main__":
    main()
