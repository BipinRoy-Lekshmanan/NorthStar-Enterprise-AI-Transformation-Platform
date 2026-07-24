"""Deterministic advisor router (Milestone 5).

Selects a primary advisor and a small set of supporting advisors for a
question using two independently-normalized signals over the *existing*
retrieval infrastructure -- never an LLM call. This is a deliberate
design choice: routing must stay pure, instantly testable, and
reproducible, per the milestone's "deterministic, explainable, testable"
requirement.

Signals:

1. Retrieval signal: one unfiltered `Retriever.retrieve()` call (the
   exact same `Retriever` from Milestone 2). Each result's score is
   attributed to whichever advisor's `default_filters["document_id"]`
   matches that chunk's `document_id`.
2. Keyword signal: substring match of each advisor's `domain_keywords`
   against the lowercased question.

Neither signal touches generation, context construction, or citations --
this module only decides *which* advisors `AdvisorOrchestrator` should
call.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.base_agent import Advisor
from app.config.settings import RouterSettings
from app.models.query import RetrievalQuery
from app.rag.retriever import Retriever


@dataclass(frozen=True)
class RoutingDecision:
    primary_advisor: str
    supporting_advisors: list[str]
    confidence: float
    rationale: str
    detected_domains: list[str]
    fallback_used: bool


class AdvisorRouter:
    def __init__(
        self,
        retriever: Retriever,
        advisors: list[Advisor],
        settings: RouterSettings | None = None,
    ):
        if not advisors:
            raise ValueError("AdvisorRouter requires at least one advisor.")
        self._retriever = retriever
        self._advisors = list(advisors)
        self._settings = settings or RouterSettings.from_env()

    def route(self, question: str) -> RoutingDecision:
        retrieval_signal = self._retrieval_signal(question)
        keyword_signal = self._keyword_signal(question)

        combined = self._combine(retrieval_signal, keyword_signal)

        ranked = sorted(combined.items(), key=lambda item: item[1], reverse=True)
        primary_id, primary_score = ranked[0]

        supporting_ids = self._select_supporting(ranked, primary_id, primary_score)

        detected_domains = self._detected_domains(keyword_signal)
        fallback_used = primary_score < self._settings.router_min_confidence
        rationale = self._build_rationale(
            primary_id, retrieval_signal, keyword_signal, primary_score, fallback_used
        )

        return RoutingDecision(
            primary_advisor=primary_id,
            supporting_advisors=supporting_ids,
            confidence=primary_score,
            rationale=rationale,
            detected_domains=detected_domains,
            fallback_used=fallback_used,
        )

    def _retrieval_signal(self, question: str) -> dict[str, float]:
        """Average cosine-similarity score of the unfiltered top-k chunks
        attributed to each advisor's document.

        Deliberately kept on the retriever's own absolute similarity
        scale (never re-normalized to make some advisor "1.0") -- an
        off-topic question retrieves chunks with a genuinely lower
        absolute score than an on-topic one (see `RagService`'s own
        insufficient-context logic, which relies on the same property).
        Normalizing away that absolute magnitude would make every
        question look "confidently" routable even when nothing in the
        knowledge base is actually relevant.
        """
        score_totals: dict[str, float] = {advisor.advisor_id: 0.0 for advisor in self._advisors}
        match_counts: dict[str, int] = {advisor.advisor_id: 0 for advisor in self._advisors}

        document_owner: dict[str, str] = {}
        for advisor in self._advisors:
            document_id = advisor.default_filters.get("document_id")
            if document_id:
                document_owner[document_id] = advisor.advisor_id

        query = RetrievalQuery(text=question, top_k=self._settings.router_retrieval_top_k)
        response = self._retriever.retrieve(query)

        for result in response.results:
            document_id = result.chunk.document_id
            if document_id and document_id in document_owner:
                advisor_id = document_owner[document_id]
                score_totals[advisor_id] += result.score
                match_counts[advisor_id] += 1

        return {
            advisor_id: (score_totals[advisor_id] / match_counts[advisor_id]) if match_counts[advisor_id] else 0.0
            for advisor_id in score_totals
        }

    def _keyword_signal(self, question: str) -> dict[str, float]:
        lowered = question.lower()
        raw_scores: dict[str, float] = {}
        for advisor in self._advisors:
            hits = sum(1 for keyword in advisor.domain_keywords if keyword.lower() in lowered)
            raw_scores[advisor.advisor_id] = float(hits)
        return _normalize_by_max(raw_scores)

    def _combine(
        self, retrieval_signal: dict[str, float], keyword_signal: dict[str, float]
    ) -> dict[str, float]:
        retrieval_weight = self._settings.router_retrieval_weight
        keyword_weight = self._settings.router_keyword_weight
        return {
            advisor.advisor_id: (
                retrieval_weight * retrieval_signal.get(advisor.advisor_id, 0.0)
                + keyword_weight * keyword_signal.get(advisor.advisor_id, 0.0)
            )
            for advisor in self._advisors
        }

    def _select_supporting(
        self,
        ranked: list[tuple[str, float]],
        primary_id: str,
        primary_score: float,
    ) -> list[str]:
        if primary_score <= 0:
            return []

        min_ratio = self._settings.router_supporting_min_ratio
        max_supporting = self._settings.router_max_supporting_advisors
        threshold = primary_score * min_ratio

        supporting: list[str] = []
        for advisor_id, score in ranked:
            if advisor_id == primary_id:
                continue
            if len(supporting) >= max_supporting:
                break
            if score >= threshold and score > 0:
                supporting.append(advisor_id)

        return supporting

    def _detected_domains(self, keyword_signal: dict[str, float]) -> list[str]:
        display_names = {advisor.advisor_id: advisor.display_name for advisor in self._advisors}
        hits = [(advisor_id, score) for advisor_id, score in keyword_signal.items() if score > 0]
        hits.sort(key=lambda item: item[1], reverse=True)
        return [display_names[advisor_id] for advisor_id, _ in hits]

    def _build_rationale(
        self,
        primary_id: str,
        retrieval_signal: dict[str, float],
        keyword_signal: dict[str, float],
        primary_score: float,
        fallback_used: bool,
    ) -> str:
        retrieval_value = retrieval_signal.get(primary_id, 0.0)
        keyword_value = keyword_signal.get(primary_id, 0.0)
        base = (
            f"Selected '{primary_id}' with combined score {primary_score:.3f} "
            f"(retrieval={retrieval_value:.3f}, keyword={keyword_value:.3f})."
        )
        if fallback_used:
            base += (
                f" Below minimum confidence {self._settings.router_min_confidence:.3f}; "
                "treating as a low-confidence fallback."
            )
        return base


def _normalize_by_max(raw_scores: dict[str, float]) -> dict[str, float]:
    max_value = max(raw_scores.values(), default=0.0)
    if max_value <= 0:
        return {key: 0.0 for key in raw_scores}
    return {key: value / max_value for key, value in raw_scores.items()}
