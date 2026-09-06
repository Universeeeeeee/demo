from knowledge.models import (
    DraftRecommendation,
    DraftRecommendationPackage,
    KnowledgeSource,
    LiteratureEvidence,
    RecommendationClaim,
    ReportRAGContext,
)
from knowledge.recommendations import RecommendationValidator


def _source():
    return KnowledgeSource(
        source_id="s1",
        title="Paper",
        url="https://example.org/paper",
        download_url="https://example.org/paper.xml",
        source_format="jats_xml",
        source_kind="journal_article",
        domains=("jump",),
        metric_codes=("jump_height_m",),
        populations=("general",),
        support_types=("method",),
        recommendation_allowed=True,
        doi="10.1/example",
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
                text="跳跃高度后段较低。",
                metric_codes=("jump_height_m",),
            ),
        ),
    )


def _evidence(*, allowed=True):
    return LiteratureEvidence(
        evidence_id="evidence-1",
        query_id="query-1",
        chunk_id="chunk-1",
        document_id="s1",
        source_id="s1",
        domain="jump",
        metric_codes=("jump_height_m",),
        populations=("general",),
        support_types=("method",),
        recommendation_allowed=allowed,
        locator="Methods ¶1",
        excerpt="Standardize take-off and landing technique when reviewing flight-time results.",
        content_digest="b" * 64,
        score=0.03,
    )


def _draft(text="建议复核起跳和落地动作的一致性。", evidence_refs=("evidence-1",)):
    return DraftRecommendationPackage(
        recommendations=(
            DraftRecommendation(
                recommendation_id="rec-1",
                category="measurement_review",
                text=text,
                claim_refs=("claim-1",),
                evidence_refs=evidence_refs,
            ),
        )
    )


def test_validator_builds_citation_from_catalog_not_model_text():
    package, audit = RecommendationValidator((_source(),)).validate(
        _draft(), _context(), (_evidence(),)
    )
    assert len(package.recommendations) == 1
    assert package.citations[0].evidence_id == "evidence-1"
    assert package.citations[0].url == "https://example.org/paper"
    assert package.recommendations[0].citation_refs == (
        package.citations[0].citation_id,
    )
    assert audit[0].accepted


def test_no_evidence_or_forbidden_dosage_is_deleted_without_retry():
    validator = RecommendationValidator((_source(),))
    missing, missing_audit = validator.validate(
        _draft(evidence_refs=()), _context(), (_evidence(),)
    )
    dosage, dosage_audit = validator.validate(
        _draft(text="每周3次，每次做4组。"), _context(), (_evidence(),)
    )
    assert missing.recommendations == ()
    assert missing_audit[0].reason == "invalid_evidence_reference"
    assert dosage.recommendations == ()
    assert dosage_audit[0].reason == "forbidden_recommendation_content"


def test_url_doi_markdown_and_citation_tokens_are_deleted():
    validator = RecommendationValidator((_source(),))
    cases = (
        "详情见 https://fake.example/paper。",
        "详情见 DOI:10.9999/fake。",
        "详情见 [论文](https://fake.example/paper)。",
        "详情见 [7]。",
        "See Citation 7.",
    )

    for text in cases:
        package, audit = validator.validate(
            _draft(text=text), _context(), (_evidence(),)
        )
        assert package.recommendations == ()
        assert audit[0].reason == "forbidden_citation_surface"
