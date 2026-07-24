import pytest

from app.agents.base_agent import Advisor
from app.agents.registry import (
    ADVISOR_REGISTRY,
    UnknownAdvisorError,
    get_advisor,
    list_advisors,
)
from app.config.prompt_config import GROUNDING_GUARDRAILS, SYSTEM_PROMPT, build_system_prompt

EXPECTED_ADVISOR_IDS = {
    "architecture",
    "ai-engineering",
    "devsecops",
    "testing",
    "security",
    "platform-engineering",
    "incident-management",
    "executive-ai-transformation",
}

FILTERED_ADVISOR_IDS = {
    "architecture": "NLC-ENG-002",
    "ai-engineering": "NLC-ENG-003",
    "devsecops": "NLC-ENG-004",
    "testing": "NLC-ENG-005",
    "platform-engineering": "NLC-ENG-008",
    "incident-management": "NLC-ENG-007",
}

UNFILTERED_ADVISOR_IDS = {"security", "executive-ai-transformation"}


# -- prompt composition ------------------------------------------------------------------


def test_generic_system_prompt_is_unchanged_by_the_advisor_refactor():
    # This is the regression check for Milestone 4's core promise: the
    # plain (non-advisor) assistant behaves byte-for-byte as it did in
    # Milestone 3.
    assert "Ground rules:" in SYSTEM_PROMPT
    assert GROUNDING_GUARDRAILS in SYSTEM_PROMPT
    assert "Northstar Enterprise Knowledge Assistant" in SYSTEM_PROMPT


def test_build_system_prompt_includes_persona_guardrails_and_structure():
    prompt = build_system_prompt("MY PERSONA TEXT", "MY STRUCTURE TEXT")

    assert "MY PERSONA TEXT" in prompt
    assert GROUNDING_GUARDRAILS in prompt
    assert "MY STRUCTURE TEXT" in prompt
    # persona must come before guardrails, guardrails before structure
    assert prompt.index("MY PERSONA TEXT") < prompt.index(GROUNDING_GUARDRAILS)
    assert prompt.index(GROUNDING_GUARDRAILS) < prompt.index("MY STRUCTURE TEXT")


def test_build_system_prompt_includes_extra_guidance_when_given():
    prompt = build_system_prompt("persona", "structure", extra_guidance="EXTRA DOMAIN GUIDANCE")

    assert "EXTRA DOMAIN GUIDANCE" in prompt
    assert prompt.index(GROUNDING_GUARDRAILS) < prompt.index("EXTRA DOMAIN GUIDANCE")
    assert prompt.index("EXTRA DOMAIN GUIDANCE") < prompt.index("structure")


def test_build_system_prompt_omits_extra_guidance_when_not_given():
    prompt = build_system_prompt("persona", "structure")
    assert prompt.count("\n\n\n") == 0  # no stray blank section left behind


# -- registry -----------------------------------------------------------------------------


def test_registry_has_exactly_the_eight_expected_advisors():
    assert set(ADVISOR_REGISTRY.keys()) == EXPECTED_ADVISOR_IDS
    assert len(list_advisors()) == 8


def test_get_advisor_returns_matching_advisor():
    advisor = get_advisor("testing")
    assert advisor.advisor_id == "testing"
    assert advisor.display_name == "Testing Advisor"


def test_get_advisor_raises_for_unknown_id():
    with pytest.raises(UnknownAdvisorError, match="Unknown advisor"):
        get_advisor("does-not-exist")


def test_list_advisors_returns_advisor_instances():
    for advisor in list_advisors():
        assert isinstance(advisor, Advisor)


# -- per-advisor structural checks (parametrized over the real registry) ------------------


@pytest.mark.parametrize("advisor_id", sorted(EXPECTED_ADVISOR_IDS))
def test_advisor_has_non_empty_persona_and_structure(advisor_id):
    advisor = get_advisor(advisor_id)
    assert advisor.persona.strip()
    assert advisor.structure_guidance.strip()
    assert advisor.description.strip()
    assert advisor.display_name.strip()


@pytest.mark.parametrize("advisor_id", sorted(EXPECTED_ADVISOR_IDS))
def test_advisor_system_prompt_always_includes_shared_guardrails(advisor_id):
    advisor = get_advisor(advisor_id)
    assert GROUNDING_GUARDRAILS in advisor.system_prompt
    assert advisor.persona in advisor.system_prompt
    assert advisor.structure_guidance in advisor.system_prompt


@pytest.mark.parametrize("advisor_id", sorted(EXPECTED_ADVISOR_IDS))
def test_advisor_prompt_version_is_tagged_with_advisor_id(advisor_id):
    advisor = get_advisor(advisor_id)
    assert advisor.prompt_version.endswith(f"+{advisor_id}-v1")


@pytest.mark.parametrize("advisor_id,expected_document_id", sorted(FILTERED_ADVISOR_IDS.items()))
def test_filtered_advisors_default_to_their_primary_document(advisor_id, expected_document_id):
    advisor = get_advisor(advisor_id)
    assert advisor.default_filters == {"document_id": expected_document_id}


@pytest.mark.parametrize("advisor_id", sorted(UNFILTERED_ADVISOR_IDS))
def test_cross_cutting_advisors_have_no_default_filter(advisor_id):
    advisor = get_advisor(advisor_id)
    assert advisor.default_filters == {}


def test_every_advisor_id_is_unique_and_matches_its_own_key():
    for key, advisor in ADVISOR_REGISTRY.items():
        assert advisor.advisor_id == key


# -- Advisor.ask() delegation + filter merging (isolated from RagService) -----------------


class _RecordingService:
    """Stand-in for RagService that just records the kwargs it was called with."""

    def __init__(self):
        self.calls: list[dict] = []

    def ask(self, question, **kwargs):
        self.calls.append({"question": question, **kwargs})
        return "SENTINEL_ANSWER"


def test_advisor_ask_delegates_to_service_with_composed_prompt():
    advisor = get_advisor("testing")
    service = _RecordingService()

    result = advisor.ask(service, "What is required?")

    assert result == "SENTINEL_ANSWER"
    assert len(service.calls) == 1
    call = service.calls[0]
    assert call["question"] == "What is required?"
    assert call["system_prompt"] == advisor.system_prompt
    assert call["prompt_version"] == advisor.prompt_version
    assert call["filters"] == {"document_id": "NLC-ENG-005"}


def test_advisor_ask_merges_default_filters_with_caller_filters():
    advisor = get_advisor("testing")  # default_filters = {"document_id": "NLC-ENG-005"}
    service = _RecordingService()

    advisor.ask(service, "q", filters={"source_file": "14_Testing_Strategy.md"})

    merged = service.calls[0]["filters"]
    assert merged == {"document_id": "NLC-ENG-005", "source_file": "14_Testing_Strategy.md"}


def test_advisor_ask_caller_filter_overrides_default_on_same_key():
    advisor = get_advisor("testing")
    service = _RecordingService()

    advisor.ask(service, "q", filters={"document_id": "NLC-ENG-999"})

    assert service.calls[0]["filters"] == {"document_id": "NLC-ENG-999"}


def test_advisor_ask_with_no_default_filter_passes_caller_filters_through():
    advisor = get_advisor("security")  # default_filters = {}
    service = _RecordingService()

    advisor.ask(service, "q", filters={"source_file": "13_DevSecOps_Standards.md"})

    assert service.calls[0]["filters"] == {"source_file": "13_DevSecOps_Standards.md"}


def test_advisor_ask_passes_through_top_k_and_hooks():
    advisor = get_advisor("architecture")
    service = _RecordingService()
    context_hook = lambda r: None  # noqa: E731
    prompt_hook = lambda p: None  # noqa: E731

    advisor.ask(service, "q", top_k=3, on_context_built=context_hook, on_prompt_built=prompt_hook)

    call = service.calls[0]
    assert call["top_k"] == 3
    assert call["on_context_built"] is context_hook
    assert call["on_prompt_built"] is prompt_hook
