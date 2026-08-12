"""Deterministic validation boundaries for Agent-generated analysis plans."""

from __future__ import annotations

import hashlib
import json
import re

from .kernel import AnalysisMethodRegistry
from .models import (
    AnalysisNode,
    AnalysisQuestion,
    DraftAnalysisPackage,
    EvidenceBundle,
    DataAccessScope,
    LoadSkillResource,
    NextAnalysisAction,
    PredicateBinding,
    ReportDataPackage,
    SmallAnalysisPlan,
    StopAnalysis,
    ValidatedAnalysisClaim,
    ValidatedAnalysisAction,
    ValidatedAnalysisPackage,
    ValidatedNumericBinding,
    ValidatedAnalysisPlan,
)
from .tools import AnalysisToolRegistry


MAX_ANALYSIS_QUESTIONS_PER_CYCLE = 3
MAX_AGENT_LEVEL_NODES_PER_CYCLE = 3
MAX_PLAN_COST = 9


class PlanValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class PlanValidator:
    def __init__(
        self,
        tool_registry: AnalysisToolRegistry | None = None,
        method_registry: AnalysisMethodRegistry | None = None,
    ):
        self.tool_registry = tool_registry or AnalysisToolRegistry()
        self.method_registry = method_registry or AnalysisMethodRegistry()

    def validate(
        self,
        plan: SmallAnalysisPlan,
        package: ReportDataPackage,
        access_scope: DataAccessScope,
    ) -> ValidatedAnalysisPlan:
        if len(plan.questions) > MAX_ANALYSIS_QUESTIONS_PER_CYCLE:
            self._fail("too_many_questions", "at most three questions are allowed")
        if len(plan.nodes) > MAX_AGENT_LEVEL_NODES_PER_CYCLE:
            self._fail("too_many_nodes", "at most three Agent-level nodes are allowed")
        question_ids = [question.question_id for question in plan.questions]
        node_ids = [node.node_id for node in plan.nodes]
        if len(question_ids) != len(set(question_ids)):
            self._fail("duplicate_question_id", "question IDs must be unique")
        if len(node_ids) != len(set(node_ids)):
            self._fail("duplicate_node_id", "node IDs must be unique")
        question_id_set = set(question_ids)
        node_id_set = set(node_ids)
        record_sets = {item.record_set_id: item for item in package.record_sets}
        request_hashes: list[str] = []
        total_cost = 0
        for node in plan.nodes:
            if node.question_id not in question_id_set:
                self._fail("unknown_question", f"unknown question: {node.question_id}")
            if not node.purpose.strip():
                self._fail("missing_purpose", f"node {node.node_id} has no purpose")
            if any(dependency not in node_id_set for dependency in node.dependencies):
                self._fail("unknown_dependency", f"node {node.node_id} has an unknown dependency")
            try:
                tool = self.tool_registry.get(node.tool_name)
            except KeyError as exc:
                raise PlanValidationError("unknown_tool", str(exc)) from exc
            if not tool.enabled:
                self._fail("tool_disabled", f"analysis tool {node.tool_name} is disabled")
            if not bool(getattr(access_scope, tool.required_scope)):
                self._fail(
                    "scope_not_authorized",
                    f"data scope {tool.required_scope} is not authorized",
                )
            try:
                method = self.method_registry.get(node.analysis_method)
            except KeyError as exc:
                raise PlanValidationError("unknown_analysis_method", str(exc)) from exc
            if method.tool_name != node.tool_name or node.analysis_method not in tool.method_names:
                self._fail(
                    "method_tool_mismatch",
                    f"analysis method {node.analysis_method} does not belong to {node.tool_name}",
                )
            self._validate_inputs(node, method, record_sets)
            request_hash = self._request_hash(node)
            if request_hash in request_hashes:
                self._fail("duplicate_request", "duplicate semantic requests are not allowed")
            request_hashes.append(request_hash)
            total_cost += method.cost
        if total_cost > MAX_PLAN_COST:
            self._fail("cost_budget_exceeded", "plan cost exceeds the cycle budget")
        execution_order = self._topological_order(plan)
        return ValidatedAnalysisPlan(
            plan=plan,
            execution_order=execution_order,
            request_hashes=tuple(request_hashes),
            total_cost=total_cost,
        )

    def _validate_inputs(self, node, spec, record_sets):
        allowed_keys = {
            "verify_temporal_change": {"record_set_id", "metric_codes", "side"},
            "verify_side_segment_difference": {"record_set_id", "metric_codes", "target_side"},
            "verify_cross_metric_cochange": {"record_set_id", "metric_codes", "side"},
            "verify_exclusion_robustness": {"record_set_id", "metric_codes", "side"},
            "quality_scope_check": set(),
        }[node.analysis_method]
        unknown_keys = set(node.inputs) - allowed_keys
        if unknown_keys:
            self._fail(
                "unknown_analysis_method_input",
                f"unknown inputs for {node.analysis_method}: {sorted(unknown_keys)}",
            )
        if not spec.requires_record_set:
            if node.inputs:
                self._fail("unexpected_inputs", "quality_scope_check accepts no inputs")
            return
        record_set_id = node.inputs.get("record_set_id")
        if record_set_id not in record_sets:
            self._fail("unknown_record_set", f"unknown RecordSet: {record_set_id}")
        metric_codes = node.inputs.get("metric_codes")
        if not isinstance(metric_codes, (list, tuple)):
            self._fail("invalid_metric_codes", "metric_codes must be a list")
        if not spec.min_metrics <= len(metric_codes) <= spec.max_metrics:
            self._fail("invalid_metric_count", "analysis method metric count is invalid")
        if len(metric_codes) != len(set(metric_codes)):
            self._fail("duplicate_metric", "metric_codes must be unique")
        record_set = record_sets[record_set_id]
        for metric_code in metric_codes:
            if metric_code not in record_set.metric_codes:
                self._fail(
                    "metric_not_in_record_set",
                    f"metric {metric_code} is not available in {record_set_id}",
                )
        side = node.inputs.get("side")
        target_side = node.inputs.get("target_side")
        if side is not None and side not in {"left", "right"}:
            self._fail("invalid_side", "side must be left or right")
        if target_side is not None and target_side not in {"left", "right"}:
            self._fail("invalid_side", "target_side must be left or right")
        if spec.requires_side:
            available_sides = {record.side for record in record_set.records}
            if not {"left", "right"}.issubset(available_sides):
                self._fail("side_dimension_unavailable", "both sides are required")

    def _topological_order(self, plan: SmallAnalysisPlan) -> tuple[str, ...]:
        dependencies = {
            node.node_id: set(node.dependencies) for node in plan.nodes
        }
        order: list[str] = []
        while dependencies:
            ready = sorted(
                node_id
                for node_id, required in dependencies.items()
                if not required
            )
            if not ready:
                self._fail("cyclic_dependencies", "analysis node dependencies are cyclic")
            for node_id in ready:
                order.append(node_id)
                dependencies.pop(node_id)
            for required in dependencies.values():
                required.difference_update(ready)
        return tuple(order)

    def _request_hash(self, node) -> str:
        payload = {
            "tool": node.tool_name,
            "method": node.analysis_method,
            "inputs": node.inputs,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _fail(self, code: str, message: str):
        raise PlanValidationError(code, message)


class ActionValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ActionValidator:
    """Validate one sequential decision while reusing the existing plan boundary."""

    def __init__(
        self,
        tool_registry: AnalysisToolRegistry | None = None,
        method_registry: AnalysisMethodRegistry | None = None,
        *,
        available_skill_references: tuple[str, ...] = (
            "references/evidence-guidelines.md",
        ),
    ):
        self.tool_registry = tool_registry or AnalysisToolRegistry()
        self.method_registry = method_registry or AnalysisMethodRegistry()
        self.plan_validator = PlanValidator(
            self.tool_registry,
            self.method_registry,
        )
        self.available_skill_references = frozenset(available_skill_references)

    def validate_decision(
        self,
        decision: NextAnalysisAction | LoadSkillResource | StopAnalysis,
        package: ReportDataPackage,
        access_scope: DataAccessScope,
        *,
        seen_request_hashes: frozenset[str] = frozenset(),
        loaded_skill_references: frozenset[str] = frozenset(),
        remaining_tool_calls: int = 1,
        remaining_skill_reference_loads: int = 1,
    ) -> ValidatedAnalysisAction | LoadSkillResource | StopAnalysis:
        if isinstance(decision, NextAnalysisAction):
            return self.validate_action(
                decision,
                package,
                access_scope,
                seen_request_hashes=seen_request_hashes,
                remaining_tool_calls=remaining_tool_calls,
            )
        if isinstance(decision, LoadSkillResource):
            return self.validate_skill_resource(
                decision,
                loaded_skill_references=loaded_skill_references,
                remaining_skill_reference_loads=remaining_skill_reference_loads,
            )
        return decision

    def validate_action(
        self,
        action: NextAnalysisAction,
        package: ReportDataPackage,
        access_scope: DataAccessScope,
        *,
        seen_request_hashes: frozenset[str] = frozenset(),
        remaining_tool_calls: int = 1,
    ) -> ValidatedAnalysisAction:
        if remaining_tool_calls <= 0:
            self._fail("tool_budget_exhausted", "no analysis Tool calls remain")
        input_metric_codes = tuple(action.inputs.get("metric_codes", ()))
        if input_metric_codes != action.hypothesis.metric_codes:
            self._fail(
                "hypothesis_metric_mismatch",
                "hypothesis metric_codes must match the analysis action inputs",
            )
        try:
            method = self.method_registry.get(action.analysis_method)
        except KeyError as exc:
            raise ActionValidationError("unknown_analysis_method", str(exc)) from exc
        if action.hypothesis.target_predicate not in method.predicate_names:
            self._fail(
                "predicate_method_mismatch",
                "target Predicate is not produced by the selected analysis method",
            )
        question = AnalysisQuestion(
            question_id=action.hypothesis.hypothesis_id,
            description=action.hypothesis.statement,
            dimensions=action.hypothesis.dimensions,
            metric_codes=action.hypothesis.metric_codes,
            reason=action.hypothesis.reason,
            stop_condition=action.hypothesis.success_condition,
        )
        node = AnalysisNode(
            node_id=action.action_id,
            tool_name=action.tool_name,
            analysis_method=action.analysis_method,
            inputs=action.inputs,
            question_id=action.hypothesis.hypothesis_id,
            purpose=action.purpose,
        )
        try:
            validated = self.plan_validator.validate(
                SmallAnalysisPlan(questions=(question,), nodes=(node,)),
                package,
                access_scope,
            )
        except PlanValidationError as exc:
            raise ActionValidationError(exc.code, str(exc)) from exc
        request_hash = validated.request_hashes[0]
        if request_hash in seen_request_hashes:
            self._fail(
                "duplicate_action_request",
                "the semantic analysis request has already been executed",
            )
        tool = self.tool_registry.get(action.tool_name)
        return ValidatedAnalysisAction(
            action=action,
            question=question,
            node=node,
            required_scope=tool.required_scope,
            request_hash=request_hash,
            cost=validated.total_cost,
        )

    def validate_skill_resource(
        self,
        decision: LoadSkillResource,
        *,
        loaded_skill_references: frozenset[str] = frozenset(),
        remaining_skill_reference_loads: int = 1,
    ) -> LoadSkillResource:
        if remaining_skill_reference_loads <= 0:
            self._fail(
                "skill_reference_budget_exhausted",
                "no Skill reference loads remain",
            )
        if decision.reference_id not in self.available_skill_references:
            self._fail(
                "unknown_skill_reference",
                f"Skill reference is not available: {decision.reference_id}",
            )
        if decision.reference_id in loaded_skill_references:
            self._fail(
                "duplicate_skill_reference",
                f"Skill reference is already loaded: {decision.reference_id}",
            )
        return decision

    def _fail(self, code: str, message: str):
        raise ActionValidationError(code, message)


class ClaimValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ClaimValidator:
    _FORBIDDEN_TERMS = (
        "导致",
        "引起",
        "证明了",
        "受伤风险",
        "伤病风险",
        "诊断",
        "治疗",
        "训练处方",
        "causes",
        "diagnosis",
        "injury risk",
    )

    def validate(
        self,
        draft: DraftAnalysisPackage,
        package: ReportDataPackage,
        evidence: tuple[EvidenceBundle, ...],
        access_scope: DataAccessScope,
    ) -> ValidatedAnalysisPackage:
        fact_map = {fact.fact_id: fact for fact in package.scalar_facts}
        evidence_map = {}
        predicate_evidence_map = {}
        run_map = {}
        for bundle in evidence:
            if bundle.package_id != package.metadata.package_id or bundle.package_digest != package.metadata.package_digest:
                self._fail("snapshot_mismatch", "evidence belongs to another report snapshot")
            evidence_map.update({item.evidence_id: item for item in bundle.items})
            run_map.update({run.tool_run_id: run for run in bundle.tool_runs})
            for item in bundle.items:
                for predicate in item.predicates:
                    if not predicate.predicate_evidence_id:
                        self._fail(
                            "missing_predicate_evidence_id",
                            f"Evidence {item.evidence_id} has an unaddressable predicate",
                        )
                    if predicate.predicate_evidence_id in predicate_evidence_map:
                        self._fail(
                            "duplicate_predicate_evidence_id",
                            f"duplicate Predicate Evidence ID: {predicate.predicate_evidence_id}",
                        )
                    predicate_evidence_map[predicate.predicate_evidence_id] = (
                        item,
                        predicate,
                    )
        validated_claims = []
        claim_ids: set[str] = set()
        for claim in draft.claims:
            if claim.claim_id in claim_ids:
                self._fail("duplicate_claim_id", f"duplicate claim ID: {claim.claim_id}")
            claim_ids.add(claim.claim_id)
            self._validate_language(claim.text_template)
            referenced_facts = self._resolve_refs(claim.fact_refs, fact_map, "unknown_fact")
            referenced_evidence = self._resolve_refs(claim.evidence_refs, evidence_map, "unknown_evidence")
            referenced_runs = self._resolve_refs(claim.tool_run_ids, run_map, "unknown_tool_run")
            for fact in referenced_facts:
                if fact.state != "present":
                    self._fail("missing_fact", f"claim references missing fact {fact.fact_id}")
            for run in referenced_runs:
                if not bool(getattr(access_scope, run.data_scope)):
                    self._fail("scope_not_authorized", f"tool run used unauthorized scope {run.data_scope}")
            if claim.claim_type == "descriptive":
                if not claim.fact_refs:
                    self._fail("descriptive_claim_without_fact", "descriptive claims require a Fact")
            else:
                if not claim.evidence_refs or not claim.tool_run_ids or not claim.predicate_bindings:
                    self._fail("derived_claim_without_evidence", "derived claims require Evidence, Tool Run and Predicate")
            if claim.claim_type == "synthesis" and len(set(claim.evidence_refs)) < 2:
                self._fail("synthesis_requires_multiple_evidence", "synthesis claims require at least two Evidence items")
            for item in referenced_evidence:
                if item.tool_run_id not in claim.tool_run_ids:
                    self._fail("evidence_tool_run_unbound", f"Evidence {item.evidence_id} is not bound to its Tool Run")
            self._validate_predicates(
                claim.predicate_bindings,
                predicate_evidence_map,
                set(claim.evidence_refs),
            )
            numeric_bindings = self._validate_numeric_bindings(
                claim.numeric_bindings,
                fact_map,
                evidence_map,
            )
            placeholders = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", claim.text_template))
            binding_ids = {binding.binding_id for binding in numeric_bindings}
            if placeholders != binding_ids:
                self._fail("numeric_placeholder_mismatch", "numeric placeholders must exactly match NumericBindings")
            text_without_placeholders = re.sub(r"\{[A-Za-z_][A-Za-z0-9_]*\}", "", claim.text_template)
            if re.search(r"\d", text_without_placeholders):
                self._fail("unbound_numeric_literal", "Claim text contains an unbound numeric literal")
            validated_claims.append(
                ValidatedAnalysisClaim(
                    claim_id=claim.claim_id,
                    claim_type=claim.claim_type,
                    text_template=claim.text_template,
                    fact_refs=claim.fact_refs,
                    evidence_refs=claim.evidence_refs,
                    tool_run_ids=claim.tool_run_ids,
                    predicate_bindings=claim.predicate_bindings,
                    numeric_bindings=tuple(numeric_bindings),
                    limitations=tuple(
                        dict.fromkeys(
                            (*claim.limitations, *(limitation for item in referenced_evidence for limitation in item.limitations))
                        )
                    ),
                )
            )
        return ValidatedAnalysisPackage(
            summary="基于本次测试记录的受限证据分析。",
            claims=tuple(validated_claims),
            scope_expansion_suggestions=draft.scope_expansion_suggestions,
            overall_limitations=draft.overall_limitations,
        )

    def _validate_language(self, text: str):
        lowered = text.lower()
        for term in self._FORBIDDEN_TERMS:
            if term.lower() in lowered:
                self._fail("forbidden_claim_language", f"forbidden term in claim: {term}")

    def _resolve_refs(self, refs, mapping, code):
        result = []
        for ref in refs:
            if ref not in mapping:
                self._fail(code, f"unknown reference: {ref}")
            result.append(mapping[ref])
        return result

    def _validate_predicates(
        self,
        bindings: tuple[PredicateBinding, ...],
        predicate_evidence_map,
        claim_evidence_refs: set[str],
    ):
        for binding in bindings:
            resolved = predicate_evidence_map.get(
                binding.predicate_evidence_ref
            )
            if resolved is None:
                self._fail(
                    "unknown_predicate_evidence",
                    "unknown Predicate Evidence: "
                    f"{binding.predicate_evidence_ref}",
                )
            item, predicate = resolved
            if item.evidence_id not in claim_evidence_refs:
                self._fail(
                    "predicate_evidence_unbound",
                    f"Predicate Evidence belongs to unreferenced Evidence {item.evidence_id}",
                )
            if predicate.predicate != binding.predicate:
                self._fail(
                    "predicate_binding_mismatch",
                    "Predicate Binding name does not match the exact "
                    "Predicate Evidence",
                )
            if item.analysis_status != "conclusive" or not predicate.supported:
                self._fail("unsupported_predicate", f"predicate is not supported: {binding.predicate}")

    def _validate_numeric_bindings(self, bindings, fact_map, evidence_map):
        validated = []
        ids: set[str] = set()
        for binding in bindings:
            if binding.binding_id in ids:
                self._fail("duplicate_numeric_binding", f"duplicate binding: {binding.binding_id}")
            ids.add(binding.binding_id)
            if binding.source_type == "fact":
                fact = fact_map.get(binding.source_ref)
                if fact is None or fact.state != "present" or fact.value is None:
                    self._fail("invalid_numeric_fact", f"invalid numeric Fact: {binding.source_ref}")
                if binding.value_key is not None:
                    self._fail("unexpected_value_key", "Fact bindings cannot specify value_key")
                value = fact.value
                unit = fact.unit
            else:
                item = evidence_map.get(binding.source_ref)
                if item is None or binding.value_key is None:
                    self._fail("invalid_numeric_evidence", f"invalid numeric Evidence: {binding.source_ref}")
                if binding.value_key not in item.numeric_values or binding.value_key not in item.numeric_units:
                    self._fail("unknown_numeric_value", f"unknown evidence numeric value: {binding.value_key}")
                value = item.numeric_values[binding.value_key]
                unit = item.numeric_units[binding.value_key]
            validated.append(
                ValidatedNumericBinding(
                    binding_id=binding.binding_id,
                    value=value,
                    unit=unit,
                    source_ref=binding.source_ref,
                )
            )
        return validated

    def _fail(self, code: str, message: str):
        raise ClaimValidationError(code, message)
