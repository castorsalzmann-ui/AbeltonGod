"""Command line for kick presets and variants (Phase 01b, issue #3).

    python -m audio_engine.kick --preset NAME [--variants N] --out DIR
                                [--seed INT] [--set FIELD=VALUE ...]
    python -m audio_engine.kick --list-presets

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

from .io import write_kick
from .params import KickParamsError, resolve_kick_params
from .presets import UnknownPresetError, describe, load_preset, preset_names
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
        description="Render kick presets and variants as 24-bit WAV + sidecar JSON.",
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
        help="set one kick parameter (a number), repeatable; e.g. --set pitch_decay_ms=15",
    )
    parser.add_argument(
        "--list-presets", action="store_true", help="list preset names and descriptions"
    )
    return parser


def parse_overrides(items: list[str]) -> dict[str, float | int]:
    """``["a=1", "b=2.5"]`` -> ``{"a": 1, "b": 2.5}``. Values must be finite JSON numbers."""
    out: dict[str, float | int] = {}
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
    if not args.preset:
        raise UsageError("--preset is required (see --list-presets)")
    if not args.out:
        raise UsageError("--out is required")
    overrides = parse_overrides(args.overrides)
    base = dict(load_preset(args.preset))
    if args.seed is not None:
        base["seed"] = args.seed
    base.update(overrides)
    base["variants"] = args.variants  # validated by the contract (1 … 8)
    base = resolve_kick_params(base)
    variants = make_variants(base, base["variants"])
    suffix = "_custom" if overrides else ""
    stem = f"{args.preset}_s{base['seed']}"
    stems = [f"{stem}_v{i}{suffix}" for i in range(len(variants))]
    text = describe(args.preset)
    custom = ", ".join(f"{k}={v}" for k, v in overrides.items())
    descriptions = []
    n, seed = len(variants), base["seed"]
    for i in range(n):
        d = f"Preset {args.preset}: {text} Variant {i} of {n}, base seed {seed}."
        if custom:
            d += f" Custom values: {custom}."
        descriptions.append(d[:MAX_DESCRIPTION])
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

    if args.list_presets:
        for name in preset_names():
            print(f"{name:14s} {describe(name)}", file=stdout)
        return EXIT_OK

    try:
        out_dir, variants, stems, descriptions = plan(args)
    except (UsageError, UnknownPresetError, KickParamsError) as exc:
        print(f"error: {exc}", file=stderr)
        return EXIT_USAGE

    for i, (params, stem, description) in enumerate(zip(variants, stems, descriptions,
                                                        strict=True)):
        try:
            wav_path, json_path = write_kick(params, out_dir, name=stem, description=description)
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
    features = json.loads(json_path.read_text(encoding="utf-8"))["features"]

    def fmt(value: float | None, unit: str) -> str:
        return "n/a" if value is None else f"{value:g} {unit}"

    return (
        f"{wav_path}  f0={fmt(features.get('fundamental_hz'), 'Hz')}  "
        f"d40={fmt(features.get('decay_40db_ms'), 'ms')}  "
        f"peak={fmt(features['peak_dbfs'], 'dBFS')}"
    )


def _reject_constant(name: str) -> float:
    raise ValueError(name)
