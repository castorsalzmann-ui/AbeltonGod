"""Command line for kick presets and variants (Phase 01b, issue #3).

    python -m audio_engine.kick --preset NAME [--variants N] --out DIR
                                [--seed INT] [--set FIELD=VALUE ...]
                                [--category kick|clap|hat|snare|rim|bass|laser]
    python -m audio_engine.kick --list-presets
                                [--category kick|clap|hat|snare|rim|bass|laser]

``--category clap`` (#231) renders clap presets from ``presets/clap/`` and writes
``clap-params`` sidecars; the default is ``kick``.

Writes ``<preset>_s<seed>_v<i>[_custom].wav`` + ``.json`` for ``i = 0 … N-1`` into ``DIR``
(``<seed>`` is the base seed; ``_custom`` when ``--set`` changed a value). Existing files are
never overwritten: ``write_kick`` appends ``_002``, ``_003`` … (D-006). Variant 0 is the preset
itself (or the preset with the ``--seed`` / ``--set`` changes).

Every parameter (preset + ``--seed`` + ``--set`` + every variant) is validated against the
contract before anything is written or any folder is created.

Exit codes: 0 all files written · 2 usage or parameter error (nothing written) · 3 output error
(folder not creatable or writable, disk full, no free name); files written before the error
stay and are listed on stdout · 130 interrupted (Ctrl+C) · 1 anything else (traceback).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, TextIO

from . import (
    bass_variants,
    clap_variants,
    hat_variants,
    laser_variants,
    rim_variants,
    snare_variants,
)
from .bass import BassParamsError, resolve_bass_params
from .categories import CategoryUnavailable, get_category
from .clap import ClapParamsError, resolve_clap_params
from .hat import HatParamsError, resolve_hat_params
from .io import write_kick
from .laser import LaserParamsError, resolve_laser_params, v02_properties
from .params import KickParamsError, resolve_kick_params
from .presets import UnknownPresetError, describe, load_preset, preset_names
from .prompt import PromptError, parse_prompt
from .rim import RimParamsError, resolve_rim_params
from .snare import SnareParamsError, resolve_snare_params
from .variants import make_variants

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_OUTPUT = 3
EXIT_INTERRUPTED = 130

# Fields --set may not change: the format version and the batch size have their own meaning
# (--variants), the base seed has --seed, and preset is the name the values came from.
NOT_SETTABLE = ("schema_version", "variants", "seed", "preset")
MAX_DESCRIPTION = 500  # sample-metadata: description maxLength


class UsageError(ValueError):
    """Bad command line value (exit 2)."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m audio_engine.kick",
        description="Render sample presets and variants (--category kick, clap, hat, snare, "
        "rim, bass, laser) as WAV + sidecar JSON; laser files are 2-channel.",
    )
    parser.add_argument("--preset", help="preset name (see --list-presets)")
    parser.add_argument(
        "--variants", type=int, default=1, help="number of kicks, 1-8 (default 1: the preset)"
    )
    parser.add_argument("--out", help="output folder (created if missing)")
    parser.add_argument("--seed", type=int, help="replace the preset's base seed")
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help="set one parameter (a number), repeatable; e.g. --set pitch_decay_ms=15. Laser: "
        "also the v0.2 fields incl. text values, e.g. --set salvo_count=3 --set "
        "salvo_pan_mode=alternate_lr --set echo_sync=1/8 --set reverb_mix=0.3 --set lp_hz=3000",
    )
    parser.add_argument(
        "--category", choices=("kick", "clap", "hat", "snare", "rim", "bass", "laser"),
        default="kick",
        help="sound category (default kick)",
    )
    parser.add_argument(
        "--prompt",
        help="keyword prompt instead of --preset, e.g. 'sub:1.5, punch:1.2, dunkel, note:Am'",
    )
    parser.add_argument(
        "--list-presets", action="store_true", help="list preset names and descriptions"
    )
    return parser


def parse_overrides(
    items: list[str], text_fields: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """``["a=1", "b=2.5"]`` -> ``{"a": 1, "b": 2.5}``. Values must be finite JSON numbers.

    ``text_fields`` (laser v0.2 text enums such as ``salvo_pan_mode=alternate_lr`` or
    ``echo_sync=1/8``): for these a value that is not a number is kept as text; the contract
    then accepts or rejects it. Every other field stays numbers-only.
    """
    out: dict[str, Any] = {}
    for item in items:
        field, sep, text = item.partition("=")
        field = field.strip()
        if not sep or not field:
            raise UsageError(f"--set {item!r}: expected FIELD=VALUE, e.g. pitch_decay_ms=15")
        if field in NOT_SETTABLE:
            hint = {"variants": " (use --variants)", "seed": " (use --seed)"}.get(field, "")
            raise UsageError(f"--set {field}: this field cannot be set{hint}")
        if field in out:
            raise UsageError(f"--set {field}: given more than once")
        try:
            value = json.loads(text.strip(), parse_constant=_reject_constant)
        except ValueError:
            value = None
        if field in text_fields and value is None and text.strip():
            out[field] = text.strip()
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise UsageError(f"--set {field}={text!r}: value must be a number")
        if not math.isfinite(value):
            raise UsageError(f"--set {field}={text!r}: value must be finite")
        out[field] = value
    return out


def plan(args: argparse.Namespace) -> tuple[str, list[dict[str, Any]], list[str], list[str]]:
    """Validate everything and return ``(out_dir, variants, stems, descriptions)``.

    Raises :class:`UsageError`, :class:`UnknownPresetError` or ``KickParamsError``; touches
    no file.
    """
    if getattr(args, "prompt", None) is not None:
        return _plan_prompt(args)
    if not args.preset:
        raise UsageError("--preset is required (see --list-presets)")
    if not args.out:
        raise UsageError("--out is required")
    category = getattr(args, "category", "kick")  # callers build their own Namespace
    text_fields = frozenset(
        k for k, spec in v02_properties().items() if "enum" in spec and k != "filter_slope"
    ) if category == "laser" else frozenset()
    overrides = parse_overrides(args.overrides, text_fields)
    base = dict(load_preset(args.preset, category))
    if args.seed is not None:
        base["seed"] = args.seed
    base.update(overrides)
    if category == "laser" and base.get("schema_version") == "0.1" and any(
        k in v02_properties() for k in overrides
    ):  # --set of a v0.2 field (salvo_*, lp_*, hp_hz, echo_sync, reverb_* ...) selects v0.2
        base["schema_version"] = "0.2"
    base["variants"] = args.variants  # validated by the contract (1 … 8)
    request = base
    resolve, make = {
        "kick": (resolve_kick_params, make_variants),
        "clap": (resolve_clap_params, clap_variants.make_variants),
        "hat": (resolve_hat_params, hat_variants.make_variants),
        "snare": (resolve_snare_params, snare_variants.make_variants),
        "rim": (resolve_rim_params, rim_variants.make_variants),
        "bass": (resolve_bass_params, bass_variants.make_variants),
        "laser": (resolve_laser_params, laser_variants.make_variants),
    }[category]
    base = resolve(request)
    # The request, not its resolved form: variants of a tail_note / length_beats request keep
    # the note and the -60 dB rule (#120), which the resolved form no longer shows.
    variants = make(request, base["variants"])
    suffix = "_custom" if overrides else ""
    stem = f"{args.preset}_s{base['seed']}"
    stems = [f"{stem}_v{i}{suffix}" for i in range(len(variants))]
    text = describe(args.preset, category)
    custom = ", ".join(f"{k}={v}" for k, v in overrides.items())
    descriptions = []
    n, seed = len(variants), base["seed"]
    for i in range(n):
        d = f"Preset {args.preset}: {text} Variant {i} of {n}, base seed {seed}."
        if custom:
            d += f" Custom values: {custom}."
        descriptions.append(d[:MAX_DESCRIPTION])
    return args.out, variants, stems, descriptions


def _plan_prompt(
    args: argparse.Namespace,
) -> tuple[str, list[dict[str, Any]], list[str], list[str]]:
    """``--prompt`` path (issue 233): keyword prompt instead of preset; the prompt text is the
    description. Adjustments are kept on ``args.prompt_adjustments`` for the caller to print."""
    if args.preset or args.overrides:
        raise UsageError("--prompt cannot be combined with --preset or --set")
    if getattr(args, "category", "kick") != "kick":
        raise UsageError(
            "--prompt is a kick vocabulary, not usable with --category clap, hat, snare, rim "
            "or bass"
        )
    if not args.out:
        raise UsageError("--out is required")
    try:
        parsed = parse_prompt(args.prompt)
    except PromptError as exc:
        raise UsageError(str(exc)) from exc
    request = dict(parsed.params)
    if args.seed is not None:
        if "seed" in parsed.slots and request["seed"] != args.seed:
            raise UsageError("--seed conflicts with seed: in the prompt")
        request["seed"] = args.seed
    if args.variants != 1:
        if "variants" in parsed.slots and request["variants"] != args.variants:
            raise UsageError("--variants conflicts with variants: in the prompt")
        request["variants"] = args.variants
    args.prompt_adjustments = [str(a) for a in parsed.adjustments]
    base = resolve_kick_params(request)
    variants = make_variants(request, base["variants"])
    stem = f"prompt_s{base['seed']}"
    stems = [f"{stem}_v{i}" for i in range(len(variants))]
    n = len(variants)
    descriptions = [
        f"Prompt: {args.prompt.strip()} | variant {i} of {n}, base seed {base['seed']}."[
            :MAX_DESCRIPTION
        ]
        for i in range(n)
    ]
    return args.out, variants, stems, descriptions


def main(argv: list[str] | None = None, stdout: TextIO | None = None,
         stderr: TextIO | None = None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    try:
        return _main(argv, stdout, stderr)
    except KeyboardInterrupt:
        print("Interrupted.", file=stderr)
        return EXIT_INTERRUPTED


def _main(argv: list[str] | None, stdout: TextIO, stderr: TextIO) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse already printed the message
        return EXIT_OK if exc.code == 0 else EXIT_USAGE

    try:
        get_category(args.category)  # a contract category without a voice is refused here
    except CategoryUnavailable as exc:
        print(f"error: {exc}", file=stderr)
        return EXIT_USAGE

    if args.list_presets:
        for name in preset_names(args.category):
            print(f"{name:14s} {describe(name, args.category)}", file=stdout)
        return EXIT_OK

    try:
        out_dir, variants, stems, descriptions = plan(args)
    except (UsageError, UnknownPresetError, KickParamsError, ClapParamsError,
                HatParamsError, SnareParamsError, RimParamsError, BassParamsError,
                LaserParamsError) as exc:
        print(f"error: {exc}", file=stderr)
        return EXIT_USAGE

    for line in getattr(args, "prompt_adjustments", []):
        print(f"adjusted: {line}", file=stdout)
    for i, (params, stem, description) in enumerate(zip(variants, stems, descriptions,
                                                        strict=True)):
        try:
            extra = {} if args.category == "kick" else {"category": args.category}
            wav_path, json_path = write_kick(
                params, out_dir, name=stem, description=description, **extra
            )
        except OSError as exc:  # includes FileExistsError (no free name) and disk full
            print(
                f"error: variant {i} ({stem}) not written: {exc}. "
                f"{i} file pair(s) written before it stay.",
                file=stderr,
            )
            return EXIT_OUTPUT
        print(_summary(wav_path, json_path), file=stdout)
        stdout.flush()
    return EXIT_OK


def _summary(wav_path: Path, json_path: Path) -> str:
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    features = meta["features"]

    def fmt(value: float | None, unit: str) -> str:
        return "n/a" if value is None else f"{value:g} {unit}"

    if meta["category"] != "kick":
        return (
            f"{wav_path}  centroid={fmt(features.get('spectral_centroid_hz'), 'Hz')}  "
            f"t60={fmt(features.get('t60_ms'), 'ms')}  "
            f"peak={fmt(features['peak_dbfs'], 'dBFS')}"
        )

    return (
        f"{wav_path}  f0={fmt(features.get('fundamental_hz'), 'Hz')}  "
        f"d40={fmt(features.get('decay_40db_ms'), 'ms')}  "
        f"peak={fmt(features['peak_dbfs'], 'dBFS')}"
    )


def _reject_constant(name: str) -> float:
    raise ValueError(name)
