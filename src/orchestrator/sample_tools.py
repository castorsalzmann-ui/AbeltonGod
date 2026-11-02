"""The ``generate_sample`` copilot tool (#258, G7), category ``clap`` first.

Design: docs/research/2026-11-02_generate-sample-tool-design.md, option B. One generic tool
instead of one per category, because the strict kick tools already use 24 of 24 optional
parameters (kick 23 + import_sample 1). All six parameters are **required** (empty string /
empty list allowed), so the tool adds 0 optional parameters whatever categories follow.

``adjust`` is a list of ``{key, value}`` pairs. The schema has no ``minimum``/``maximum`` (strict
subset), so every check is local, against the category contract (``contracts/clap-params``):
unknown key, out-of-range, wrong integer-ness, a value outside an enum, a duplicate key, a
non-empty ``prompt``, a bad seed / variants / preset. All problems come back in one refusal;
nothing is clamped and nothing is written (D-002).

Files go through ``library.place_sample`` (WAV + sidecar 0.2, category ``clap``) into the clap
folder of the project the chat was started with; ids are ``clap-N`` in the same session table as
the kick ids, so ``import_sample`` takes them unchanged. Approval ``routine``; the kick tool is
not touched.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from audio_engine.clap_variants import make_variants
from audio_engine.presets import load_preset, preset_names
from library import place_sample
from orchestrator.kick_tools import (
    FILES_PER_KICK,
    KickSession,
    _whole_int,
    contract_input_schema,
)
from orchestrator.tools import Approval, Tool, ToolError, ToolOutput

TOOL_NAME = "generate_sample"
CLAP_CONTRACT = "clap-params.schema.json"
CATEGORIES = ("clap",)
# Contract fields given as their own tool argument (or fixed), not through `adjust`.
NOT_ADJUSTABLE = ("schema_version", "seed", "variants", "preset")


def _clap_schema() -> dict[str, Any]:
    return contract_input_schema(CLAP_CONTRACT)


def adjustable_keys() -> dict[str, dict[str, Any]]:
    """The clap contract's fields that `adjust` may set, with their schema."""
    return {k: v for k, v in _clap_schema()["properties"].items() if k not in NOT_ADJUSTABLE}


def _key_help() -> str:
    parts = []
    for key, spec in adjustable_keys().items():
        if "enum" in spec:
            rng = "one of " + "/".join(str(v) for v in spec["enum"])
        else:
            rng = f"{spec['minimum']}..{spec['maximum']}"
        parts.append(f"{key} ({'integer ' if spec.get('type') == 'integer' else ''}{rng}, "
                     f"default {spec.get('default', 'none')})")
    return "; ".join(parts)


def description() -> str:
    return (
        "Renders samples of one category with the local, deterministic engine into the sample "
        "folder of the user's Live project (WAV + sidecar each). Only category 'clap' exists "
        "so far. preset: one of " + ", ".join(preset_names("clap")) + " or '' for the engine "
        "defaults. prompt: must be empty for clap (no keyword parser yet). seed: integer "
        "0..4294967295. "
        "variants: how many claps, 1..8 (1 = only the given parameters; more = variations "
        "around them). adjust: parameters to change from the preset, one {key, value} each, "
        "[] = none; keys: " + _key_help() + ". A key or value outside these is refused and "
        "nothing is written: read the refusal and call again. Returns one sample_id per clap; "
        "pass it to import_sample. Does not touch the Live set."
    )


def tool_input_schema() -> dict[str, Any]:
    """Strict-subset schema, no optional parameter, no ``minimum``/``maximum``."""
    return {
        "type": "object",
        "description": description(),
        "properties": {
            "category": {"type": "string", "enum": list(CATEGORIES),
                         "description": "Sound category. Only clap so far."},
            "preset": {"type": "string",
                       "description": "Preset name of the category, or '' for the defaults."},
            "prompt": {"type": "string",
                       "description": "Free text for a keyword parser. Must be '' for clap."},
            "seed": {"type": "integer", "description": "Noise seed, 0..4294967295."},
            "variants": {"type": "integer", "description": "Number of samples, 1..8."},
            "adjust": {
                "type": "array",
                "description": "Parameter changes, one entry each; [] = none.",
                "items": {
                    "type": "object",
                    "description": "One parameter change.",
                    "properties": {
                        "key": {"type": "string", "description": "Parameter name."},
                        "value": {"type": "number", "description": "New value."},
                    },
                    "required": ["key", "value"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["category", "preset", "prompt", "seed", "variants", "adjust"],
        "additionalProperties": False,
    }


def _range_text(spec: dict[str, Any]) -> str:
    if "enum" in spec:
        return "one of " + ", ".join(str(v) for v in spec["enum"])
    return f"{'an integer ' if spec.get('type') == 'integer' else ''}from " \
           f"{spec['minimum']} to {spec['maximum']}"


def check_adjust(adjust: Any) -> tuple[dict[str, Any], list[str]]:
    """Validate ``adjust`` against the clap contract. Returns (accepted values, all problems).
    Out-of-range is a problem, never clamped; whole floats become ints for integer fields."""
    keys = adjustable_keys()
    problems: list[str] = []
    values: dict[str, Any] = {}
    if not isinstance(adjust, list):
        return {}, ["adjust must be a list of {key, value}"]
    for i, item in enumerate(adjust):
        if not isinstance(item, Mapping) or set(item) != {"key", "value"}:
            problems.append(f"adjust[{i}]: must be an object with exactly key and value")
            continue
        key, value = item["key"], item["value"]
        if key in NOT_ADJUSTABLE:
            problems.append(f"adjust[{i}]: {key!r} is its own argument of the tool, not an "
                            "adjust key")
            continue
        spec = keys.get(key) if isinstance(key, str) else None
        if spec is None:
            problems.append(f"adjust[{i}]: unknown key {key!r}; known keys: "
                            f"{', '.join(keys)}")
            continue
        if key in values:
            problems.append(f"adjust[{i}]: duplicate key {key!r}")
            continue
        if isinstance(value, bool) or not isinstance(value, int | float) or (
                isinstance(value, float) and not math.isfinite(value)):
            problems.append(f"adjust[{i}]: {key} must be a finite number, got {value!r}")
            continue
        if spec.get("type") == "integer":
            whole = _whole_int(value)
            if whole is None:
                problems.append(f"adjust[{i}]: {key} must be a whole number, got {value!r}")
                continue
            value = whole
        ok = (value in spec["enum"]) if "enum" in spec else (
            spec["minimum"] <= value <= spec["maximum"])
        if not ok:
            problems.append(f"adjust[{i}]: {key} must be {_range_text(spec)}, got {value!r}")
            continue
        values[key] = value
    return values, problems


def build_request(arguments: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The clap parameter dict for these tool arguments, and every problem found."""
    problems: list[str] = []
    props = _clap_schema()["properties"]
    if arguments.get("category") not in CATEGORIES:
        problems.append(f"category must be one of {list(CATEGORIES)}")
    if arguments.get("prompt") != "":
        problems.append("prompt must be '' for clap (there is no keyword parser yet); put "
                        "changes into adjust")
    seed = _whole_int(arguments.get("seed"))
    if seed is None or not props["seed"]["minimum"] <= seed <= props["seed"]["maximum"]:
        problems.append(f"seed must be an integer {_range_text(props['seed'])}, got "
                        f"{arguments.get('seed')!r}")
    variants = _whole_int(arguments.get("variants"))
    if variants is None or not props["variants"]["minimum"] <= variants <= (
            props["variants"]["maximum"]):
        problems.append(f"variants must be an integer {_range_text(props['variants'])}, got "
                        f"{arguments.get('variants')!r}")
    preset = arguments.get("preset")
    base: dict[str, Any] = {"schema_version": "0.1"}
    if preset:
        names = preset_names("clap")
        if preset not in names:
            problems.append(f"unknown preset {preset!r}; presets: {', '.join(names)} (or '' "
                            "for the defaults)")
        else:
            base.update(load_preset(preset, "clap"))
    adjusted, adjust_problems = check_adjust(arguments.get("adjust"))
    problems += adjust_problems
    base.update(adjusted)
    if seed is not None:
        base["seed"] = seed
    else:
        base.setdefault("seed", 0)
    base["variants"] = variants if variants is not None else 1
    return base, problems


class SampleTools:
    """``generate_sample`` on top of a ``KickSession`` (its project folder and sample table)."""

    def __init__(self, session: KickSession) -> None:
        self.session = session

    def tools(self, files_per_request: int | None = None) -> list[Tool]:
        schema = tool_input_schema()
        text = schema["description"]
        max_variants = int(_clap_schema()["properties"]["variants"]["maximum"])
        if files_per_request is not None:
            text += (f" At most {int(files_per_request) // FILES_PER_KICK} samples per request "
                     f"({FILES_PER_KICK} files each, request limit {int(files_per_request)} "
                     "files).")
        schema["description"] = text

        def sample_files(arguments: Any) -> int:
            """Files one call may write, read before validation (as generate_kick)."""
            if not isinstance(arguments, Mapping):
                return 0
            n = _whole_int(arguments.get("variants", 1))
            return 0 if n is None or n < 1 else FILES_PER_KICK * n

        return [Tool(TOOL_NAME, text, schema, self._generate, approval=Approval.ROUTINE,
                     max_files_written=FILES_PER_KICK * max_variants, files_for=sample_files)]

    def _generate(self, arguments: dict[str, Any]) -> ToolOutput:
        session = self.session
        problem = session.project_problem(session.project_dir)
        if problem is not None:
            raise ToolError(f"the project folder is not usable now: {problem}",
                            files_written=0, live_writes=0)
        request, problems = build_request(arguments)
        if problems:
            raise ToolError("generate_sample refused, nothing was written: "
                            + "; ".join(problems), files_written=0, live_writes=0,
                            details={"problems": copy.deepcopy(problems)})
        try:
            variants = make_variants(request, request["variants"])
        except ValueError as exc:  # ClapParamsError: the contract caught what we did not
            raise ToolError(f"clap parameters refused: {exc}", files_written=0,
                            live_writes=0) from exc
        seed = request["seed"]
        stem = f"{request.get('preset') or 'clap'}_s{seed}"
        made: list[dict[str, Any]] = []
        files = 0
        for i, params in enumerate(variants):
            note = (f"Copilot generate_sample: clap variant {i} of {len(variants)}, "
                    f"base seed {seed}.")
            try:
                wav = place_sample("clap", params, session.project_dir, name=f"{stem}_v{i}",
                                   description=note)
            except (ValueError, OSError) as exc:  # place_sample removed what it wrote
                raise session._partial(made, files, f"clap {i} of {len(variants)} was not "
                                       f"written: {type(exc).__name__}: {exc}") from exc
            files += FILES_PER_KICK
            try:
                entry, info = session._pin(wav, i, int(params["seed"]), "clap")
            except ToolError as exc:
                raise session._partial(made, files, str(exc)) from exc
            made.append({"sample_id": entry.sample_id, "file": entry.file, **info})
        return ToolOutput({"samples": made, "category": "clap",
                           "folder": str(wav.parent)},
                          files_written=files, live_writes=0)


__all__ = ["SampleTools", "build_request", "check_adjust", "tool_input_schema"]
