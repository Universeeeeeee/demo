from knowledge.chunking import TextUnit, chunk_units, estimate_tokens
from knowledge.models import KnowledgeSource


def _source():
    return KnowledgeSource(
        source_id="s1",
        title="Source",
        url="https://example.org/source",
        download_url="https://example.org/source.xml",
        source_format="jats_xml",
        source_kind="journal_article",
        domains=("walk",),
        license="CC BY",
        ingest_policy="full_text",
    )


def test_chunking_is_deterministic_and_preserves_locators():
    units = tuple(
        TextUnit("Methods", f"Methods ¶{index}", f"Paragraph {index}. " * 20)
        for index in range(1, 5)
    )

    first = chunk_units(_source(), units, target_tokens=80, overlap_tokens=15)
    second = chunk_units(_source(), units, target_tokens=80, overlap_tokens=15)

    assert first == second
    assert all(chunk.locator.startswith("Methods ¶") for chunk in first)
    assert all(chunk.content_digest for chunk in first)
    assert len({chunk.chunk_id for chunk in first}) == len(first)


def test_token_estimate_counts_chinese_more_finely_than_whitespace_words():
    assert estimate_tokens("步态周期包含支撑相和摆动相") >= 10
    assert estimate_tokens("gait cycle") >= 2


def test_training_direction_is_only_enabled_for_evidence_bearing_sections():
    source = _source().model_copy(
        update={
            "support_types": ("training_direction", "limitation"),
            "recommendation_allowed": True,
        }
    )
    chunks = chunk_units(
        source,
        (
            TextUnit("Methods", "Methods ¶1", "Search strategy and inclusion criteria."),
            TextUnit("Results", "Results ¶1", "Training improved jump performance."),
        ),
        target_tokens=80,
        overlap_tokens=0,
    )

    methods = next(item for item in chunks if item.section == "Methods")
    results = next(item for item in chunks if item.section == "Results")
    assert "training_direction" not in methods.support_types
    assert methods.recommendation_allowed is False
    assert "training_direction" in results.support_types
    assert results.recommendation_allowed is True


def test_introduction_chunks_are_never_recommendation_evidence():
    source = _source().model_copy(update={"recommendation_allowed": True})
    chunks = chunk_units(
        source,
        (TextUnit("Introduction", "Introduction ¶1", "Prior work was limited."),),
        target_tokens=80,
        overlap_tokens=0,
    )
    assert chunks[0].recommendation_allowed is False
