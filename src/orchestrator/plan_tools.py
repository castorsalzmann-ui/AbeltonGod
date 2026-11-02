"""The ``plan_arrangement`` copilot tool and its plan table (#222, G5).

Design: docs/research/2026-11-02_arrangement-plan-generator-design.md, sections 3 and 7 (G5).
Claude maps the user's words to genre, tempo, length and named setting changes; the local
generator (``arrangement_generator.generate_plan``) computes every section and every number
(D-002). The tool is ``routine``: it writes no file and does not touch Live.

Where the plan lives (proposal, PR #222): in this session's table ``PlanSession.plans``, keyed
by a ``plan_id`` (``plan-1``, ...) like ``sample_id`` for kicks. The tool returns the id and a
summary; Claude never receives or sends a whole plan (INTERFACES "Arrangement plan"). A file is
written only by the user-run CLI (``orchestrator.plan_cli``); a later Live builder (G6) takes the
plan by id from this table.

Tool schema: strict subset, **no optional parameters** (the strict budget is 24 of 24 across
the kick tools). The length is a required pair ``length`` + ``length_unit``; the settings are a
required array (empty allowed) of ``{key, value}``. Every range check is local, because the
strict subset has no ``minimum``. The schema is built here, not in ``contracts/``: moving it
into a ``contract-change`` file is proposed in the PR.

``second_drop: ask`` (proposal, PR #222): the generator treats ``ask`` as ``equal`` plus a
warning. In the chat Claude is the one who can ask, so the tool refuses ``ask`` and tells
Claude to ask the user first and then pass ``stronger`` or ``equal``.
"""

from __future__ import annotations

import copy
from typing import Any

from orchestrator.arrangement_generator import generate_plan
from orchestrator.arrangement_layout import (
    BARS_RANGE,
    BPM_RANGE,
    GENRES,
    SETTING_ALLOWED,
    PlanRequest,
)
from orchestrator.tools import Approval, Tool, ToolError, ToolOutput

TOOL_NAME = "plan_arrangement"
LENGTH_UNITS = ("bars", "minutes")
MAX_PLANS = 20  # newest plans kept in the table

DESCRIPTION = (
    "Builds an arrangement plan (sections with start bar and length, energy line, settings) "
    "for one track with the local, deterministic generator and keeps it under a plan_id. "
    "Nothing is written to disk or to Live. The numbers are computed locally: do not invent "
    "sections or energy values. Give genre, bpm and the length either in bars (multiple of 8, "
    f"{BARS_RANGE[0]}-{BARS_RANGE[1]}) or in minutes (converted to bars locally, rounded to a "
    "multiple of 8). setting_changes lists only the settings the user asked to change "
    "(empty list = defaults). With the default settings only these lengths work: from 200 bars "
    "(techno) or 192 bars (trance) upwards, in steps of 8, so a short track needs different "
    "settings (a shorter intro or breakdown); a refusal names the nearest lengths that work. "
    "The outro is always 64 bars after a full drop: the outro_length setting never makes it "
    "shorter, it only sets the minimum. second_drop must be stronger or equal; if the user has "
    "not said which, ask them first. Read the result's adjustments and warnings back to the "
    "user in plain words."
)

_SETTING_HELP = {
    "build_kick": "kick in builds: filtered_in_build or at_drop",
    "intro_length": "bars: 16, 32 or 64",
    "outro_length": "bars: 16, 32 or 64; only a minimum, the outro is 64 after a full drop",
    "intro_outro_bass": "bass in intro and outro: on, outside_mix_zone or off",
    "breakdown_count": "1 or 2",
    "breakdown_length": "bars: 16, 32 or 64",
    "breakdown_rumble": "on or off",
    "second_drop": "stronger or equal (ask the user if unclear)",
    "change_grid": "bars between changes, 1-64",
    "pre_drop_gap": "bars of gap before a drop: 0, 1, 2 or 4",
    "fills": "off, section_change or every_8",
}


def tool_input_schema() -> dict[str, Any]:
    """The strict-subset input schema (no optional parameter, no root metadata)."""
    help_text = "; ".join(f"{k}: {v}" for k, v in _SETTING_HELP.items())
    return {
        "type": "object",
        "description": DESCRIPTION,
        "properties": {
            "genre": {"type": "string", "enum": list(GENRES),
                      "description": "Picks the section skeleton."},
            "bpm": {"type": "number",
                    "description": f"Tempo, {BPM_RANGE[0]}-{BPM_RANGE[1]}. 136-146 is the usual "
                                   "techno/trance range, not a limit."},
            "length": {"type": "number",
                       "description": "Track length in the unit given by length_unit."},
            "length_unit": {"type": "string", "enum": list(LENGTH_UNITS),
                            "description": "bars (a multiple of 8) or minutes."},
            "setting_changes": {
                "type": "array",
                "description": "Settings to change from their defaults, one entry each; "
                               f"empty list = all defaults. {help_text}.",
                "items": {
                    "type": "object",
                    "description": "One setting change.",
                    "properties": {
                        "key": {"type": "string", "enum": list(SETTING_ALLOWED),
                                "description": "Setting name."},
                        "value": {"anyOf": [
                            {"type": "string", "description": "A text value."},
                            {"type": "integer", "description": "A whole-number value."},
                        ], "description": "New value; the allowed values depend on the key."},
                    },
                    "required": ["key", "value"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["genre", "bpm", "length", "length_unit", "setting_changes"],
        "additionalProperties": False,
    }


# ----- model-facing refusal texts (one per error code of design note 2.3 and G2) ---------------

def _nearest(detail: dict) -> str:
    near = detail.get("nearest")
    if isinstance(near, dict):  # length_infeasible: {"below", "above"}
        parts = [f"{k} {v} bars" for k, v in near.items() if v is not None]
    else:
        parts = [f"{v} bars" for v in (near or [])]
    return " and ".join(parts) or "none"


def _text_bad_genre(d: dict) -> str:
    return f"genre must be one of {d.get('allowed')}."


def _text_bad_bpm(d: dict) -> str:
    lo, hi = d.get("allowed") or BPM_RANGE
    return f"bpm must be a number from {lo} to {hi}."


def _text_bad_setting(d: dict) -> str:
    allowed = d.get("allowed")
    if d.get("field") in SETTING_ALLOWED:
        return f"setting {d['field']!r} only allows {allowed}; ask the user which they want."
    return f"unknown setting {d.get('field')!r}; known settings: {allowed}."


def _text_infeasible(d: dict) -> str:
    return (f"{d.get('target_bars')} bars cannot be split into sections for this genre and "
            f"these settings. Nearest lengths that work: {_nearest(d)}. With the default "
            "settings a techno track needs at least 200 bars and a trance track at least 192 "
            "(steps of 8); shorter tracks need a shorter intro or breakdown in "
            "setting_changes. Offer the user the nearest length or a settings change.")


def _text_second_drop_ask() -> str:
    return ("second_drop 'ask' is not accepted by this tool: ask the user in the chat whether "
            "the second drop should be 'stronger' or 'equal', then call plan_arrangement again "
            "with their answer. Nothing was planned.")


REFUSALS = {
    "bad_genre": _text_bad_genre,
    "bad_bpm": _text_bad_bpm,
    "bad_setting": _text_bad_setting,
    "length_both_or_none": lambda d: (
        "give exactly one length: length plus length_unit ('bars' or 'minutes')."),
    "length_not_multiple_of_8": lambda d: (
        f"the length in bars must be a multiple of 8. Nearest: {_nearest(d)}."),
    "length_out_of_range": lambda d: (
        f"the length is outside {BARS_RANGE[0]}-{BARS_RANGE[1]} bars. Nearest: {_nearest(d)}."),
    "length_infeasible": _text_infeasible,
    "length_with_sections": lambda d: "a length cannot be given together with explicit sections.",
    "sections_invalid": lambda d: "the sections break the plan format: "
        + "; ".join(str(p) for p in d.get("problems") or []) + ".",
    "drawn_node_invalid": lambda d: (
        f"drawn energy node {d.get('index')} is invalid: {d.get('reason')}."),
    "outro_slot_too_short": lambda d: (
        f"the drawn energy makes the outro start high; it would need {d.get('required')} bars "
        f"but the slot has {d.get('slot')}."),
}


def refusal_text(errors: list[dict]) -> str:
    """One model-facing sentence per error; unknown codes still say their code."""
    texts = []
    for e in errors[:5]:
        code, detail = e.get("code"), e.get("detail") or {}
        make = REFUSALS.get(code)
        texts.append(f"{code}: {make(detail)}" if make else f"{code}: {detail}")
    return " ".join(texts) + " Nothing was planned."


# ----- request building shared by the tool and the CLI -----------------------------------------

def _whole(value: Any) -> Any:
    """A whole float (16.0) becomes an int; 16.5 stays and is refused by the generator."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


def build_request(genre: Any, bpm: Any, length: Any, unit: Any,
                  changes: list[tuple[Any, Any]]) -> PlanRequest:
    """``length_unit`` picks which of the two generator targets is set; other values are
    left to the generator (a wrong unit leaves both unset, so it answers length_both_or_none)."""
    length = _whole(length)  # 64.0 is 64 bars (JSON numbers and argparse floats)
    bars = length if unit == "bars" else None
    minutes = length if unit == "minutes" else None
    return PlanRequest(genre, bpm, target_bars=bars, target_minutes=minutes,
                       settings={k: _whole(v) for k, v in changes})


def plan_summary(plan: dict) -> dict[str, Any]:
    """What the model (and the CLI) is told about a plan: no energy nodes (G4 adds the
    timeline later)."""
    return {
        "bpm": plan["bpm"],
        "total_bars": plan["total_bars"],
        "duration_minutes": round(plan["total_bars"] * 4 / plan["bpm"], 2),
        "sections": copy.deepcopy(plan["sections"]),
        "settings": dict(plan["settings"]),
    }


class PlanSession:
    """The plans made in this chat, by ``plan_id``. Filled only by the ``plan_arrangement``
    handler from a plan that passed ``plan_problems`` inside ``generate_plan``."""

    def __init__(self) -> None:
        self.plans: dict[str, dict] = {}
        self._count = 0

    def plan(self, plan_id: str) -> dict | None:
        found = self.plans.get(plan_id)
        return copy.deepcopy(found) if found is not None else None

    def context(self) -> str:
        if not self.plans:
            return ""
        lines = ["Arrangement plans made in this chat (newest last); they exist only in this "
                 "chat:"]
        for plan_id, plan in self.plans.items():
            types = " > ".join(s["type"] for s in plan["sections"])
            lines.append(f"- {plan_id}: {plan['total_bars']} bars at {plan['bpm']} BPM ({types})")
        return "\n".join(lines)

    def tools(self) -> list[Tool]:
        schema = tool_input_schema()
        return [Tool(TOOL_NAME, schema["description"], schema, self._plan_arrangement,
                     approval=Approval.ROUTINE)]

    def _plan_arrangement(self, arguments: dict[str, Any]) -> ToolOutput:
        changes = [(c["key"], c["value"]) for c in arguments["setting_changes"]]
        if ("second_drop", "ask") in changes:
            raise ToolError(_text_second_drop_ask(),
                            files_written=0, live_writes=0,
                            details={"codes": ["second_drop_ask"]})
        req = build_request(arguments["genre"], arguments["bpm"], arguments["length"],
                            arguments["length_unit"], changes)
        result = generate_plan(req)
        if not result.ok:
            raise ToolError(refusal_text(result.errors), files_written=0, live_writes=0,
                            details={"codes": [e["code"] for e in result.errors]})
        self._count += 1
        plan_id = f"plan-{self._count}"
        self.plans[plan_id] = result.plan
        while len(self.plans) > MAX_PLANS:
            del self.plans[next(iter(self.plans))]
        content = {
            "plan_id": plan_id,
            **plan_summary(result.plan),
            "adjustments": result.adjustments,
            "warnings": result.warnings,
            "note": "Plan only: nothing was written to disk or to Live. Settings not listed "
                    "in setting_changes have their defaults (all settings are in the summary).",
        }
        return ToolOutput(content, files_written=0, live_writes=0)


__all__ = ["REFUSALS", "PlanSession", "build_request", "refusal_text", "tool_input_schema"]
