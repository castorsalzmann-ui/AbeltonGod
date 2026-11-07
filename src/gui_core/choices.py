"""Choice log (#110, D-032): the user's verdicts on sample files. No Qt.

Format: ``contracts/choice-log.schema.json`` v0.1 and docs/INTERFACES.md "Choice log". One JSONL
file ``choices.jsonl`` next to ``settings.json`` in the user config dir. Nothing here sends
anything anywhere.

* :func:`make_entry` builds one entry for a WAV below the output folder: the file's real
  SHA-256, its path relative to the output folder, and from its sidecar the category, engine,
  preset, seed and a verbatim copy of ``parameters``.
* :meth:`ChoiceLog.append` validates the entry against the contract and appends it as one line
  with a single write. A line a crash left without its newline is closed first, so the new
  entry always starts on its own line (the broken line is then skipped by readers).
* :meth:`ChoiceLog.read` never stops at a bad line: invalid UTF-8, invalid JSON, entries the
  contract refuses and times that are not a real instant (2026-02-30, which the contract's
  pattern lets through) are skipped and counted. It never repairs the file.
* :func:`current_verdicts` is the newest entry per SHA-256 by parsed instant (equal instants:
  the later line), never by comparing the time strings.

A ``ChoiceLog`` without a path keeps its lines in memory (tests, the tour, a main window without
a settings file), with the same parsing code.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
SCHEMA_FILE = CONTRACTS_DIR / "choice-log.schema.json"
FILE_NAME = "choices.jsonl"
VERDICTS = ("favourite", "reject", "neutral")
LABELS = {"favourite": "Favorit", "reject": "Passt nicht", "neutral": "Neutral"}
MAX_NOTE = 2000
_CHUNK = 1 << 20

_validator: Draft202012Validator | None = None


def validator() -> Draft202012Validator:
    global _validator
    if _validator is None:
        _validator = Draft202012Validator(json.loads(SCHEMA_FILE.read_text(encoding="utf-8")))
    return _validator


def problems(entry: Any) -> list[str]:
    """Contract errors of one entry (empty = valid), each as 'path: message'."""
    out = []
    for e in validator().iter_errors(entry):
        where = "/".join(str(p) for p in e.absolute_path) or "(entry)"
        out.append(f"{where}: {e.message}")
    return out


class ChoiceError(ValueError):
    """An entry cannot be built or is refused by the contract (message in German)."""


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def instant(text: str) -> datetime:
    """The parsed instant of a contract ``time`` (always has an offset)."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _read_sidecar(wav: Path) -> dict | None:
    try:
        meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def _sidecar_block(meta: dict) -> dict | None:
    engine = meta.get("engine")
    if not isinstance(engine, dict):
        return None
    name, version = engine.get("name"), engine.get("version")
    if not (isinstance(name, str) and name and isinstance(version, str) and version):
        return None
    params = meta.get("parameters")
    params = params if isinstance(params, dict) else None
    preset = params.get("preset") if params else None
    seed = params.get("seed") if params else None
    block: dict[str, Any] = {
        "engine": {"name": name, "version": version},
        "preset": preset if isinstance(preset, str) else None,
        "seed": seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
    }
    if params is not None:
        block["parameters"] = params  # verbatim copy (#477 review, option a)
    return block


def make_entry(wav: Path, output_dir: Path, verdict: str, note: str = "",
               now: str | None = None) -> dict:
    """The entry for ``wav`` (below ``output_dir``). Raises :class:`ChoiceError` when the file
    is outside the output folder, cannot be read, or the result breaks the contract."""
    if verdict not in VERDICTS:
        raise ChoiceError(f"Unbekanntes Urteil: {verdict!r}")
    wav, output_dir = Path(wav), Path(output_dir)
    try:
        rel = wav.resolve().relative_to(output_dir.resolve())
    except (OSError, ValueError):
        raise ChoiceError(f"{wav.name} liegt nicht im Ausgabeordner {output_dir}") from None
    try:
        sha = file_sha256(wav)
    except OSError as exc:
        raise ChoiceError(f"{wav.name} nicht lesbar: {type(exc).__name__}") from None
    meta = _read_sidecar(wav)
    category = None
    sidecar = None
    if meta is not None:
        cat = meta.get("category", "kick")  # first-format sidecars have no category: kicks
        category = cat if isinstance(cat, str) else None
        sidecar = _sidecar_block(meta)
    entry: dict[str, Any] = {
        "schema_version": "0.1",
        "time": now or utc_now(),
        "verdict": verdict,
        "sample": {"path": rel.as_posix(), "sha256": sha, "category": category},
        "sidecar": sidecar,
        "source": "gui",
    }
    if note.strip():  # verbatim, as the user typed it; a blank note is left out
        entry["note"] = note
    found = problems(entry)
    if found:
        raise ChoiceError("Eintrag passt nicht zum Format: " + found[0])
    return entry


@dataclass
class LogRead:
    entries: list[dict] = field(default_factory=list)  # valid entries in file order
    skipped: int = 0  # lines that were not valid entries
    error: str = ""  # the file exists but could not be read (German); entries are then empty


def parse_lines(data: bytes) -> LogRead:
    """Valid entries of a JSONL byte string; every other line is skipped and counted."""
    res = LogRead()
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()  # the newline that ends the last line
    for raw in lines:
        try:
            entry = json.loads(raw.decode("utf-8"))
        except ValueError:  # UnicodeDecodeError is a ValueError
            res.skipped += 1
            continue
        if problems(entry):
            res.skipped += 1
            continue
        try:  # the pattern has no calendar check: 2026-02-30 passes it (#486 review)
            instant(entry["time"])
        except ValueError:
            res.skipped += 1
            continue
        res.entries.append(entry)
    return res


def encode(entry: dict) -> bytes:
    return (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")


class ChoiceLog:
    """The log file (``path``) or, with ``path=None``, an in-memory log."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._memory = bytearray()

    @classmethod
    def beside_settings(cls, settings_path: Path | None) -> ChoiceLog:
        """The log next to ``settings.json``; in memory when the settings are (no file)."""
        return cls(Path(settings_path).parent / FILE_NAME if settings_path is not None else None)

    @property
    def location(self) -> str:
        return str(self.path) if self.path is not None else "nur im Speicher"

    def append(self, entry: dict) -> None:
        """Validate and append one entry. Raises :class:`ChoiceError` (refused entry, nothing
        written) or ``OSError`` (disk); a short write leaves at most one unterminated line,
        which the next append closes and readers skip."""
        found = problems(entry)
        try:
            instant(entry["time"])
        except (ValueError, KeyError, TypeError, AttributeError):
            found = found or ["time: kein gültiger Zeitpunkt"]
        if found:
            raise ChoiceError("Eintrag passt nicht zum Format: " + found[0])
        data = encode(entry)
        if self.path is None:
            if self._memory and not self._memory.endswith(b"\n"):
                self._memory += b"\n"
            self._memory += data
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
        fd = os.open(self.path, flags, 0o644)
        try:
            if _needs_newline(self.path):
                data = b"\n" + data
            written = os.write(fd, data)  # one write: a whole line or (disk full) a short one
            if written != len(data):
                raise OSError(f"choice log: wrote {written} of {len(data)} bytes")
            os.fsync(fd)
        finally:
            os.close(fd)

    def read(self) -> LogRead:
        if self.path is None:
            return parse_lines(bytes(self._memory))
        try:
            data = self.path.read_bytes()
        except FileNotFoundError:
            return LogRead()
        except OSError as exc:
            return LogRead(error=f"Auswahl-Log nicht lesbar: {type(exc).__name__}")
        return parse_lines(data)


def _needs_newline(path: Path) -> bool:
    """True when the file ends inside a line (a crash cut its last write)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            if f.tell() == 0:
                return False
            f.seek(-1, os.SEEK_END)
            return f.read(1) != b"\n"
    except OSError:
        return False


def current_verdicts(entries: list[dict]) -> dict[str, dict]:
    """sha256 -> the entry that holds its current verdict: the newest parsed instant, on equal
    instants the later line. Entries without a hash (old listening tests) are history only."""
    best: dict[str, tuple[datetime, int, dict]] = {}
    for i, e in enumerate(entries):
        sha = e["sample"]["sha256"]
        if sha is None:
            continue
        key = (instant(e["time"]), i)
        if sha not in best or key > best[sha][:2]:
            best[sha] = (*key, e)
    return {sha: v[2] for sha, v in best.items()}


def known_sha256(wav: Path, cache: dict | None = None) -> str | None:
    """The WAV's SHA-256 for showing verdicts in the library: hashed once per (path, size,
    mtime) and cached in ``cache``. None if the file cannot be read."""
    try:
        st = wav.stat()
    except OSError:
        return None
    key = (str(wav), st.st_size, st.st_mtime_ns)
    if cache is not None and key in cache:
        return cache[key]
    try:
        sha = file_sha256(wav)
    except OSError:
        return None
    if cache is not None:
        cache[key] = sha
    return sha
