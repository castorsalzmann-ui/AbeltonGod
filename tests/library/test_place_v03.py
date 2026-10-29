"""place_kick with kick-params v0.3 requests (#120): the library stores the resolved form,
which re-renders the WAV byte for byte and still shows the note (``tail_note_of``)."""

from __future__ import annotations

import hashlib
import json

import pytest

from audio_engine.io import rerender_from_sidecar
from audio_engine.params import KickParamsError, tail_note_of
from library import place_kick


def test_v03_request_is_placed_and_rerenders(tmp_path) -> None:
    req = {"schema_version": "0.3", "seed": 11, "tail_note": 29, "length_beats": 1,
           "bpm": 132, "offset_ms": 2, "polarity": -1, "clip_db": 3}
    wav_path = place_kick(req, tmp_path, name="kick-F1")
    meta = json.loads(wav_path.with_suffix(".json").read_text(encoding="utf-8"))
    params = meta["parameters"]
    assert not {"tail_note", "length_beats"} & set(params)
    assert params["length_ms"] == 60000 / 132 and tail_note_of(params) == 29
    assert hashlib.sha256(wav_path.read_bytes()).hexdigest() == meta["sha256"]
    assert rerender_from_sidecar(wav_path.with_suffix(".json")) == wav_path.read_bytes()


def test_rejected_v03_request_writes_nothing(tmp_path) -> None:
    with pytest.raises(KickParamsError):
        place_kick({"schema_version": "0.3", "seed": 1, "length_beats": 1, "bpm": 128,
                    "amp_decay_ms": 2000}, tmp_path)
    assert list(tmp_path.iterdir()) == []
