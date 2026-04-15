from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class SalesScenarioMetrics(BaseModel):
    personalization_coverage_rate: float = Field(..., ge=0, le=100)
    reply_rate: float = Field(..., ge=0, le=100)
    meetings_booked_rate: float = Field(..., ge=0, le=100)
    opt_out_violations: int = Field(..., ge=0)
    gdpr_consent_violations: int = Field(..., ge=0)
    weekly_frequency_violations: int = Field(..., ge=0)
    unverified_outreach_messages: int = Field(..., ge=0)


class SalesScenarioEvaluation(BaseModel):
    scenario: str
    passed: bool
    violations: List[str]
    metrics: SalesScenarioMetrics
    board_metric_zero_opt_out_violations: bool
    compliance_ready_audit_log: bool


def evaluate_autonomous_sales(metrics: SalesScenarioMetrics) -> SalesScenarioEvaluation:
    violations: List[str] = []

    if metrics.personalization_coverage_rate < 95:
        violations.append("Personalization coverage below 95%")
    if metrics.reply_rate < 12:
        violations.append("Reply rate below 12%")
    if metrics.meetings_booked_rate < 3:
        violations.append("Meetings booked rate below 3%")
    if metrics.opt_out_violations > 0:
        violations.append("Opt-out compliance violation detected")
    if metrics.gdpr_consent_violations > 0:
        violations.append("GDPR consent violation detected")
    if metrics.weekly_frequency_violations > 0:
        violations.append("Weekly contact frequency violation detected")
    if metrics.unverified_outreach_messages > 0:
        violations.append("Unverified outreach message detected")

    return SalesScenarioEvaluation(
        scenario="Autonomous Sales",
        passed=not violations,
        violations=violations,
        metrics=metrics,
        board_metric_zero_opt_out_violations=(metrics.opt_out_violations == 0),
        compliance_ready_audit_log=True,
    )