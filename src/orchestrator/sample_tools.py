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

Which category runs is decided by the ``ADAPTERS`` table (#273): a category without a row is
refused before approval and before any file. Files go through ``library.place_sample`` (WAV +
sidecar 0.2, category ``clap``) into the clap folder of the project the chat was started with;
ids are ``<category>-N`` in the same session table as the kick ids, so ``import_sample`` takes
them unchanged. Approval ``routine``; the kick tool is not touched.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from audio_engine.clap_variants import make_variants
from audio_engine.hat_variants import make_variants as hat_variants
from audio_engine.presets import load_preset, preset_names
from audio_engine.snare_variants import make_variants as snare_variants
from library import place_sample
from orchestrator.kick_tools import (
    FILES_PER_KICK,
    KickSession,
    _whole_int,
    contract_input_schema,
)
from orchestrator.tools import Approval, Tool, ToolError, ToolOutput

TOOL_NAME = "generate_sample"
# Contract fields given as their own tool argument (or fixed), not through `adjust`.
NOT_ADJUSTABLE = ("schema_version", "seed", "variants", "preset")


@dataclass(frozen=True)
class CategoryAdapter:
    """Everything the generic tool needs to know about one sample category (#273).

    Adding a category (hat, snare) is one row in ``ADAPTERS``: no change to the tool's schema
    shape (still 0 optional parameters), only to the ``category`` enum and the description.
    """

    name: str  # category name, also the sidecar category and the sample_id prefix
    contract: str  # params schema file in contracts/
    make_variants: Callable[[dict[str, Any], int], list[dict[str, Any]]]
    schema_version: str = "0.1"  # `schema_version` of the params object
    accepts_prompt: bool = False  # False: `prompt` must be '' (no keyword parser yet)
    noun: str = "sample"  # singular, for the tool text ("claps")
    files_per_variant: int = FILES_PER_KICK  # WAV + sidecar
    place: Callable[..., Any] = place_sample  # (category, params, project_dir, name=, description=)
    preset_category: str | None = None  # preset folder, default: ``name``

    @property
    def id_prefix(self) -> str:
        return f"{self.name}-"

    @property
    def presets(self) -> list[str]:
        return preset_names(self.preset_category or self.name)

    def schema(self) -> dict[str, Any]:
        return contract_input_schema(self.contract)

    def load_preset(self, name: str) -> dict[str, Any]:
        return load_preset(name, self.preset_category or self.name)


ADAPTERS: Mapping[str, CategoryAdapter] = {
    "clap": CategoryAdapter("clap", "clap-params.schema.json", make_variants, noun="clap"),
    "hat": CategoryAdapter("hat", "hat-params.schema.json", hat_variants, noun="hat"),
    "snare": CategoryAdapter("snare", "snare-params.schema.json", snare_variants, noun="snare"),
}
CLAP_CONTRACT = ADAPTERS["clap"].contract
CATEGORIES = tuple(ADAPTERS)


def _adapters(adapters: Mapping[str, CategoryAdapter] | None) -> Mapping[str, CategoryAdapter]:
    return ADAPTERS if adapters is None else adapters


def adjustable_keys(adapter: CategoryAdapter | None = None) -> dict[str, dict[str, Any]]:
    """The category contract's fields that `adjust` may set, with their schema (default clap)."""
    adapter = adapter or ADAPTERS["clap"]
    return {k: v for k, v in adapter.schema()["properties"].items() if k not in NOT_ADJUSTABLE}


def _key_help(adapter: CategoryAdapter) -> str:
    parts = []
    for key, spec in adjustable_keys(adapter).items():
        if "enum" in spec:
            rng = "one of " + "/".join(str(v) for v in spec["enum"])
        elif "oneOf" in spec:
            rng = _range_text(spec)
        else:
            rng = f"{spec['minimum']}..{spec['maximum']}"
        parts.append(f"{key} ({'integer ' if spec.get('type') == 'integer' else ''}{rng}, "
                     f"default {spec.get('default', 'none')})")
    return "; ".join(parts)


def _segment(a: CategoryAdapter) -> str:
    props = a.schema()["properties"]
    prompt = ("free text for the keyword parser" if a.accepts_prompt else
              f"must be empty for {a.name} (no keyword parser yet)")
    return (
        f"preset: one of {', '.join(a.presets)} or '' for the engine defaults. "
        f"prompt: {prompt}. seed: integer {props['seed']['minimum']}..{props['seed']['maximum']}. "
        f"variants: how many {a.noun}s, {props['variants']['minimum']}.."
        f"{props['variants']['maximum']} (1 = only the given parameters; more = variations "
        f"around them). adjust: parameters to change from the preset, one {{key, value}} each, "
        f"[] = none; keys: {_key_help(a)}."
    )


def description(adapters: Mapping[str, CategoryAdapter] | None = None) -> str:
    table = _adapters(adapters)
    one = len(table) == 1
    names = list(table)
    intro = ("Renders samples of one category with the local, deterministic engine into the "
             "sample folder of the user's Live project (WAV + sidecar each). ")
    if one:
        body = f"Only category '{names[0]}' exists so far. " + _segment(table[names[0]])
    else:
        body = f"Categories: {', '.join(names)}. " + " ".join(
            f"For category '{n}': {_segment(a)}" for n, a in table.items())
    nouns = " / ".join(a.noun for a in table.values())
    return (intro + body + " A key or value outside these is refused and nothing is written: "
            f"read the refusal and call again. Returns one sample_id per {nouns}; pass it to "
            "import_sample. Does not touch the Live set.")


def tool_input_schema(adapters: Mapping[str, CategoryAdapter] | None = None) -> dict[str, Any]:
    """Strict-subset schema, no optional parameter, no ``minimum``/``maximum``. Its shape does
    not depend on the number of categories; only the enum and the texts do."""
    table = _adapters(adapters)
    names = list(table)
    no_prompt = [n for n, a in table.items() if not a.accepts_prompt]
    return {
        "type": "object",
        "description": description(table),
        "properties": {
            "category": {"type": "string", "enum": names,
                         "description": (f"Sound category. Only {names[0]} so far."
                                         if len(names) == 1 else
                                         f"Sound category: {', '.join(names)}.")},
            "preset": {"type": "string",
                       "description": "Preset name of the category, or '' for the defaults."},
            "prompt": {"type": "string",
                       "description": "Free text for a keyword parser."
                       + (f" Must be '' for {', '.join(no_prompt)}." if no_prompt else "")},
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


def _one_of(spec: dict[str, Any]) -> tuple[list[Any], dict[str, Any] | None]:
    """(consts, numeric range branch) of a ``oneOf`` spec such as hat ``choke_ms``."""
    consts = [b["const"] for b in spec["oneOf"] if "const" in b]
    ranges = [b for b in spec["oneOf"] if "minimum" in b]
    return consts, (ranges[0] if ranges else None)


def _range_text(spec: dict[str, Any]) -> str:
    if "oneOf" in spec:
        consts, rng = _one_of(spec)
        text = " or ".join(str(c) for c in consts)
        return f"{text} or from {rng['minimum']} to {rng['maximum']}" if rng else text
    if "enum" in spec:
        return "one of " + ", ".join(str(v) for v in spec["enum"])
    return f"{'an integer ' if spec.get('type') == 'integer' else ''}from " \
           f"{spec['minimum']} to {spec['maximum']}"


def check_adjust(adjust: Any, adapter: CategoryAdapter | None = None,
                 ) -> tuple[dict[str, Any], list[str]]:
    """Validate ``adjust`` against the clap contract. Returns (accepted values, all problems).
    Out-of-range is a problem, never clamped; whole floats become ints for integer fields."""
    keys = adjustable_keys(adapter)
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
        if "oneOf" in spec:
            consts, rng = _one_of(spec)
            ok = value in consts or (rng is not None
                                     and rng["minimum"] <= value <= rng["maximum"])
        else:
            ok = (value in spec["enum"]) if "enum" in spec else (
                spec["minimum"] <= value <= spec["maximum"])
        if not ok:
            problems.append(f"adjust[{i}]: {key} must be {_range_text(spec)}, got {value!r}")
            continue
        values[key] = value
    return values, problems


def build_request(arguments: Mapping[str, Any],
                  adapters: Mapping[str, CategoryAdapter] | None = None,
                  ) -> tuple[dict[str, Any], list[str]]:
    """The parameter dict for these tool arguments, and every problem found. A category with
    no adapter in the table gets the "not available" refusal and nothing else is looked at."""
    table = _adapters(adapters)
    category = arguments.get("category")
    adapter = table.get(category) if isinstance(category, str) else None
    if adapter is None:
        return {}, [f"category {category!r} is not available yet; available: "
                    f"{', '.join(table)}"]
    problems: list[str] = []
    props = adapter.schema()["properties"]
    if not adapter.accepts_prompt and arguments.get("prompt") != "":
        problems.append(f"prompt must be '' for {adapter.name} (there is no keyword parser "
                        "yet); put changes into adjust")
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
    base: dict[str, Any] = {"schema_version": adapter.schema_version}
    if preset:
        names = adapter.presets
        if preset not in names:
            problems.append(f"unknown preset {preset!r}; presets: {', '.join(names)} (or '' "
                            "for the defaults)")
        else:
            base.update(adapter.load_preset(preset))
    adjusted, adjust_problems = check_adjust(arguments.get("adjust"), adapter)
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

    def __init__(self, session: KickSession,
                 adapters: Mapping[str, CategoryAdapter] | None = None) -> None:
        self.session = session
        self.adapters = _adapters(adapters)  # the category table; default: ADAPTERS

    def tools(self, files_per_request: int | None = None) -> list[Tool]:
        schema = tool_input_schema(self.adapters)
        text = schema["description"]
        table = self.adapters
        max_files = max(a.files_per_variant * int(a.schema()["properties"]["variants"]["maximum"])
                        for a in table.values())
        if files_per_request is not None:
            text += (f" At most {int(files_per_request) // FILES_PER_KICK} samples per request "
                     f"({FILES_PER_KICK} files each, request limit {int(files_per_request)} "
                     "files).")
        schema["description"] = text

        def sample_files(arguments: Any) -> int:
            """Files one call may write, read before validation (as generate_kick)."""
            if not isinstance(arguments, Mapping):
                return 0
            adapter = table.get(arguments.get("category"))
            n = _whole_int(arguments.get("variants", 1))
            if adapter is None or n is None or n < 1:
                return 0
            return adapter.files_per_variant * n

        return [Tool(TOOL_NAME, text, schema, self._generate, approval=Approval.ROUTINE,
                     max_files_written=max_files, files_for=sample_files)]

    def _generate(self, arguments: dict[str, Any]) -> ToolOutput:
        session = self.session
        problem = session.project_problem(session.project_dir)
        if problem is not None:
            raise ToolError(f"the project folder is not usable now: {problem}",
                            files_written=0, live_writes=0)
        request, problems = build_request(arguments, self.adapters)
        if problems:
            raise ToolError("generate_sample refused, nothing was written: "
                            + "; ".join(problems), files_written=0, live_writes=0,
                            details={"problems": copy.deepcopy(problems)})
        adapter = self.adapters[arguments["category"]]  # build_request refused unknown ones
        try:
            variants = adapter.make_variants(request, request["variants"])
        except ValueError as exc:  # the category's params error: the contract caught more
            raise ToolError(f"{adapter.name} parameters refused: {exc}", files_written=0,
                            live_writes=0) from exc
        seed = request["seed"]
        stem = f"{request.get('preset') or adapter.name}_s{seed}"
        made: list[dict[str, Any]] = []
        files = 0
        for i, params in enumerate(variants):
            note = (f"Copilot generate_sample: {adapter.name} variant {i} of {len(variants)}, "
                    f"base seed {seed}.")
            try:
                wav = adapter.place(adapter.name, params, session.project_dir,
                                    name=f"{stem}_v{i}", description=note)
            except (ValueError, OSError) as exc:  # place_sample removed what it wrote
                raise session._partial(made, files, f"{adapter.name} {i} of {len(variants)} "
                                       f"was not written: {type(exc).__name__}: {exc}") from exc
            files += adapter.files_per_variant
            try:
                entry, info = session._pin(wav, i, int(params["seed"]), adapter.name)
            except ToolError as exc:
                raise session._partial(made, files, str(exc)) from exc
            made.append({"sample_id": entry.sample_id, "file": entry.file, **info})
        return ToolOutput({"samples": made, "category": adapter.name,
                           "folder": str(wav.parent)},
                          files_written=files, live_writes=0)


__all__ = ["ADAPTERS", "CategoryAdapter", "SampleTools", "build_request", "check_adjust",
           "tool_input_schema"]
