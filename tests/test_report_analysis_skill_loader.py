from pathlib import Path

import pytest

from agent.report.skill_loader import ReportAnalysisSkillLoader, SkillLoadError


SKILL_PATH = (
    Path(__file__).resolve().parents[1]
    / "agent"
    / "report"
    / "skills"
    / "report-analysis"
)


@pytest.mark.parametrize(
    ("test_type", "expected_reference"),
    (
        ("Jump Test", "references/jump.md"),
        ("Treadmill Gait Test", "references/gait.md"),
        ("Treadmill Running Test", "references/running.md"),
    ),
)
def test_initial_load_discloses_only_root_and_matching_domain(
    test_type, expected_reference
):
    loader = ReportAnalysisSkillLoader(SKILL_PATH)

    context = loader.load_initial(test_type)

    assert tuple(resource.resource_id for resource in context.resources) == (
        "SKILL.md",
        expected_reference,
    )
    assert context.loaded_reference_ids == (expected_reference,)
    assert len(context.content_digest) == 64
    assert context.content_digest == loader.load_initial(test_type).content_digest


def test_on_demand_reference_changes_context_without_reloading_domain():
    loader = ReportAnalysisSkillLoader(SKILL_PATH)
    initial = loader.load_initial("Jump Test")

    extended = loader.load_reference(
        initial, "references/evidence-guidelines.md"
    )

    assert initial.loaded_reference_ids == ("references/jump.md",)
    assert extended.loaded_reference_ids == (
        "references/jump.md",
        "references/evidence-guidelines.md",
    )
    assert extended.content_digest != initial.content_digest
    assert initial.content_digest == loader.load_initial("Jump Test").content_digest


@pytest.mark.parametrize(
    ("reference_id", "expected_code"),
    (
        ("references/gait.md", "unknown_skill_reference"),
        ("references/evidence-guidelines.md", "duplicate_skill_reference"),
    ),
)
def test_unknown_and_duplicate_on_demand_references_are_rejected(
    reference_id, expected_code
):
    loader = ReportAnalysisSkillLoader(SKILL_PATH)
    context = loader.load_initial("Jump Test")
    if expected_code == "duplicate_skill_reference":
        context = loader.load_reference(context, reference_id)

    with pytest.raises(SkillLoadError) as exc_info:
        loader.load_reference(context, reference_id)

    assert exc_info.value.code == expected_code


def test_missing_skill_root_fails_closed():
    loader = ReportAnalysisSkillLoader(SKILL_PATH / "missing")

    with pytest.raises(SkillLoadError) as exc_info:
        loader.load_initial("Jump Test")

    assert exc_info.value.code == "skill_resource_unavailable"
