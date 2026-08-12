"""Deterministic analysis-method tests for the Analysis Kernel."""

from agent.report.tools import AnalysisToolGateway
from reporting.models import (
    AnalysisNode,
    AnalysisQuestion,
    DataAccessScope,
    SmallAnalysisPlan,
)
from reporting.validators import PlanValidator
from tests.reporting_fixtures import make_jump_package, make_treadmill_package


def _run(package, analysis_method, metric_codes, **inputs):
    record_set_id = package.record_sets[0].record_set_id
    question = AnalysisQuestion(
        question_id="q1",
        description="synthetic question",
        dimensions=("temporal",),
        metric_codes=tuple(metric_codes),
        reason="synthetic pattern",
        stop_condition="deterministic evidence",
    )
    node = AnalysisNode(
        node_id="n1",
        tool_name="analyze_current_session",
        analysis_method=analysis_method,
        inputs={
            "record_set_id": record_set_id,
            "metric_codes": list(metric_codes),
            **inputs,
        },
        question_id="q1",
        purpose="verify synthetic pattern",
    )
    plan = SmallAnalysisPlan(questions=(question,), nodes=(node,))
    validated = PlanValidator().validate(plan, package, DataAccessScope())
    return AnalysisToolGateway().execute_plan(
        package, validated, DataAccessScope()
    )


def _predicate(bundle, name):
    return next(
        predicate
        for predicate in bundle.items[0].predicates
        if predicate.predicate == name
    )


def _run_quality(package):
    question = AnalysisQuestion(
        question_id="q1",
        description="quality",
        dimensions=("quality",),
        metric_codes=(),
        reason="quality",
        stop_condition="checked",
    )
    node = AnalysisNode(
        node_id="n1",
        tool_name="analyze_current_session",
        analysis_method="quality_scope_check",
        inputs={},
        question_id="q1",
        purpose="check quality scope",
    )
    plan = SmallAnalysisPlan(questions=(question,), nodes=(node,))
    validated = PlanValidator().validate(plan, package, DataAccessScope())
    return AnalysisToolGateway().execute_plan(
        package, validated, DataAccessScope()
    )


def test_temporal_change_supports_increase_and_persistence():
    package = make_jump_package(
        [0.20] * 3 + [0.22] * 3 + [0.24] * 3 + [0.26] * 3
    )

    bundle = _run(package, "verify_temporal_change", ["contact_time_s"])

    assert _predicate(bundle, "comparison_supported").supported is True
    assert _predicate(bundle, "increase").supported is True
    assert _predicate(bundle, "persistent").supported is True
    assert bundle.items[0].numeric_values["difference"] > 0


def test_temporal_change_marks_transient_without_calling_it_persistent():
    package = make_jump_package(
        [0.20] * 3 + [0.20] * 3 + [0.25] * 3 + [0.25] * 3
    )

    bundle = _run(package, "verify_temporal_change", ["contact_time_s"])

    assert _predicate(bundle, "increase").supported is True
    assert _predicate(bundle, "persistent").supported is False
    assert _predicate(bundle, "transient").supported is True


def test_temporal_comparison_is_unsupported_when_each_half_has_fewer_than_three_rows():
    package = make_jump_package([0.20, 0.21, 0.30, 0.31])

    bundle = _run(package, "verify_temporal_change", ["contact_time_s"])

    assert _predicate(bundle, "comparison_supported").supported is False
    assert _predicate(bundle, "increase").supported is False
    assert bundle.items[0].analysis_status == "inconclusive"
    assert "insufficient_sample_size" in bundle.items[0].limitations


def test_predicate_evidence_ids_are_stable_unique_audit_refs():
    package = make_jump_package([0.20] * 6 + [0.30] * 6)

    first = _run(package, "verify_temporal_change", ["contact_time_s"])
    second = _run(package, "verify_temporal_change", ["contact_time_s"])
    first_ids = tuple(
        predicate.predicate_evidence_id
        for predicate in first.items[0].predicates
    )
    second_ids = tuple(
        predicate.predicate_evidence_id
        for predicate in second.items[0].predicates
    )

    assert all(first_ids)
    assert len(first_ids) == len(set(first_ids))
    assert first_ids == second_ids


def test_side_change_can_be_concentrated_on_left():
    package = make_treadmill_package(
        [0.20] * 6 + [0.32] * 6,
        [0.20] * 6 + [0.22] * 6,
    )

    bundle = _run(
        package,
        "verify_side_segment_difference",
        ["contact_time_s"],
        target_side="left",
    )

    predicate = _predicate(bundle, "concentrated_on_side")
    assert predicate.supported is True
    assert predicate.details["target_side"] == "left"


def test_cross_metric_cochange_preserves_alignment_and_forbids_causal_interpretation():
    package = make_treadmill_package(
        [0.20] * 3 + [0.30] * 3,
        [0.20] * 3 + [0.30] * 3,
        [72.0] * 3 + [66.0] * 3,
        [72.0] * 3 + [66.0] * 3,
    )

    bundle = _run(
        package,
        "verify_cross_metric_cochange",
        ["contact_time_s", "step_length_cm"],
    )

    predicate = _predicate(bundle, "co_change")
    assert predicate.supported is True
    assert predicate.details["directions"] == {
        "contact_time_s": "increase",
        "step_length_cm": "decrease",
    }
    assert predicate.details["causal_interpretation_allowed"] is False
    assert "co_change_is_not_causation" in bundle.items[0].limitations


def test_exclusion_robustness_runs_multiple_primitives_as_one_agent_node():
    values = [0.20] * 6 + [0.30] * 6
    included = [True] * 12
    included[2] = False
    included[9] = False
    package = make_jump_package(values, included=included)

    bundle = _run(
        package,
        "verify_exclusion_robustness",
        ["contact_time_s"],
    )

    assert _predicate(bundle, "remains_after_exclusion").supported is True
    assert len(bundle.items) == 1
    assert len(bundle.tool_runs) == 1
    assert set(bundle.items[0].numeric_values) == {
        "all_difference",
        "included_difference",
    }


def test_kernel_output_digest_is_deterministic_for_same_package_plan():
    package = make_jump_package([0.20] * 6 + [0.30] * 6)

    first = _run(package, "verify_temporal_change", ["contact_time_s"])
    second = _run(package, "verify_temporal_change", ["contact_time_s"])

    assert first == second
    assert first.tool_runs[0].output_digest == second.tool_runs[0].output_digest


def test_quality_scope_check_keeps_its_semantic_digest():
    bundle = _run_quality(make_jump_package([0.20] * 12))

    assert bundle.tool_runs[0].output_digest == (
        "e6b8d57083e128104fe0933b138bf3870358f481001071fcb1bd730d58a36746"
    )


def test_migration_keeps_pre_v2_semantic_output_digests_byte_identical():
    cases = (
        (
            make_jump_package([0.20] * 3 + [0.22] * 3 + [0.24] * 3 + [0.26] * 3),
            "verify_temporal_change",
            ["contact_time_s"],
            {},
            "f983f850bc3dc211b3c0203eb1fc84f1c7d6e73958f28ce6d192827224ce84fc",
        ),
        (
            make_treadmill_package([0.20] * 6 + [0.32] * 6, [0.20] * 6 + [0.22] * 6),
            "verify_side_segment_difference",
            ["contact_time_s"],
            {"target_side": "left"},
            "278f9aa7f00932bac162e8b6d76044eb408ef3f57daf0b952b9a814660b02e02",
        ),
        (
            make_treadmill_package(
                [0.20] * 3 + [0.30] * 3,
                [0.20] * 3 + [0.30] * 3,
                [72.0] * 3 + [66.0] * 3,
                [72.0] * 3 + [66.0] * 3,
            ),
            "verify_cross_metric_cochange",
            ["contact_time_s", "step_length_cm"],
            {},
            "51fec2f96566206a1cadd74706e197475b71622e28d8927d810f38bc6dd25919",
        ),
        (
            make_jump_package(
                [0.20] * 6 + [0.30] * 6,
                included=(True, True, False, True, True, True, True, True, True, False, True, True),
            ),
            "verify_exclusion_robustness",
            ["contact_time_s"],
            {},
            "9ec2f73ad97071c495540e80d9df6b74221e02d0d0ff3e146b94a371dca1413c",
        ),
    )

    for package, method, metrics, inputs, expected in cases:
        run = _run(package, method, metrics, **inputs).tool_runs[0]
        assert run.output_digest == expected
        assert run.input_digest is not None


def test_tool_wrapper_version_does_not_change_output_digest():
    package = make_jump_package([0.20] * 6 + [0.30] * 6)
    bundle = _run(package, "verify_temporal_change", ["contact_time_s"])
    run = bundle.tool_runs[0]

    assert run.tool_version not in run.output_digest
    assert run.analysis_method_version not in run.output_digest
    assert run.kernel_version not in run.output_digest


def test_changing_evidence_value_changes_output_digest():
    first = _run(
        make_jump_package([0.20] * 6 + [0.30] * 6),
        "verify_temporal_change",
        ["contact_time_s"],
    )
    second = _run(
        make_jump_package([0.20] * 6 + [0.35] * 6),
        "verify_temporal_change",
        ["contact_time_s"],
    )

    assert first.tool_runs[0].output_digest != second.tool_runs[0].output_digest
