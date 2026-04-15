"""Autonomous Sales Agent domain runtime.

Registers four safety constraints that every outreach message must pass:

  CRITICAL  sales.opt_out_respected       – blocked if prospect has opted out
  CRITICAL  sales.gdpr_consent_required   – blocked if B2C EU prospect without consent
  HIGH      sales.rate_limit_weekly       – blocked if >= 3 touches in 7 days
  HIGH      sales.no_unverified_outreach  – blocked if zero live signals found

These constraints are immutable and cannot be removed at runtime.
"""

from __future__ import annotations

import logging

from core.constraints import (
    Constraint,
    ConstraintLayer,
    ConstraintSeverity,
    ConstraintType,
)
from core.planner.behavior_tree import Action, BehaviorTree, Sequence
from core.provisioning import DomainRuntime, DomainRuntimeRegistry
from core.provisioning.service import AgentRecord, SpecializedAgent

SALES_TEMPLATE = "autonomous_sales"

logger = logging.getLogger("agentos.examples.sales")


class SalesAgentDomainRuntime(DomainRuntime):
    """Autonomous Sales Agent domain runtime pack.

    Applies outreach compliance constraints, provisioning profile, and a
    four-step behavior tree: research → personalise → compliance gate → send.
    """

    @property
    def template(self) -> str:
        return SALES_TEMPLATE

    def apply_profile(self, agent: AgentRecord) -> AgentRecord:
        agent.specialized_agents = [
            SpecializedAgent(
                name="research-agent",
                boundary="Collects live company and prospect signals before outreach is drafted",
            ),
            SpecializedAgent(
                name="personalization-agent",
                boundary="Generates outreach grounded in verified signals and prior context",
            ),
            SpecializedAgent(
                name="compliance-gate-agent",
                boundary="Enforces opt-out, consent, and weekly contact rules before sending",
            ),
            SpecializedAgent(
                name="interaction-tracker-agent",
                boundary="Persists outreach history and follow-up context for future contact",
            ),
        ]
        agent.metadata = {
            **agent.metadata,
            "domain_profile": "autonomous_sales",
            "domain": "sales",
            "compliance_mode": "can_spam_gdpr",
            "memory_backend": "vector",
            "analytics_feedback": "enabled",
            "capabilities": [
                "research",
                "personalization",
                "interaction_memory",
                "analytics",
                "compliance_gating",
            ],
            "domain_defaults": {
                "personalization_coverage_min_rate": 95.0,
                "reply_rate_min": 12.0,
                "meetings_booked_rate_min": 3.0,
                "max_touches_per_7_days": 3,
            },
        }
        return agent

    def register_constraints(self, constraint_layer: ConstraintLayer) -> None:
        """Inject sales compliance and safety constraints (all immutable)."""
        constraints = [
            Constraint(
                constraint_id="sales.opt_out_respected",
                name="Opted-out prospects must never be contacted",
                constraint_type=ConstraintType.SAFETY,
                severity=ConstraintSeverity.CRITICAL,
                check_fn=lambda state: not state.get("opted_out", False),
                description=(
                    "Any prospect with opted_out=True must be hard-blocked. "
                    "CAN-SPAM and CASL compliance requirement."
                ),
            ),
            Constraint(
                constraint_id="sales.gdpr_consent_required",
                name="GDPR: prospect must have consented to messaging",
                constraint_type=ConstraintType.SAFETY,
                severity=ConstraintSeverity.CRITICAL,
                check_fn=lambda state: state.get("consented_messaging", True),
                description=(
                    "B2C EU prospects require explicit GDPR consent before any outreach. "
                    "Defaults to True for B2B; opt-in required for B2C EU."
                ),
            ),
            Constraint(
                constraint_id="sales.rate_limit_weekly",
                name="Maximum 3 touches per prospect per 7-day window",
                constraint_type=ConstraintType.SAFETY,
                severity=ConstraintSeverity.HIGH,
                check_fn=lambda state: state.get("touches_this_week", 0) < 3,
                description=(
                    "Prospects must not receive more than 3 messages in a rolling "
                    "7-day window. Excess touches are blocked, not queued."
                ),
            ),
            Constraint(
                constraint_id="sales.no_unverified_outreach",
                name="Outreach must reference at least one verified live signal",
                constraint_type=ConstraintType.OPERATIONAL,
                severity=ConstraintSeverity.HIGH,
                check_fn=lambda state: state.get("signal_count", 0) >= 1,
                description=(
                    "Personalisation must be grounded in at least one live signal "
                    "(news item, LinkedIn activity, or filing event). "
                    "Template-only messages are blocked."
                ),
            ),
        ]
        for constraint in constraints:
            constraint_layer.add_immutable_constraint(constraint)

    def register_behaviors(self, planner: object) -> None:
        """Register a four-step sales behavior tree."""
        if not hasattr(planner, "register_tree"):
            return

        root = Sequence("sales_agent_flow")
        root.add_child(Action("research_prospect"))
        root.add_child(Action("personalise_outreach"))
        root.add_child(Action("compliance_gate"))
        root.add_child(Action("send_and_track"))

        tree = BehaviorTree(root)
        planner.register_tree("sales_agent_flow", tree)

        if hasattr(planner, "set_active_tree"):
            planner.set_active_tree("sales_agent_flow")

    def configure_memory(self, memory_store: object) -> None:
        """Seed interaction memory with a starter context hint."""
        if hasattr(memory_store, "put"):
            memory_store.put(
                "context.sales.tip.opening",
                "Reference a specific company event or trigger in the opening line.",
            )
            memory_store.put(
                "context.sales.tip.follow_up",
                "Follow-up messages should reference the previous message topic, not restart from scratch.",
            )


def register_sales_runtime(registry: DomainRuntimeRegistry) -> None:
    """Register the sales domain runtime with the global domain registry."""
    registry.register(SalesAgentDomainRuntime())
