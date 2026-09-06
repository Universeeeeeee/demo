"""Run the non-CI Report Agent benchmark against fixed synthetic cases."""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.report.service import ReportAnalysisService  # noqa: E402
from agent.report.agent import ReportAgent  # noqa: E402
from agent.report.prompts import SEQUENTIAL_PROMPT_VERSION  # noqa: E402
from agent.report.skill_loader import (  # noqa: E402
    REPORT_ANALYSIS_SKILL_VERSION,
    ReportAnalysisSkillLoader,
)
from config.test_config import default_jump_config  # noqa: E402
from config.treadmill_config import TreadmillGaitConfig  # noqa: E402
from config.test_report import JumpTestReport  # noqa: E402
from data.subject_store import SubjectStore  # noqa: E402
from reporting.models import (  # noqa: E402
    DataAccessScope,
    NextAnalysisAction,
    StopAnalysis,
)
from reporting.kernel import (  # noqa: E402
    ANALYSIS_METHOD_REGISTRY_VERSION,
    KERNEL_VERSION,
)
from reporting.observation import (  # noqa: E402
    OBSERVATION_BUILDER_VERSION,
    ObservationBuilder,
)
from reporting.repository import ReportRepository  # noqa: E402
from reporting.tools import ANALYSIS_TOOL_REGISTRY_VERSION  # noqa: E402
from tests.reporting_fixtures import make_jump_report, make_treadmill_report  # noqa: E402


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    description: str
    report: Any
    expected_predicates: tuple[str, ...]
    cross_dimension: bool = False
    acceptable_initial_methods: tuple[str, ...] = ()
    varying_metric_codes: tuple[str, ...] = ()
    max_initial_nodes: int = 1
    allow_initial_stop: bool = False


@dataclass(frozen=True)
class AblationConfig:
    include_sketch: bool
    include_compact_series: bool
    include_screening_cues: bool
    max_replans: Literal[0, 1]


ABLATIONS = {
    "A": AblationConfig(False, False, False, 0),
    "B": AblationConfig(True, True, False, 0),
    "C": AblationConfig(True, True, True, 0),
    "D": AblationConfig(True, True, True, 1),
}


class TracedReportAgent(ReportAgent):
    """Capture model decisions for benchmark diagnosis without changing runtime behavior."""

    def __init__(self, *, skill_path: Path | None = None, test_type: str = ""):
        super().__init__()
        self.initial_decision = None
        self.evidence_review = None
        self.skill_audit = None
        self.sequential_decisions = []
        self.synthesis_trace = []

    def propose_plan(self, observation, state):
        decision = super().propose_plan(observation, state)
        self.initial_decision = decision
        return decision

    def review_evidence(self, observation, state, evidence):
        decision = super().review_evidence(observation, state, evidence)
        self.evidence_review = decision
        return decision

    def decide(self, observation, state, evidence, skill_context):
        decision = super().decide(
            observation, state, evidence, skill_context
        )
        if self.initial_decision is None:
            self.initial_decision = decision
        self.sequential_decisions.append(decision)
        self.skill_audit = {
            "skill_name": skill_context.skill_name,
            "skill_version": skill_context.skill_version,
            "loaded_references": skill_context.loaded_reference_ids,
            "content_digest": skill_context.content_digest,
        }
        return decision

    def synthesize_sequential(
        self, observation, state, evidence, skill_context
    ):
        draft = super().synthesize_sequential(
            observation, state, evidence, skill_context
        )
        self.synthesis_trace.append(
            {"stage": "initial", "draft": draft.model_dump(mode="json")}
        )
        return draft

    def repair_synthesis(
        self,
        observation,
        state,
        evidence,
        draft,
        error_code,
        error_message,
    ):
        repaired = super().repair_synthesis(
            observation,
            state,
            evidence,
            draft,
            error_code,
            error_message,
        )
        self.synthesis_trace.append(
            {
                "stage": "repair",
                "error_code": error_code,
                "draft": repaired.model_dump(mode="json"),
            }
        )
        return repaired

    def decision_trace(self) -> dict[str, Any]:
        return {
            "initial_decision": (
                self.initial_decision.model_dump(mode="json")
                if self.initial_decision is not None
                else None
            ),
            "evidence_review": (
                self.evidence_review.model_dump(mode="json")
                if self.evidence_review is not None
                else None
            ),
            "skill_audit": self.skill_audit,
            "sequential_decisions": [
                decision.model_dump(mode="json")
                for decision in self.sequential_decisions
            ],
            "synthesis_trace": self.synthesis_trace,
        }


def load_report_analysis_skill(
    skill_path: Path,
    test_type: str,
) -> tuple[str, dict[str, Any]]:
    context = ReportAnalysisSkillLoader(skill_path).load_initial(test_type)
    return context.instructions, {
        "skill_name": context.skill_name,
        "skill_version": context.skill_version,
        "loaded_references": context.loaded_reference_ids,
        "content_digest": context.content_digest,
    }


def grade_initial_decision(
    case: BenchmarkCase,
    decision,
) -> dict[str, bool]:
    if isinstance(decision, NextAnalysisAction):
        methods = (decision.analysis_method,)
        inputs = (decision.inputs,)
        initial_stop = False
    elif isinstance(decision, StopAnalysis):
        methods = ()
        inputs = ()
        initial_stop = True
    elif decision is not None and hasattr(decision, "plan"):
        nodes = decision.plan.nodes
        methods = tuple(node.analysis_method for node in nodes)
        inputs = tuple(node.inputs for node in nodes)
        initial_stop = not nodes
    else:
        methods = ()
        inputs = ()
        initial_stop = False
    first_method = methods[0] if methods else None
    acceptable_first_action = (
        (initial_stop and case.allow_initial_stop)
        or first_method in case.acceptable_initial_methods
    )
    cross_metric_uses_varying_inputs = all(
        method != "verify_cross_metric_cochange"
        or set(method_inputs.get("metric_codes", ())).issubset(
            case.varying_metric_codes
        )
        for method, method_inputs in zip(methods, inputs)
    )
    return {
        "bounded_initial_action": len(methods) <= case.max_initial_nodes,
        "acceptable_first_action": acceptable_first_action,
        "no_initial_exclusion_robustness": all(
            method != "verify_exclusion_robustness" for method in methods
        ),
        "cross_metric_inputs_show_change": cross_metric_uses_varying_inputs,
    }


def load_report_agent_cases() -> list[BenchmarkCase]:
    return [
        BenchmarkCase("temporal_increase", "单一后程增加", make_jump_report([0.20] * 6 + [0.30] * 6), ("increase",), acceptable_initial_methods=("verify_temporal_change",), varying_metric_codes=("contact_time_s",)),
        BenchmarkCase("side_change", "左右变化差异", make_treadmill_report([0.20] * 6 + [0.31] * 6, [0.20] * 6 + [0.22] * 6), ("concentrated_on_side",), True, ("verify_temporal_change", "verify_side_segment_difference"), ("contact_time_s",)),
        BenchmarkCase("left_late_change", "左侧差异只在后程出现", make_treadmill_report([0.20] * 6 + [0.32] * 6, [0.20] * 12), ("concentrated_on_side",), True, ("verify_temporal_change", "verify_side_segment_difference"), ("contact_time_s",)),
        BenchmarkCase("cross_metric", "触地时间增加且步长下降", make_treadmill_report([0.20] * 3 + [0.30] * 3, [0.20] * 3 + [0.30] * 3, [72.0] * 3 + [66.0] * 3, [72.0] * 3 + [66.0] * 3), ("co_change",), True, ("verify_temporal_change", "verify_cross_metric_cochange"), ("contact_time_s", "step_length_cm")),
        BenchmarkCase("right_stable_left_change", "右侧稳定左侧变化", make_treadmill_report([0.20] * 6 + [0.30] * 6, [0.22] * 12), ("concentrated_on_side",), True, ("verify_temporal_change", "verify_side_segment_difference"), ("contact_time_s",)),
        BenchmarkCase("single_outlier", "单个极值制造局部变化", make_jump_report([0.20] * 5 + [0.50] + [0.20] * 6), ("transient",), acceptable_initial_methods=("verify_temporal_change",), varying_metric_codes=("contact_time_s",)),
        BenchmarkCase("robust_after_exclusion", "排除后方向仍成立", make_jump_report([0.20] * 6 + [0.30] * 6, included=[True, True, False, True, True, True, True, True, True, False, True, True]), ("remains_after_exclusion",), True, ("verify_temporal_change",), ("contact_time_s",)),
        BenchmarkCase("reversal_after_exclusion", "排除后方向反转；当前方法无正向模式Predicate", make_jump_report([0.40, 0.40, 0.10, 0.40, 0.40, 0.10, 0.20, 0.20, 0.60, 0.20, 0.20, 0.60], included=[True, True, False, True, True, False, True, True, False, True, True, False]), (), True, ("verify_temporal_change",), ("contact_time_s",), allow_initial_stop=True),
        BenchmarkCase("same_mean_dispersion", "均值相同但离散程度不同；当前方法不验证离散程度", make_jump_report([0.20, 0.30] * 3 + [0.10, 0.40] * 3), (), acceptable_initial_methods=("verify_temporal_change",), varying_metric_codes=("contact_time_s",), allow_initial_stop=True),
        BenchmarkCase("insufficient_sample", "样本量不足", make_jump_report([0.20, 0.21, 0.30, 0.31]), (), False, ("verify_temporal_change",), ("contact_time_s",)),
        BenchmarkCase("quality_limited", "质量标记下仍可验证的时序变化", make_jump_report([0.20] * 6 + [0.30] * 6, included=[True] * 5 + [False] + [True] * 6), ("increase",), True, ("verify_temporal_change", "quality_scope_check"), ("contact_time_s",)),
        BenchmarkCase("replan_required", "初始假设被否定后需要Replan", make_treadmill_report([0.20] * 6, [0.20] * 6, [72.0] * 3 + [66.0] * 3, [72.0] * 3 + [66.0] * 3), ("decrease",), True, ("verify_temporal_change", "verify_cross_metric_cochange"), ("step_length_cm",)),
    ]


def run_report_agent_benchmark(
    cases: list[BenchmarkCase],
    repetitions: int,
    *,
    ablation: AblationConfig,
    skill_path: Path | None = None,
) -> dict[str, Any]:
    runs = []
    for case in cases:
        for repetition in range(repetitions):
            started = time.perf_counter()
            with tempfile.TemporaryDirectory() as directory:
                store = SubjectStore(Path(directory) / "benchmark.sqlite3")
                config = (
                    default_jump_config()
                    if isinstance(case.report, JumpTestReport)
                    else TreadmillGaitConfig(
                        stop_type="End of Time",
                        test_length="01:00",
                        treadmill_speed=5.0,
                        direction="Interface side",
                    )
                )
                agent = TracedReportAgent(
                    skill_path=skill_path,
                    test_type=config.test_type,
                )
                session_id = store.record_session(None, config, case.report)
                service = ReportAnalysisService(
                    ReportRepository(store),
                    agent=agent,
                    observation_builder=ObservationBuilder(
                        include_analysis_sketch=ablation.include_sketch,
                        include_compact_series=ablation.include_compact_series,
                        include_screening_cues=ablation.include_screening_cues,
                    ),
                    max_replans=ablation.max_replans,
                    skill_loader=(
                        None
                        if skill_path is None
                        else ReportAnalysisSkillLoader(skill_path)
                    ),
                )
                try:
                    analysis = service.analyze(session_id, DataAccessScope())
                    decision_assertions = grade_initial_decision(
                        case, agent.initial_decision
                    )
                    discovered = sorted(
                        {
                            binding.predicate
                            for claim in analysis.claims
                            for binding in claim.predicate_bindings
                        }
                    )
                    runs.append(
                        {
                            "case_id": case.case_id,
                            "repetition": repetition + 1,
                            "status": "validated",
                            "expected_predicates": case.expected_predicates,
                            "discovered_predicates": discovered,
                            "cycle_count": analysis.cycle_count,
                            "replan_count": analysis.replan_count,
                            "decision_trace": agent.decision_trace(),
                            "decision_assertions": decision_assertions,
                            "elapsed_ms": round((time.perf_counter() - started) * 1000),
                        }
                    )
                except Exception as exc:
                    runs.append(
                        {
                            "case_id": case.case_id,
                            "repetition": repetition + 1,
                            "status": "failed",
                            "error_code": getattr(exc, "code", "benchmark_failed"),
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            "decision_trace": agent.decision_trace(),
                            "decision_assertions": grade_initial_decision(
                                case, agent.initial_decision
                            ),
                            "elapsed_ms": round((time.perf_counter() - started) * 1000),
                        }
                    )
    expected_total = sum(
        len(case.expected_predicates) * repetitions for case in cases
    )
    matched = 0
    discovered_total = 0
    for run in runs:
        expected = set(run.get("expected_predicates", ()))
        discovered = set(run.get("discovered_predicates", ()))
        matched += len(expected & discovered)
        discovered_total += len(discovered)
    elapsed_values = sorted(run["elapsed_ms"] for run in runs)
    validated_count = sum(run["status"] == "validated" for run in runs)
    assertion_values = [
        passed
        for run in runs
        for passed in run["decision_assertions"].values()
    ]
    p50_index = len(elapsed_values) // 2
    p95_index = max(0, math.ceil(len(elapsed_values) * 0.95) - 1)
    return {
        "benchmark_schema_version": "report-agent-benchmark/2.0-sequential",
        "model_name": ReportAgent.model_name,
        "prompt_version": SEQUENTIAL_PROMPT_VERSION,
        "observation_builder_version": OBSERVATION_BUILDER_VERSION,
        "analysis_tool_registry_version": ANALYSIS_TOOL_REGISTRY_VERSION,
        "analysis_method_registry_version": ANALYSIS_METHOD_REGISTRY_VERSION,
        "kernel_version": KERNEL_VERSION,
        "skill": (
            None
            if skill_path is None
            else {
                "name": "report-analysis",
                "version": REPORT_ANALYSIS_SKILL_VERSION,
            }
        ),
        "ablation": asdict(ablation),
        "repetitions": repetitions,
        "case_count": len(cases),
        "release_sample_requirement_met": repetitions >= 3,
        "hidden_pattern_recall": matched / expected_total if expected_total else None,
        "hidden_pattern_precision": None,
        "precision_unavailable_reason": (
            "Benchmark cases define expected predicates but not the complete allowed "
            "predicate set; extra supported predicates cannot be classified as false positives"
        ),
        "legacy_raw_predicate_match_ratio": (
            matched / discovered_total if discovered_total else None
        ),
        "validated_run_rate": validated_count / len(runs) if runs else None,
        "decision_assertion_pass_rate": (
            sum(assertion_values) / len(assertion_values)
            if assertion_values
            else None
        ),
        "p50_elapsed_ms": elapsed_values[p50_index] if elapsed_values else None,
        "p95_elapsed_ms": elapsed_values[p95_index] if elapsed_values else None,
        "runs": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--ablation", choices=sorted(ABLATIONS), default="D")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skill-path", type=Path)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    cases = load_report_agent_cases()
    if args.case_ids:
        requested = set(args.case_ids)
        cases = [case for case in cases if case.case_id in requested]
        missing = requested - {case.case_id for case in cases}
        if missing:
            parser.error(f"unknown case IDs: {sorted(missing)}")
    result = run_report_agent_benchmark(
        cases,
        args.repetitions,
        ablation=ABLATIONS[args.ablation],
        skill_path=args.skill_path,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
