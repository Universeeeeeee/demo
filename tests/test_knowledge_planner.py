from knowledge.models import KnowledgeSource, RecommendationClaim, ReportRAGContext
from knowledge.planner import QueryPlanner, SupportMatrix


def _source(*, support_types=("method",), allowed=True):
    return KnowledgeSource(
        source_id="source-1",
        title="Reviewed source",
        url="https://example.org/source",
        download_url="https://example.org/source.xml",
        source_format="jats_xml",
        source_kind="journal_article",
        domains=("jump",),
        metric_codes=("jump_height_m",),
        populations=("general",),
        support_types=support_types,
        recommendation_allowed=allowed,
        license="CC BY",
        ingest_policy="full_text",
    )


def _context():
    return ReportRAGContext(
        package_digest="a" * 64,
        test_type="Jump Test",
        metric_codes=("jump_height_m",),
        claims=(
            RecommendationClaim(
                claim_id="claim-1",
                text="跳跃高度存在可验证变化。",
                metric_codes=("jump_height_m",),
                limitations=("样本较少",),
            ),
        ),
        quality_codes=("small_sample",),
    )


def test_planner_is_deterministic_and_only_enables_reviewed_intents():
    planner = QueryPlanner(SupportMatrix((_source(),)))

    first = planner.plan(_context())
    second = planner.plan(_context())

    assert first == second
    assert [item.recommendation_intent for item in first] == [
        "measurement_review",
        "retest",
    ]
    assert all("a" * 64 not in item.query for item in first)


def test_training_query_requires_training_direction_source():
    planner = QueryPlanner(
        SupportMatrix((_source(support_types=("method", "training_direction")),))
    )
    intents = [item.recommendation_intent for item in planner.plan(_context())]
    assert "general_training_focus" in intents


def test_disabled_population_produces_no_query():
    context = _context().model_copy(update={"population": "clinical"})
    assert QueryPlanner(SupportMatrix((_source(),))).plan(context) == ()
