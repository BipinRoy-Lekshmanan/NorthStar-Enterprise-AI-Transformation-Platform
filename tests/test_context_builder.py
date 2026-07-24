from app.models.chunk import Chunk
from app.models.response import RetrievalResult
from app.rag.context_builder import ContextBuilder


def _result(chunk_id: str, text: str, score: float, **overrides) -> RetrievalResult:
    fields = dict(
        chunk_id=chunk_id,
        text=text,
        chunk_index=0,
        source_file="doc.md",
        source_path="doc.md",
        content_hash="hash",
        char_count=len(text),
    )
    fields.update(overrides)
    return RetrievalResult(chunk=Chunk(**fields), score=score, rank=1)


def _builder(**overrides) -> ContextBuilder:
    defaults = dict(
        max_characters=1000, max_chunks=5, min_score=0.0,
        insufficient_min_results=1, insufficient_min_score=0.0,
    )
    defaults.update(overrides)
    return ContextBuilder(**defaults)


def test_no_results_is_insufficient():
    result = _builder().build([])

    assert result.sufficient is False
    assert result.insufficiency_reason == "no_results"
    assert result.blocks == []


def test_below_insufficient_score_threshold_is_insufficient():
    results = [_result("a", "text", score=0.05)]
    result = _builder(insufficient_min_score=0.5).build(results)

    assert result.sufficient is False
    assert result.insufficiency_reason == "low_relevance"


def test_sufficient_results_produce_blocks_in_rank_order():
    results = [_result("a", "first", score=0.9), _result("b", "second", score=0.8)]

    result = _builder().build(results)

    assert result.sufficient is True
    assert [b.source_id for b in result.blocks] == ["S1", "S2"]
    assert [b.chunk.chunk_id for b in result.blocks] == ["a", "b"]


def test_source_ids_are_stable_and_sequential():
    results = [_result(str(i), f"text {i}", score=0.5) for i in range(4)]

    result = _builder(max_chunks=10).build(results)

    assert [b.source_id for b in result.blocks] == ["S1", "S2", "S3", "S4"]


def test_empty_content_excluded():
    results = [_result("a", "   ", score=0.9), _result("b", "real content", score=0.8)]

    result = _builder().build(results)

    assert [b.chunk.chunk_id for b in result.blocks] == ["b"]
    assert result.excluded_reasons.get("empty_content") == 1


def test_below_min_score_excluded_from_context():
    results = [_result("a", "good match", score=0.9), _result("b", "weak match", score=0.01)]

    result = _builder(min_score=0.1).build(results)

    assert [b.chunk.chunk_id for b in result.blocks] == ["a"]
    assert result.excluded_reasons.get("below_min_score") == 1


def test_near_duplicate_content_deduplicated():
    results = [
        _result("a", "  Sev1 incidents require an incident commander.  ", score=0.9),
        _result("b", "sev1 incidents require an incident commander.", score=0.85),
    ]

    result = _builder().build(results)

    assert len(result.blocks) == 1
    assert result.excluded_reasons.get("duplicate") == 1


def test_max_chunks_enforced():
    results = [_result(str(i), f"text {i}", score=0.9 - i * 0.01) for i in range(10)]

    result = _builder(max_chunks=3, max_characters=100000).build(results)

    assert len(result.blocks) == 3
    assert result.excluded_reasons.get("chunk_limit") == 7


def test_max_characters_enforced_and_stops_at_first_overflow():
    results = [_result("a", "x" * 600, score=0.9), _result("b", "y" * 600, score=0.8)]

    result = _builder(max_characters=1000, max_chunks=10).build(results)

    assert [b.chunk.chunk_id for b in result.blocks] == ["a"]
    assert result.total_characters == 600
    assert result.excluded_reasons.get("size_limit") == 1


def test_no_usable_context_after_filtering_is_insufficient():
    results = [_result("a", "   ", score=0.9)]

    result = _builder().build(results)

    assert result.sufficient is False
    assert result.insufficiency_reason == "no_usable_context"


def test_highest_score_reported_even_when_insufficient():
    results = [_result("a", "text", score=0.3)]

    result = _builder(insufficient_min_score=0.9).build(results)

    assert result.highest_score == 0.3
