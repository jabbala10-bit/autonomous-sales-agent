"""Autonomous Sales Agent — four-agent workflow pipeline.

Agents run in sequence per lead:

  1. ResearchAgent        — queries LinkedIn, news, and filings adapters
  2. PersonalizationAgent — builds hyper-specific message from signals + memory context
  3. ComplianceGate       — enforces domain constraints (opt-out, rate limit, GDPR, signal count)
  4. InteractionTracker   — writes every touch to VectorMemoryStore

After the batch, AnalyticsAgent reads the FeedbackSignals and surfaces conversion patterns.

MultiAgentCoordinator prevents duplicate simultaneous outreach to the same company
(e.g. three reps sending to the same account in the same run).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from core.coordination import MultiAgentCoordinator, ResourceRequest
from core.memory.store import VectorMemoryStore
from core.memory.retrieval import retrieve_context, augment_objective_with_context

from .domain_runtime import SalesAgentDomainRuntime
from .policy_engine import SalesPolicyEngine


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Prospect:
    """A sales lead sourced from CRM or manual import."""

    prospect_id: str
    name: str
    title: str
    company: str
    industry: str
    linkedin_url: str = ""
    company_news_url: str = ""
    opted_out: bool = False
    touches_this_week: int = 0
    consented_messaging: bool = True
    priority: int = 1  # higher = preferred in company-level contention


@dataclass
class ResearchSignals:
    """Live signals discovered by the ResearchAgent."""

    news_items: List[str] = field(default_factory=list)
    linkedin_activity: str = ""
    company_trigger: str = ""   # e.g. "raised $40M Series B", "new VP of Ops hired"
    filing_event: str = ""      # e.g. "10-Q: overseas expansion announced"
    crm_notes: str = ""

    @property
    def signal_count(self) -> int:
        count = 0
        if self.news_items:
            count += 1
        if self.linkedin_activity:
            count += 1
        if self.company_trigger:
            count += 1
        if self.filing_event:
            count += 1
        return count


@dataclass
class EnrichedProspect:
    """Prospect enriched with live signals."""

    prospect: Prospect
    signals: ResearchSignals
    research_ms: float = 0.0


@dataclass
class OutreachMessage:
    """A personalised outreach message produced by PersonalizationAgent."""

    prospect_id: str
    message_id: str
    subject: str
    body: str
    signal_hooks: List[str] = field(default_factory=list)  # which signals drove personalisation
    memory_context_used: bool = False
    blocked: bool = False
    violations: List[str] = field(default_factory=list)
    audit_log: List[str] = field(default_factory=list)


@dataclass
class ProcessedLead:
    """Full result for one lead through the pipeline."""

    prospect_id: str
    name: str
    company: str
    enriched: bool
    message: Optional[OutreachMessage]
    blocked: bool
    violations: List[str]
    research_ms: float
    personalization_ms: float
    memory_context_used: bool
    company_contention_blocked: bool = False


@dataclass
class PatternInsight:
    """A weekly learning insight from the AnalyticsAgent."""

    pattern: str
    signal_type: str
    observed_contact_rate: float
    recommendation: str


@dataclass
class BatchLeadResult:
    """Full result for a processed batch of prospects."""

    results: List[ProcessedLead]
    total_leads: int
    contacted: int
    blocked: int
    company_contention_blocks: int
    avg_research_ms: float
    avg_personalization_ms: float
    pattern_insights: List[PatternInsight] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Research signal simulator (domain adapters)
# ---------------------------------------------------------------------------

# In production these would call LinkedIn Sales Navigator API, NewsAPI,
# SEC EDGAR, and a CRM connector. The simulation produces deterministic
# realistic outputs so the demo and tests are self-contained.

_COMPANY_TRIGGERS: Dict[str, str] = {
    "acme_corp": "raised $40M Series B – new VP of Operations hired last week",
    "healthfirst": "announced NHS digital contracting programme expansion",
    "nexusai": "filed 10-Q citing overseas warehouse automation initiative",
    "clearpath_logistics": "CEO published LinkedIn post: 'scaling last-mile ops 3×'",
    "meridian_financial": "posted 6 open roles in trade-finance operations",
    "vertex_retail": "Q3 earnings call: 'reducing manual picking errors is top priority'",
}

_NEWS_ITEMS: Dict[str, List[str]] = {
    "acme_corp": [
        "Acme Corp closes $40M Series B to accelerate warehouse robotics rollout",
        "Acme appoints Sarah Chen as VP Operations — previously at Amazon Robotics",
    ],
    "healthfirst": [
        "HealthFirst wins £12M NHS contract for patient flow automation",
        "NHS England names HealthFirst preferred partner for triage AI pilot",
    ],
    "nexusai": [
        "NexusAI expands to three new EMEA distribution centres",
        "NexusAI 10-Q: overseas ops budget up 47% YoY",
    ],
    "clearpath_logistics": [
        "ClearPath raises $18M to scale micro-fulfilment network",
    ],
    "meridian_financial": [
        "Meridian Financial launches AI-assisted trade-finance desk",
    ],
    "vertex_retail": [
        "Vertex Retail Q3: inventory accuracy investment planned for FY25",
    ],
}

_LINKEDIN_ACTIVITY: Dict[str, str] = {
    "acme_corp": "VP Ops Sarah Chen posted: 'excited to lead our automation journey'",
    "healthfirst": "CTO commented on AI triage paper: 'exactly what we're building next'",
    "nexusai": "CEO liked three posts on 'multi-agent warehouse coordination'",
    "clearpath_logistics": "Head of Ops shared a post on last-mile robotics trends",
    "meridian_financial": "Director of Ops posted job spec: 'experience with AI workflow tools preferred'",
    "vertex_retail": "CISO reposted: 'why every retailer needs autonomous inventory ops in 2026'",
}


def _simulate_research(prospect: Prospect) -> ResearchSignals:
    """Simulate the ResearchAgent calling LinkedIn, news, and filings APIs."""
    company_key = prospect.company.lower().replace(" ", "_").replace("-", "_")

    return ResearchSignals(
        news_items=_NEWS_ITEMS.get(company_key, [
            f"{prospect.company} recently appeared in industry news",
        ]),
        linkedin_activity=_LINKEDIN_ACTIVITY.get(company_key, ""),
        company_trigger=_COMPANY_TRIGGERS.get(company_key, ""),
        filing_event="10-Q filed last quarter" if "financial" in company_key else "",
        crm_notes=f"Last contacted: never — first-touch opportunity for {prospect.title}",
    )


# ---------------------------------------------------------------------------
# Personalization engine (PersonalizationAgent)
# ---------------------------------------------------------------------------

def _build_message(
    prospect: Prospect,
    signals: ResearchSignals,
    memory_contexts: List[str],
    *,
    message_id: str,
) -> OutreachMessage:
    """Build a signal-grounded personalised outreach message.

    In production this calls an LLM planner (OpenAI provider) with the
    enriched prospect and retrieved memory context as the system prompt.
    The simulation produces deterministic copy that mirrors what a
    well-prompted LLM would generate.
    """
    signal_hooks: List[str] = []

    # Pick the strongest opening hook from available signals
    opening = ""
    if signals.company_trigger:
        opening = f"I saw that {prospect.company} {signals.company_trigger.lower()}."
        signal_hooks.append("company_trigger")
    elif signals.news_items:
        opening = f"I noticed {signals.news_items[0]}."
        signal_hooks.append("news")
    elif signals.linkedin_activity:
        opening = f"Your recent LinkedIn activity caught my attention — {signals.linkedin_activity}."
        signal_hooks.append("linkedin")

    # Inject prior interaction context from memory
    memory_hint = ""
    if memory_contexts:
        memory_hint = f"\n\nContext from previous interactions: {memory_contexts[0]}"
        signal_hooks.append("memory_context")

    subject = f"Quick thought on {prospect.company}'s {prospect.industry} ops"
    body = (
        f"Hi {prospect.name.split()[0]},\n\n"
        f"{opening}\n\n"
        f"We help {prospect.industry} teams eliminate the manual coordination overhead "
        f"that slows operations as they scale — specifically the gaps between agents, "
        f"systems, and decisions that require a human in the loop today.\n\n"
        f"Given your role as {prospect.title}, I thought there might be a relevant "
        f"parallel to what we've built. Would a 20-minute call next week make sense?"
        f"{memory_hint}"
    )

    return OutreachMessage(
        prospect_id=prospect.prospect_id,
        message_id=message_id,
        subject=subject,
        body=body,
        signal_hooks=signal_hooks,
        memory_context_used=bool(memory_contexts),
        audit_log=[
            f"personalisation-agent: opening hook = {signal_hooks[0] if signal_hooks else 'none'}",
            f"personalisation-agent: memory_context_used = {bool(memory_contexts)}",
            f"personalisation-agent: signal_count = {signals.signal_count}",
        ],
    )


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------


class SalesAgentWorkflow:
    """Autonomous Sales Agent pipeline built on AgentOS core primitives.

    Usage::

        workflow = SalesAgentWorkflow()
        result = workflow.process_leads(prospects)
        for lead in result.results:
            if not lead.blocked:
                print(f"✓ {lead.name}: {lead.message.subject}")
    """

    MAX_WEEKLY_TOUCHES = 3

    def __init__(
        self,
        *,
        response_budget_ms: float = 2000.0,
        policy_path: Optional[Path] = None,
    ) -> None:
        from core.constraints import ConstraintLayer

        self.response_budget_ms = response_budget_ms
        self.runtime = SalesAgentDomainRuntime()
        self.constraint_layer = ConstraintLayer()
        self.runtime.register_constraints(self.constraint_layer)

        self.coordinator = MultiAgentCoordinator()
        self.memory = VectorMemoryStore()
        self.runtime.configure_memory(self.memory)

        rule_file = policy_path or (
            Path(__file__).resolve().parent / "policies" / "sales_policy.yaml"
        )
        self.policy_engine = SalesPolicyEngine.from_yaml_file(str(rule_file))

        # Interaction log: {prospect_id: [OutreachMessage, ...]}
        self._interaction_log: Dict[str, List[OutreachMessage]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_leads(self, prospects: List[Prospect]) -> BatchLeadResult:
        """Run the full four-agent pipeline for a list of prospects.

        Returns a BatchLeadResult with per-lead results and batch analytics.
        """
        t_batch_start = time.monotonic()
        results: List[ProcessedLead] = []
        company_contention_blocks = 0

        # --- stage 1: company-level contention (MultiAgentCoordinator) ---
        # Only the highest-priority rep contacts each company per run.
        company_grantees: Dict[str, Optional[str]] = {}
        for p in prospects:
            self.coordinator.submit(
                ResourceRequest(
                    request_id=f"{p.prospect_id}:{p.company}",
                    agent_id=p.prospect_id,
                    resource_id=p.company,
                    priority=p.priority,
                    ttl_seconds=30,
                    created_at=datetime.utcnow(),
                )
            )
        for p in prospects:
            if p.company not in company_grantees:
                decision = self.coordinator.resolve(p.company)
                company_grantees[p.company] = decision.granted_to

        # --- stage 2: per-lead pipeline ---
        research_times: List[float] = []
        personalisation_times: List[float] = []

        for prospect in prospects:
            granted_id = company_grantees.get(prospect.company)
            if granted_id is not None and granted_id != prospect.prospect_id:
                # Another higher-priority contact for this company won this run.
                company_contention_blocks += 1
                results.append(
                    ProcessedLead(
                        prospect_id=prospect.prospect_id,
                        name=prospect.name,
                        company=prospect.company,
                        enriched=False,
                        message=None,
                        blocked=True,
                        violations=["sales.company_contention: higher-priority contact selected for this company"],
                        research_ms=0.0,
                        personalization_ms=0.0,
                        memory_context_used=False,
                        company_contention_blocked=True,
                    )
                )
                continue

            result = self._process_single_lead(prospect)
            research_times.append(result.research_ms)
            personalisation_times.append(result.personalization_ms)
            results.append(result)

        # --- stage 3: analytics agent ---
        insights = self._analytics_agent(results)

        contacted = sum(1 for r in results if not r.blocked)
        blocked = sum(1 for r in results if r.blocked)
        avg_research = sum(research_times) / len(research_times) if research_times else 0.0
        avg_personal = sum(personalisation_times) / len(personalisation_times) if personalisation_times else 0.0

        return BatchLeadResult(
            results=results,
            total_leads=len(prospects),
            contacted=contacted,
            blocked=blocked,
            company_contention_blocks=company_contention_blocks,
            avg_research_ms=avg_research,
            avg_personalization_ms=avg_personal,
            pattern_insights=insights,
        )

    def get_interaction_history(self, prospect_id: str) -> List[OutreachMessage]:
        """Return all logged interactions for a prospect (for follow-up context)."""
        return self._interaction_log.get(prospect_id, [])

    # ------------------------------------------------------------------
    # Internal agents
    # ------------------------------------------------------------------

    def _process_single_lead(self, prospect: Prospect) -> ProcessedLead:
        # Agent 1: research
        t0 = time.monotonic()
        signals = _simulate_research(prospect)
        research_ms = (time.monotonic() - t0) * 1000

        enriched = EnrichedProspect(
            prospect=prospect,
            signals=signals,
            research_ms=research_ms,
        )

        # Agent 2: personalization — retrieve memory context first
        t1 = time.monotonic()
        memory_query = f"{prospect.company} {prospect.title} {prospect.industry}"
        memory_contexts = retrieve_context(self.memory, memory_query, k=2)
        message_id = _short_id(prospect.prospect_id)
        message = _build_message(
            prospect,
            signals,
            memory_contexts,
            message_id=message_id,
        )
        personalization_ms = (time.monotonic() - t1) * 1000

        # Agent 3: compliance gate — hard constraint check
        constraint_state = {
            "opted_out": prospect.opted_out,
            "consented_messaging": prospect.consented_messaging,
            "touches_this_week": prospect.touches_this_week,
            "signal_count": signals.signal_count,
        }
        _crit_ok, constraint_violations = self.constraint_layer.verify_state(constraint_state)

        # Also run soft policy engine
        policy_event = {
            "opted_out": prospect.opted_out,
            "touches_this_week": prospect.touches_this_week,
            "signal_count": signals.signal_count,
            "consented_messaging": prospect.consented_messaging,
        }
        policy_result = self.policy_engine.evaluate(policy_event)

        all_violations = (
            [f"{v.constraint_id}: {v.constraint_name}" for v in constraint_violations]
            + [v["description"] for v in policy_result.get("violations", [])]
        )
        blocked = bool(constraint_violations) or policy_result.get("blocked", False)

        if blocked:
            message.blocked = True
            message.violations = all_violations
        else:
            # Agent 4: track the interaction in memory
            self._track_interaction(prospect, message, signals)

        return ProcessedLead(
            prospect_id=prospect.prospect_id,
            name=prospect.name,
            company=prospect.company,
            enriched=True,
            message=message,
            blocked=blocked,
            violations=all_violations,
            research_ms=research_ms,
            personalization_ms=personalization_ms,
            memory_context_used=message.memory_context_used,
        )

    def _track_interaction(
        self,
        prospect: Prospect,
        message: OutreachMessage,
        signals: ResearchSignals,
    ) -> None:
        """Agent 4: write the interaction to VectorMemoryStore.

        Stored under two keys:
        - by prospect_id for exact follow-up retrieval
        - by company for cross-contact awareness
        """
        interaction_text = (
            f"Prospect: {prospect.name} ({prospect.title} at {prospect.company}). "
            f"Signal hooks: {', '.join(message.signal_hooks)}. "
            f"Subject: {message.subject}. "
            f"Trigger: {signals.company_trigger or 'none'}."
        )
        self.memory.put(f"interaction.{prospect.prospect_id}", interaction_text)
        self.memory.put(f"company.{prospect.company.lower()}", interaction_text)

        # Maintain in-memory log for follow-up queries
        self._interaction_log.setdefault(prospect.prospect_id, []).append(message)

    def _analytics_agent(self, results: List[ProcessedLead]) -> List[PatternInsight]:
        """Analyse the batch and surface which signal types drove engagement.

        In V2 this would use FeedbackManager + ExperienceBuffer to accumulate
        signals across multiple runs and generate governance-gated learning
        proposals via PolicyUpdater. For now it produces deterministic insights
        from the current batch.
        """
        signal_type_counts: Dict[str, int] = {}
        total_contacted = 0

        for result in results:
            if result.blocked or result.message is None:
                continue
            total_contacted += 1
            for hook in result.message.signal_hooks:
                signal_type_counts[hook] = signal_type_counts.get(hook, 0) + 1

        insights: List[PatternInsight] = []
        if not total_contacted:
            return insights

        hook_order = [
            ("company_trigger", "Funding, hiring, or expansion triggers"),
            ("news", "Recent press coverage or announcements"),
            ("linkedin", "LinkedIn activity or engagement"),
            ("memory_context", "Prior interaction context used in message"),
        ]
        for hook_key, label in hook_order:
            count = signal_type_counts.get(hook_key, 0)
            rate = count / total_contacted
            if rate > 0:
                insights.append(
                    PatternInsight(
                        pattern=label,
                        signal_type=hook_key,
                        observed_contact_rate=round(rate, 2),
                        recommendation=(
                            f"Prioritise '{hook_key}' sourcing — used in {count}/{total_contacted} "
                            f"messages this run ({int(rate * 100)}% coverage)."
                        ),
                    )
                )

        return sorted(insights, key=lambda i: -i.observed_contact_rate)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_id(text: str) -> str:
    return hashlib.md5(f"{text}{time.time()}".encode()).hexdigest()[:8]  # noqa: S324 — demo ID only
