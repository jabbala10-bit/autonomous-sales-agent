"""Sales policy engine — evaluates YAML-driven soft advisory rules.

Mirrors the AutoServePolicyEngine pattern so behaviour is consistent
across domain packs. Hard CRITICAL/HIGH constraint violations are handled
separately by the ConstraintLayer in domain_runtime.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SalesRule:
    name: str
    description: str
    safety: bool
    trigger: str
    condition: str | None
    action: str
    enabled: bool = True


class SalesPolicyEngine:
    """Evaluate sales compliance rules from a YAML policy pack."""

    def __init__(self, rules: list[SalesRule]) -> None:
        self._rules = rules

    @classmethod
    def from_yaml_file(cls, file_path: str) -> "SalesPolicyEngine":
        text = Path(file_path).read_text(encoding="utf-8")
        return cls(cls._parse_yaml_rules(text))

    def list_rules(self) -> list[SalesRule]:
        return list(self._rules)

    def disable_rule(self, name: str) -> None:
        for rule in self._rules:
            if rule.name == name:
                if rule.safety:
                    raise ValueError(f"safety-critical rule '{name}' cannot be disabled")
                rule.enabled = False
                return
        raise KeyError(f"rule '{name}' not found")

    def evaluate(self, event: dict[str, Any]) -> dict[str, Any]:
        violations: list[dict[str, Any]] = []
        blocked = False

        for rule in self._rules:
            if not rule.enabled:
                continue
            if not self._eval_expr(rule.trigger, event):
                continue

            violated = True if not rule.condition else self._eval_expr(rule.condition, event)
            if violated:
                blocked = True
                violations.append(
                    {
                        "rule": rule.name,
                        "description": rule.description,
                        "safety": rule.safety,
                        "action": rule.action,
                    }
                )

        return {"allowed": not blocked, "blocked": blocked, "violations": violations}

    # ------------------------------------------------------------------
    # YAML parsing (same minimal hand-rolled parser as AutoServe)
    # ------------------------------------------------------------------

    @classmethod
    def _parse_yaml_rules(cls, text: str) -> list[SalesRule]:
        rules: list[SalesRule] = []
        current: dict[str, Any] = {}

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("#") or not line:
                continue
            if line == "rules:":
                continue
            if line.startswith("- name:"):
                if current:
                    rules.append(cls._make_rule(current))
                current = {"name": line.split(":", 1)[1].strip()}
            elif ":" in line and current:
                key, _, val = line.partition(":")
                key = key.strip().lstrip("-").strip()
                val = val.strip().strip('"')
                if val == "null":
                    val = None  # type: ignore[assignment]
                current[key] = val

        if current:
            rules.append(cls._make_rule(current))
        return rules

    @staticmethod
    def _make_rule(d: dict[str, Any]) -> SalesRule:
        return SalesRule(
            name=d.get("name", ""),
            description=d.get("description", ""),
            safety=str(d.get("safety", "false")).lower() == "true",
            trigger=d.get("trigger", ""),
            condition=d.get("condition") or None,
            action=d.get("action", ""),
        )

    @staticmethod
    def _coerce(value: str) -> Any:
        if value in ("true", "True"):
            return True
        if value in ("false", "False"):
            return False
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value

    @classmethod
    def _eval_expr(cls, expr: str, event: dict[str, Any]) -> bool:
        ops = [" >= ", " <= ", " != ", " == ", " > ", " < "]
        for op in ops:
            if op in expr:
                left, right = expr.split(op, 1)
                lv = event.get(left.strip(), cls._coerce(left.strip()))
                rv = cls._coerce(right.strip())
                lv_cmp = cls._coerce(str(lv)) if isinstance(lv, bool) else lv
                if op.strip() == "==":
                    return lv_cmp == rv
                if op.strip() == "!=":
                    return lv_cmp != rv
                if op.strip() == ">=":
                    return lv_cmp >= rv  # type: ignore[operator]
                if op.strip() == "<=":
                    return lv_cmp <= rv  # type: ignore[operator]
                if op.strip() == ">":
                    return lv_cmp > rv  # type: ignore[operator]
                if op.strip() == "<":
                    return lv_cmp < rv  # type: ignore[operator]
        return False
