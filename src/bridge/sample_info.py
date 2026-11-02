"""Which sound category a WAV belongs to, read from its sidecar, before anything goes to Live.

The import path (``scripts/live_import.py``, ``scripts/kick_to_live.py``) sends the same
tested functions for every category: ``song.create_audio_track``,
``clip_slot.create_audio_clip`` and the read-backs. What changes per category is only the
check in front of them and the words used for the sample. No Ableton function is added here;
this module touches no OSC socket.

Rules (:func:`read_sample_info`):

- A WAV with a sidecar (same stem, ``.json``) must name a category that
  :func:`audio_engine.categories.get_category` has registered (``kick``, ``clap``). An
  unreadable sidecar, a missing or non-string category, a category the contract names without
  a renderer, or an unknown one is refused with :class:`SampleCategoryError`.
- The WAV must lie in that category's folder of a project (``library.LibraryLayout``,
  e.g. ``Samples/Drums/Claps``), so a clap sitting in the kick folder is refused.
- A WAV without a sidecar is a hand-made file (the #50 test usage): it is imported as before,
  with ``category=None``.

What Live does with names is not changed here: Live names the clip after the file and renames
a default-named audio track after the clip (#50 run 1). The label this module builds
(``"clap: name"``) is for the plan, prompts and result block only; no rename is sent.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from audio_engine.categories import CategoryUnavailable, get_category
from library import DEFAULT_LAYOUT, LibraryLayout, LibraryPathError, sidecar_path

from .clip_import import ImportPathError


class SampleCategoryError(ImportPathError):
    """The sample's category is unknown, unregistered or contradicts its folder."""


@dataclass(frozen=True)
class SampleInfo:
    """``category`` is ``None`` for a WAV without a sidecar."""

    category: str | None
    stem: str

    @property
    def label(self) -> str:
        return self.stem if self.category is None else f"{self.category}: {self.stem}"


def read_sample_info(wav: str | os.PathLike[str], *,
                     layout: LibraryLayout = DEFAULT_LAYOUT) -> SampleInfo:
    """Category and name of ``wav`` from its sidecar; :class:`SampleCategoryError` if refused.

    Reads one file, writes nothing. ``wav`` is expected to be validated already
    (``clip_import.validate_wav_path``).
    """
    path = Path(wav)
    side = sidecar_path(path)
    if not side.is_file():
        return SampleInfo(None, path.stem)
    try:
        meta = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SampleCategoryError(
            f"Sidecar {side.name} lässt sich nicht lesen ({type(exc).__name__}); die Kategorie "
            "der Datei ist unbekannt."
        ) from exc
    name = meta.get("category") if isinstance(meta, dict) else None
    if not isinstance(name, str):
        raise SampleCategoryError(f"Sidecar {side.name} nennt keine Kategorie (Feld 'category').")
    try:
        get_category(name)
        parts = layout.parts_for(name)
    except CategoryUnavailable as exc:
        raise SampleCategoryError(
            f"Kategorie {name!r} ist hier nicht importierbar: {exc}") from exc
    except LibraryPathError as exc:  # registered category without a library folder
        raise SampleCategoryError(f"Kategorie {name!r}: {exc}") from exc
    folder = path.parent.parts
    wanted = tuple(p.casefold() for p in parts)
    if tuple(p.casefold() for p in folder[-len(parts):]) != wanted:
        raise SampleCategoryError(
            f"Die Datei ist eine {name!r}-Datei, liegt aber nicht im Ordner "
            f"'{os.sep.join(parts)}' eines Projekts ({path.parent}).")
    return SampleInfo(name, path.stem)
