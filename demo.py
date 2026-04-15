"""Narrated demo for the Autonomous Sales Agent.

Runs a full six-prospect batch through all four agents and surfaces:
  1. ResearchAgent signal discovery per prospect
  2. PersonalizationAgent message generation with live signals
  3. ComplianceGate blocking an opted-out prospect and a rate-limited prospect
  4. InteractionTracker writing to VectorMemoryStore
  5. AnalyticsAgent pattern insights
  6. Pre/post readiness checks

Blocked cases are intentional guardrail behaviour - they prove the safety
constraints are enforced, not a broken demo.
"""

from __future__ import annotations

import json
import sys
import textwrap
import logging
from pathlib import Path

# path bootstrap for direct execution
_RUNTIME_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_ROOT))
# end path bootstrap

from examples.autonomous_sales.workflow import Prospect, SalesAgentWorkflow
from examples.autonomous_sales.readiness import (
    run_pre_deployment_readiness,
    run_post_run_readiness,
)

_LINE = "-" * 68


def _section(title: str) -> None:
    print(f"\n{_LINE}")
    print(f"  {title}")
    print(_LINE)


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _blocked(msg: str) -> None:
    print(f"  [BLOCKED] {msg}")


def _info(msg: str) -> None:
    print(f"     {msg}")


def run_demo() -> None:
    # The demo intentionally triggers blocked prospects; suppress expected error logs.
    logging.getLogger("agentos.constraints").setLevel(logging.CRITICAL + 1)

    print()
    print("+------------------------------------------------------------------+")
    print("|         AUTONOMOUS SALES AGENT - AgentOS Demo                   |")
    print("+------------------------------------------------------------------+")
    _info("Four-agent pipeline: Research -> Personalize -> Compliance Gate -> Track")
    _info("Memory layer: VectorMemoryStore (contextual follow-ups)")
    _info("Analytics: pattern insights surface every run")

    # ------------------------------------------------------------------
    # Pre-deployment readiness
    # ------------------------------------------------------------------
    _section("PILOT 1  Pre-Deployment Readiness")
    workflow = SalesAgentWorkflow(response_budget_ms=2000.0)
    pre = run_pre_deployment_readiness(workflow)
    for check in pre.checks:
        if check.passed:
            _ok(f"{check.name}  [{check.detail}]")
        else:
            _blocked(f"{check.name} FAILED  [{check.detail}]")
    status = "PASS" if pre.passed else "FAIL"
    print(f"\n  Pre-deployment: {status}")

    # ------------------------------------------------------------------
    # Prospect list - mix of clean, opted-out, rate-limited, no-consent
    # ------------------------------------------------------------------
    _section("PILOT 2  Prospect Batch (6 leads)")

    prospects = [
        Prospect(
            prospect_id="p001",
            name="Sarah Chen",
            title="VP of Operations",
            company="Acme Corp",
            industry="Warehouse Automation",
            linkedin_url="https://linkedin.com/in/sarahchen",
            touches_this_week=0,
            priority=3,
        ),
        Prospect(
            prospect_id="p002",
            name="Dr. James Okafor",
            title="CTO",
            company="HealthFirst",
            industry="Healthcare Operations",
            touches_this_week=0,
            priority=2,
        ),
        Prospect(
            prospect_id="p003",
            name="Mei Zhang",
            title="Head of Operations",
            company="NexusAI",
            industry="AI-Powered Logistics",
            touches_this_week=0,
            priority=2,
        ),
        Prospect(
            prospect_id="p004",
            name="Tom Hargreaves",
            title="Director of Ops",
            company="ClearPath Logistics",
            industry="Last-Mile Delivery",
            opted_out=True,          # CRITICAL: should be blocked (opted out)
            touches_this_week=0,
            priority=1,
        ),
        Prospect(
            prospect_id="p005",
            name="Aisha Nwosu",
            title="VP Finance",
            company="Meridian Financial",
            industry="Trade Finance",
            touches_this_week=3,     # HIGH: rate limit hit, should be blocked
            priority=1,
        ),
        Prospect(
            prospect_id="p006",
            name="Carlos Reyes",
            title="CISO",
            company="Vertex Retail",
            industry="Retail Operations",
            touches_this_week=0,
            priority=1,
        ),
    ]

    print(f"  Queued {len(prospects)} prospects across {len(set(p.company for p in prospects))} companies")
    for p in prospects:
        flags = []
        if p.opted_out:
            flags.append("OPT-OUT")
        if p.touches_this_week >= 3:
            flags.append("RATE-LIMITED")
        tag = f"  [{', '.join(flags)}]" if flags else ""
        print(f"    * {p.name} - {p.title} @ {p.company}{tag}")

    # ------------------------------------------------------------------
    # Run the batch
    # ------------------------------------------------------------------
    _section("PILOT 3  Running Four-Agent Pipeline")
    result = workflow.process_leads(prospects)

    for lead in result.results:
        if lead.company_contention_blocked:
            _blocked(
                f"{lead.name} ({lead.company})  "
                f"[guardrail: company contention - higher-priority contact selected]"
            )
            continue

        if lead.blocked:
            _blocked(
                f"{lead.name} ({lead.company})  "
                f"[EXPECTED GUARDRAIL: {lead.violations[0] if lead.violations else 'compliance block'}]"
            )
            _info("  ^ This block is correct behaviour. The safety constraint is working.")
        else:
            _ok(f"{lead.name} ({lead.company})  <- message queued")
            if lead.message:
                _info(f"  Subject : {lead.message.subject}")
                _info(f"  Signals : {', '.join(lead.message.signal_hooks)}")
                _info(f"  Memory  : {'yes - prior context injected' if lead.memory_context_used else 'no prior interactions'}")
                body_first = lead.message.body.split("\n\n")[1] if "\n\n" in lead.message.body else ""
                _info(f"  Opening : {textwrap.shorten(body_first, 90)}")

    # ------------------------------------------------------------------
    # Batch summary
    # ------------------------------------------------------------------
    _section("PILOT 4  Batch Summary")
    _ok(f"Total leads processed   : {result.total_leads}")
    _ok(f"Messages sent           : {result.contacted}")
    _blocked(f"Blocked by guardrails   : {result.blocked}  (expected)")
    _info(f"Company contention      : {result.company_contention_blocks} deferred")
    _info(f"Avg research time       : {result.avg_research_ms:.1f} ms")
    _info(f"Avg personalisation time: {result.avg_personalization_ms:.1f} ms")

    # ------------------------------------------------------------------
    # Memory state
    # ------------------------------------------------------------------
    _section("PILOT 5  Interaction Memory (VectorMemoryStore)")
    _info("Follow-up queries now return contextual prior-interaction snippets:")
    test_queries = [
        ("Sarah Chen follow-up", "VP Operations warehouse automation"),
        ("HealthFirst follow-up", "CTO healthcare AI triage"),
    ]
    for label, query in test_queries:
        contexts = workflow.memory.search(query, k=1)
        if contexts:
            _ok(f"{label}: {textwrap.shorten(contexts[0][1], 80)}")
        else:
            _info(f"{label}: no prior context yet")

    # ------------------------------------------------------------------
    # Analytics insights
    # ------------------------------------------------------------------
    _section("PILOT 6  AnalyticsAgent - Weekly Pattern Insights")
    if result.pattern_insights:
        for insight in result.pattern_insights:
            _ok(f"{insight.pattern}  ({int(insight.observed_contact_rate * 100)}% of messages)")
            _info(f"  -> {insight.recommendation}")
    else:
            _info("No insights yet - run with more prospects to surface patterns.")

    # ------------------------------------------------------------------
    # Post-run readiness
    # ------------------------------------------------------------------
    _section("PILOT 7  Post-Run Readiness")
    post = run_post_run_readiness(result)
    for check in post.checks:
        if check.passed:
            _ok(f"{check.name}  [{check.detail}]")
        else:
            _blocked(f"{check.name}  [{check.detail}]")
    status = "PASS" if post.passed else "FAIL"
    print(f"\n  Post-run: {status}")

    # ------------------------------------------------------------------
    # Closing capability summary
    # ------------------------------------------------------------------
    _section("DEMO COMPLETE - AgentOS Capabilities Proven")
    capabilities = [
        ("ResearchAgent",        "Live signal discovery from LinkedIn, news, and filings"),
        ("PersonalizationAgent", "Signal-grounded, memory-augmented outreach - not templates"),
        ("ComplianceGate",       "Opt-out, GDPR, rate-limit, and signal-verification enforcement"),
        ("InteractionTracker",   "Every touch written to VectorMemoryStore for contextual follow-ups"),
        ("MultiAgentCoordinator","Company-level contention resolved deterministically"),
        ("AnalyticsAgent",       "Weekly pattern insights from signal -> response feedback loops"),
    ]
    for agent, desc in capabilities:
        _ok(f"{agent:<26}  {desc}")

    guardrail_pass = result.blocked >= 2
    guardrail_pass = guardrail_pass and any(
        lead.blocked and any("sales.opt_out_respected" in violation for violation in lead.violations)
        for lead in result.results
    )
    guardrail_pass = guardrail_pass and any(
        lead.blocked and any("sales.rate_limit_weekly" in violation for violation in lead.violations)
        for lead in result.results
    )

    report = {
        "scenario": "autonomous_sales_full_demo",
        "passed": bool(pre.passed and post.passed and guardrail_pass),
        "guardrail_pass": bool(guardrail_pass),
        "metrics": {
            "total_leads": result.total_leads,
            "contacted": result.contacted,
            "blocked": result.blocked,
            "company_contention_blocks": result.company_contention_blocks,
            "pattern_insights": len(result.pattern_insights),
        },
        "checks": {
            "pre_deployment": pre.passed,
            "post_run": post.passed,
        },
    }
    report_path = Path("tools/reports/sales-latest.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print()
    print("  Next step:  agentos init my-sales-agent --template autonomous_sales")
    print()


if __name__ == "__main__":
    run_demo()
