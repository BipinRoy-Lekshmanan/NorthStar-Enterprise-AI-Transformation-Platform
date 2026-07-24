"""Rule-based conflict detection across advisor answers within a workflow
execution (Milestone 6).

Deterministic and fully explainable -- no second LLM judge, no fuzzy
matching. For each pair of advisor stage results that both mention the
same fixed topic keyword, classifies each advisor's stance on that topic
via a small literal-phrase lexicon (positive vs. blocking) in a bounded
window around the topic mention. A positive-vs-blocking split on the
same topic between two advisors becomes a high-severity, blocking
`ReviewFinding` quoting the exact matched phrases -- so every conflict
finding is traceable to literal text, never inferred.

Coarse by design: false negatives (a real disagreement phrased outside
this lexicon) are expected and acceptable, per the milestone's "simple
and explainable, not exhaustive NLU" guidance. This is the stage body
for `stage_type == "conflict_review"`.
"""

from __future__ import annotations

import re

from app.models.workflow import ReviewFinding, WorkflowStageResult

_WINDOW_CHARS = 200

CONFLICT_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "rollback": ("rollback", "roll back"),
    "security_review": ("security review", "security control", "security risk"),
    "scalability": ("scalability", "scale", "throughput"),
    "testing_evidence": ("test coverage", "test evidence", "testing evidence"),
    "release_readiness": ("release readiness", "production readiness", "go-live"),
    "data_privacy": ("data privacy", "data classification", "sensitive data"),
    "monitoring": ("monitoring", "observability", "alerting"),
    "human_review": ("human review", "human oversight", "human-in-the-loop"),
    "architecture_alignment": ("architecture principle", "architecture standard", "design principle"),
}

POSITIVE_MARKERS = (
    "approved", "sufficient", "ready", "meets", "no concerns", "no blocking",
    "satisfies", "acceptable", "in place", "adequate", "compliant",
)

BLOCKING_MARKERS = (
    "not ready", "insufficient", "blocked", "must not", "fails to", "no rollback",
    "critical gap", "not sufficient", "not approved", "blocking risk", "missing",
    "does not meet", "unacceptable", "high risk", "not acceptable",
)


def _find_topics(text: str) -> dict[str, list[int]]:
    """Map topic -> character offsets where a topic keyword was found."""
    lowered = text.lower()
    hits: dict[str, list[int]] = {}
    for topic, keywords in CONFLICT_TOPIC_KEYWORDS.items():
        offsets = [m.start() for kw in keywords for m in re.finditer(re.escape(kw), lowered)]
        if offsets:
            hits[topic] = offsets
    return hits


def _stance_at(text: str, offset: int) -> tuple[str | None, str | None]:
    """Return (stance, matched_phrase) for the window around `offset`.

    stance is "positive", "blocking", or None if neither marker is
    present. Blocking takes precedence over positive when both appear in
    the same window -- a blocking call-out should never be silently
    outvoted by a nearby positive word.
    """
    lowered = text.lower()
    start = max(0, offset - _WINDOW_CHARS)
    end = min(len(text), offset + _WINDOW_CHARS)
    window = lowered[start:end]

    for marker in BLOCKING_MARKERS:
        if marker in window:
            return "blocking", marker
    for marker in POSITIVE_MARKERS:
        if marker in window:
            return "positive", marker
    return None, None


def detect_conflicts(stage_results: list[WorkflowStageResult]) -> list[ReviewFinding]:
    """Detect topic-level stance conflicts between completed advisor stage
    results. Only considers results with `advisor_name` set, `status ==
    "completed"`, and a non-empty `answer`.
    """
    advisor_results = [
        result for result in stage_results
        if result.advisor_name and result.status == "completed" and result.answer
    ]

    # topic -> advisor_name -> (stance, matched_phrase)
    topic_stances: dict[str, dict[str, tuple[str, str]]] = {}
    for result in advisor_results:
        for topic, offsets in _find_topics(result.answer).items():
            for offset in offsets:
                stance, phrase = _stance_at(result.answer, offset)
                if stance is None:
                    continue
                # First stance found per advisor per topic wins -- keeps
                # this deterministic and stops a later, unrelated mention
                # from silently overwriting an earlier blocking call-out.
                topic_stances.setdefault(topic, {}).setdefault(result.advisor_name, (stance, phrase))

    findings: list[ReviewFinding] = []
    for topic, stances_by_advisor in topic_stances.items():
        positive = [(a, p) for a, (s, p) in stances_by_advisor.items() if s == "positive"]
        blocking = [(a, p) for a, (s, p) in stances_by_advisor.items() if s == "blocking"]

        if positive and blocking:
            positive_advisor, positive_phrase = positive[0]
            blocking_advisor, blocking_phrase = blocking[0]
            topic_label = topic.replace("_", " ")
            findings.append(
                ReviewFinding(
                    finding_id=f"conflict-{topic}-{blocking_advisor}-{positive_advisor}",
                    category="conflict",
                    title=f"Conflicting guidance on {topic_label}",
                    description=(
                        f"{blocking_advisor} flagged a blocking concern on {topic_label} "
                        f'(matched phrase: "{blocking_phrase}"), while {positive_advisor} reported '
                        f'it as sufficient (matched phrase: "{positive_phrase}"). Both viewpoints are '
                        "preserved; this conflict is not silently resolved."
                    ),
                    severity="high",
                    recommendation="A human reviewer must reconcile these viewpoints before proceeding.",
                    blocking=True,
                    source_advisors=[blocking_advisor, positive_advisor],
                    status="open",
                )
            )

    return findings
