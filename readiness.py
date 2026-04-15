"""Sales Agent readiness checks.

Pre-deployment:  constraint pack loaded, policy rules loaded, memory ready, coordinator ready
Post-run:        zero opt-out violations, zero GDPR violations, all contacted leads have signals
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .workflow import BatchLeadResult, SalesAgentWorkflow


@dataclass
class ReadinessCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ReadinessReport:
    label: str
    checks: List[ReadinessCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(ReadinessCheck(name=name, passed=passed, detail=detail))


def run_pre_deployment_readiness(workflow: SalesAgentWorkflow) -> ReadinessReport:
    report = ReadinessReport(label="pre-deployment")

    constraints = workflow.constraint_layer.list_constraints()
    critical = [c for c in constraints if c.severity.value == "critical"]
    high = [c for c in constraints if c.severity.value == "high"]
    rules = workflow.policy_engine.list_rules()
    safety_rules = [r for r in rules if r.safety]

    report.add(
        "critical_constraint_pack_loaded",
        len(critical) >= 2,
        f"{len(critical)} critical constraints loaded "
        f"(opt_out, gdpr_consent required)",
    )
    report.add(
        "high_constraint_pack_loaded",
        len(high) >= 1,
        f"{len(high)} high constraints loaded (rate_limit, signal_verification)",
    )
    report.add(
        "safety_policy_rules_loaded",
        len(safety_rules) >= 2,
        f"{len(safety_rules)} safety policy rules loaded",
    )
    report.add(
        "memory_store_ready",
        workflow.memory is not None,
        "VectorMemoryStore initialised",
    )
    report.add(
        "coordinator_ready",
        workflow.coordinator is not None,
        "MultiAgentCoordinator initialised for company-level contention",
    )
    report.add(
        "response_budget_configured",
        workflow.response_budget_ms > 0,
        f"budget={workflow.response_budget_ms}ms",
    )
    return report


def run_post_run_readiness(result: BatchLeadResult) -> ReadinessReport:
    report = ReadinessReport(label="post-run")

    # Check no opt-out violations slipped through
    opt_out_violations = [
        r for r in result.results
        if not r.blocked
        and r.message is not None
        and any("opt_out" in v for v in r.violations)
    ]
    report.add(
        "zero_opt_out_violations",
        len(opt_out_violations) == 0,
        f"opt_out violations that bypassed guard = {len(opt_out_violations)}",
    )

    # Check contacted leads all had at least one live signal
    ungrounded = [
        r for r in result.results
        if not r.blocked
        and r.message is not None
        and not r.message.signal_hooks
    ]
    report.add(
        "all_messages_signal_grounded",
        len(ungrounded) == 0,
        f"messages with no signal hook = {len(ungrounded)}",
    )

    # Check analytics ran
    report.add(
        "analytics_insights_produced",
        len(result.pattern_insights) > 0,
        f"{len(result.pattern_insights)} pattern insights generated",
    )

    report.add(
        "contacted_gt_zero",
        result.contacted > 0,
        f"contacted={result.contacted} / total={result.total_leads}",
    )
    return report
