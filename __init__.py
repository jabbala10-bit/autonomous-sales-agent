"""Autonomous Sales Agent domain pack.

Four-agent pipeline built on AgentOS core primitives:

  ResearchAgent        → scrapes LinkedIn, news, and filings signals
  PersonalizationAgent → generates hyper-specific outreach from live signals + memory
  InteractionTracker   → writes every touch to VectorMemoryStore for contextual follow-ups
  AnalyticsAgent       → emits FeedbackSignals so the team learns which patterns convert

Safety is enforced by the sales.opt_out_respected and sales.gdpr_consent_required
CRITICAL constraints — blocked cases are visible in the demo by design.
"""

from .domain_runtime import SalesAgentDomainRuntime, register_sales_runtime
from .scenario import SalesScenarioEvaluation, SalesScenarioMetrics, evaluate_autonomous_sales
from .workflow import SalesAgentWorkflow, Prospect, OutreachMessage, BatchLeadResult

__all__ = [
    "SalesAgentDomainRuntime",
    "register_sales_runtime",
    "SalesScenarioEvaluation",
    "SalesScenarioMetrics",
    "evaluate_autonomous_sales",
    "SalesAgentWorkflow",
    "Prospect",
    "OutreachMessage",
    "BatchLeadResult",
]
