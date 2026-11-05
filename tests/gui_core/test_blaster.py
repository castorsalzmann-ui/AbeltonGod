"""Blaster service layer (no Qt). The engine is the STUB of gui_core.blaster_stub or a tiny fake
here; nothing in this file says anything about the real laser engine (issue #416)."""

from __future__ import annotations

import json
import random
import wave
from pathlib import Path

import numpy as np
import pytest

from gui_core import blaster as bl
from gui_core.blaster import (
    BANK_MAX,
    BlasterError,
    BlasterSession,
    BlasterSettings,
    CategoryBankWriter,
    encode_shot_wav,
    export_bank,
    to_engine_params,
)
from gui_core.blaster_stub import StubLaserEngine


class FakeBackend:
    def __init__(self, available=True, fail=False):
        self.available, self.fail = available, fail
        self.played: list[Path] = []
        self.bits: list[int] = []

    def play(self, wav_path):
        if self.fail:
            raise RuntimeError("Gerät weg")
        self.played.append(Path(wav_path))
        with wave.open(str(wav_path)) as w:
            self.bits.append(w.getsampwidth() * 8)

    def stop(self):
        pass


class FakeWriter:
    """Writes <stem>.wav + <stem>.json like a sidecar writer would (test double)."""

    def __init__(self, fail_at=None):
        self.fail_at, self.n = fail_at, 0

    def write(self, params, seed, samples, sr, folder, stem, description):
        self.n += 1
        if self.fail_at == self.n:
            raise OSError("Datenträger voll")
        wav, js = Path(folder) / f"{stem}.wav", Path(folder) / f"{stem}.json"
        wav.write_bytes(encode_shot_wav(samples, sr, 24))
        js.write_text(json.dumps({"seed": seed, "params": params, "description": description}))
        return wav, js


class FixedEngine:
    sample_rate = 22050

    def __init__(self, result):
        self.result = result

    def render(self, params, seed):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def session(tmp_path):
    s = BlasterSession(StubLaserEngine(), FakeBackend(), work_dir=tmp_path / "work")
    yield s
    s.close()


# ---- settings and parameter mapping ------------------------------------------------------------
def test_settings_accept_the_whole_range_and_reject_outside():
    rng = random.Random(1)
    for _ in range(200):
        vals = {n: rng.randint(0, 100) for n in bl.SLIDER_NAMES}
        BlasterSettings(dimension=rng.choice(bl.DIMENSION_KEYS), **vals)
    for bad in (-1, 101, 5.0, True, "5", None):
        with pytest.raises(ValueError):
            BlasterSettings(pitch=bad)
    with pytest.raises(ValueError, match="Unbekannte Dimension"):
        BlasterSettings(dimension="nope")


def test_engine_params_match_hand_computed_values():
    lo = to_engine_params(BlasterSettings(pitch=0, sweep=0, length=0, roughness=0, echo=0, width=0))
    hi = to_engine_params(BlasterSettings(pitch=100, sweep=100, length=100, roughness=100,
                                          echo=100, width=100))
    assert lo["pitch_start_hz"] == 200.0 and lo["pitch_end_hz"] == 200.0  # sweep 0: flat
    assert lo["length_ms"] == 60.0 and lo["fm_amount"] == 0 and lo["stereo_width"] == 0
    assert hi["pitch_start_hz"] == 8000.0
    assert hi["pitch_end_hz"] == 250.0  # 8000 Hz, 5 octaves down
    assert hi["length_ms"] == 1500.0 and hi["fm_amount"] == 1.0 and hi["noise_amount"] == 0.5
    assert hi["tail_amount"] == 1.0 and hi["stereo_width"] == 1.0
    assert hi["family"] == "classic"


def test_engine_params_stay_in_range_and_are_monotonic():
    rng = random.Random(2)
    for _ in range(200):
        s = BlasterSettings(**{n: rng.randint(0, 100) for n in bl.SLIDER_NAMES})
        p = to_engine_params(s)
        assert 200 <= p["pitch_start_hz"] <= 8000 and 20 <= p["pitch_end_hz"] <= p["pitch_start_hz"]
        assert 60 <= p["length_ms"] <= 1500
        assert all(0 <= p[k] <= 1 for k in ("fm_amount", "noise_amount", "tail_amount",
                                            "stereo_width"))
    lens = [to_engine_params(BlasterSettings(length=v))["length_ms"] for v in range(0, 101, 5)]
    assert lens == sorted(lens)


def test_readouts_are_german_text():
    assert bl.readout("pitch", 0) == "200 Hz"
    assert bl.readout("pitch", 100) == "8,0 kHz"
    assert bl.readout("sweep", 100) == "−5,0 Okt"
    assert bl.readout("length", 100) == "1500 ms"
    assert bl.readout("echo", 35) == "35 %"


# ---- shots -------------------------------------------------------------------------------------
def test_fire_uses_a_deterministic_seed_sequence(session):
    seeds = []
    for _ in range(4):
        r = session.fire()
        seeds.append(r.shot.seed)
    assert seeds == [1, 2, 3, 4] and session.next_seed == 5
    assert [c[1] for c in session.engine.calls] == [1, 2, 3, 4]
    assert [s.index for s in session.history] == [4, 3, 2, 1]  # newest first


def test_same_seed_same_settings_same_bytes(tmp_path):
    def wav_for(seed, stereo):
        s = BlasterSession(StubLaserEngine(stereo=stereo), FakeBackend(),
                           tmp_path / f"w{seed}{stereo}", first_seed=seed)
        s.settings = BlasterSettings(dimension="plasma", pitch=70, length=30)
        try:
            return s.fire().shot.wav_path.read_bytes()
        finally:
            s.close()

    for stereo in (False, True):
        assert wav_for(7, stereo) == wav_for(7, stereo)
        assert wav_for(7, stereo) != wav_for(8, stereo)


def test_wav_files_are_valid_24_bit_and_16_bit_copies(session):
    shot = session.fire().shot
    with wave.open(str(shot.wav_path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 3, 22050)
        assert w.getnframes() == len(shot.samples)
    with wave.open(str(shot.play_path)) as w:
        assert w.getsampwidth() == 2
    assert session.backend.bits == [16]  # what the backend gets is the 16-bit copy


def test_stereo_shot_gives_a_two_channel_wav(tmp_path):
    s = BlasterSession(StubLaserEngine(stereo=True), FakeBackend(), tmp_path / "w")
    shot = s.fire().shot
    assert shot.samples.shape[1] == 2 and len(shot.mono) == len(shot.samples)
    for path, width in ((shot.wav_path, 3), (shot.play_path, 2)):
        with wave.open(str(path)) as w:
            assert (w.getnchannels(), w.getsampwidth()) == (2, width)
            frames = w.readframes(w.getnframes())
        assert len(frames) == len(shot.samples) * 2 * width
    # independent check of the interleave: first left sample of the 16-bit file
    with wave.open(str(shot.play_path)) as w:
        first = np.frombuffer(w.readframes(2), dtype="<i2")
    assert first[0] == round(shot.samples[0, 0] * 32767)
    assert first[1] == round(shot.samples[0, 1] * 32767)
    s.close()


@pytest.mark.parametrize("bad, text", [
    (np.array([0.1, np.nan, 0.2]), "ungültige Werte"),
    (np.array([0.1, np.inf]), "ungültige Werte"),
    (np.zeros(100), "Stille"),
    (np.array([0.5, 1.2]), "Vollaussteuerung"),
    (np.array([]), "keine Audiodaten"),
    (np.zeros((10, 3)) + 0.1, "keine Audiodaten"),
    ("abc", "keine Audiodaten"),
])
def test_bad_engine_output_is_an_error_not_a_shot(tmp_path, bad, text):
    s = BlasterSession(FixedEngine(bad), FakeBackend(), tmp_path / "w")
    r = s.fire()
    assert r.shot is None and r.error and text in r.message
    assert s.history == [] and s.next_seed == 1  # nothing kept, counter not advanced
    assert s.backend.played == []
    s.close()


def test_engine_exceptions_become_messages(tmp_path):
    for exc, text in ((ValueError("Länge"), "Ungültige Parameter: Länge"),
                      (RuntimeError("kaputt"), "Schuss fehlgeschlagen: RuntimeError: kaputt")):
        s = BlasterSession(FixedEngine(exc), FakeBackend(), tmp_path / "w")
        r = s.fire()
        assert r.shot is None and r.error and text in r.message
        s.close()


def test_missing_engine_says_so_and_does_nothing(tmp_path):
    s = BlasterSession(None, FakeBackend(), tmp_path / "w", unavailable_reason="Engine fehlt.")
    r = s.fire()
    assert r.shot is None and r.error and r.message == "Engine fehlt."
    assert s.backend.played == [] and s.history == []
    s.close()


def test_missing_or_failing_audio_still_keeps_the_shot(tmp_path):
    s = BlasterSession(StubLaserEngine(), FakeBackend(available=False), tmp_path / "w")
    r = s.fire()
    assert r.shot is not None and not r.played and "Keine Audioausgabe" in r.message
    assert not r.error and len(s.history) == 1
    s2 = BlasterSession(StubLaserEngine(), FakeBackend(fail=True), tmp_path / "w2")
    r = s2.fire()
    assert r.shot is not None and r.error and "Wiedergabe fehlgeschlagen" in r.message
    s.close()
    s2.close()


def test_unwritable_work_dir_is_an_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    s = BlasterSession(StubLaserEngine(), FakeBackend(), blocker / "sub")
    r = s.fire()
    assert r.shot is None and r.error and "zwischengespeichert" in r.message
    assert s.next_seed == 1 and s.history == []


def test_history_is_capped_and_old_files_are_removed(tmp_path):
    s = BlasterSession(StubLaserEngine(), FakeBackend(), tmp_path / "w", history_limit=3)
    shots = [s.fire().shot for _ in range(6)]
    assert [x.index for x in s.history] == [6, 5, 4]
    assert not shots[0].wav_path.exists() and not shots[2].play_path.exists()
    assert shots[5].wav_path.exists()
    s.close()


def test_close_removes_its_own_temp_dir():
    s = BlasterSession(StubLaserEngine(), FakeBackend())
    s.fire()
    d = s.work_dir
    assert d.exists()
    s.close()
    assert not d.exists()


def test_load_engine_reports_missing_module(monkeypatch):
    monkeypatch.setattr(bl.importlib.util, "find_spec", lambda name: None)
    engine, msg = bl.load_engine()
    assert engine is None and "audio_engine.laser fehlt" in msg


def test_load_engine_wraps_render_laser(monkeypatch):
    class Mod:
        SAMPLE_RATE = 48000
        calls: list = []

        @staticmethod
        def render_laser(params, seed):
            Mod.calls.append((params, seed))
            return [0.1, -0.1]

    monkeypatch.setattr(bl.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(bl.importlib, "import_module", lambda name: Mod)
    engine, msg = bl.load_engine()
    assert msg == "" and engine.sample_rate == 48000
    out = engine.render({"a": 1}, 9)
    assert Mod.calls == [({"a": 1}, 9)] and out.tolist() == [0.1, -0.1]


def test_load_engine_import_error_is_a_message(monkeypatch):
    def boom(name):
        raise ImportError("kaputt")

    monkeypatch.setattr(bl.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(bl.importlib, "import_module", boom)
    engine, msg = bl.load_engine()
    assert engine is None and "nicht ladbar" in msg and "kaputt" in msg


# ---- bank export -------------------------------------------------------------------------------
def test_bank_writes_a_new_folder_with_sidecars_and_advances_the_seed(session, tmp_path):
    session.settings = BlasterSettings(dimension="ion")
    res = export_bank(session, 3, tmp_path / "out", FakeWriter())
    assert res.ok and res.folder == tmp_path / "out" / "laser_bank_001"
    names = sorted(p.name for p in res.folder.iterdir())
    assert names == [f"laser_ion_s{s}.{e}" for s in (1, 2, 3) for e in ("json", "wav")]
    meta = json.loads((res.folder / "laser_ion_s2.json").read_text())
    assert meta["seed"] == 2 and meta["params"]["family"] == "ion"
    assert session.next_seed == 4 and session.history == []  # the bank does not touch the history


def test_bank_never_reuses_or_overwrites_a_folder(session, tmp_path):
    out = tmp_path / "out"
    old = out / "laser_bank_001"
    old.mkdir(parents=True)
    keep = old / "laser_classic_s1.wav"
    keep.write_bytes(b"MINE")
    res = export_bank(session, 2, out, FakeWriter())
    assert res.folder == out / "laser_bank_002" and res.ok
    assert keep.read_bytes() == b"MINE" and [p.name for p in old.iterdir()] == [keep.name]
    res2 = export_bank(session, 1, out, FakeWriter())
    assert res2.folder == out / "laser_bank_003"


def test_bank_is_reproducible_from_the_same_start_seed(tmp_path):
    def run(sub):
        s = BlasterSession(StubLaserEngine(), FakeBackend(), tmp_path / f"w{sub}", first_seed=40)
        r = export_bank(s, 3, tmp_path / sub, FakeWriter())
        s.close()
        return {p.name: p.read_bytes() for p in r.folder.glob("*.wav")}

    assert run("a") == run("b")


def test_bank_engine_failure_creates_no_folder(tmp_path):
    s = BlasterSession(FixedEngine(RuntimeError("kaputt")), FakeBackend(), tmp_path / "w")
    res = export_bank(s, 2, tmp_path / "out", FakeWriter())
    assert res.error and "kaputt" in res.message and res.folder is None
    assert not (tmp_path / "out").exists() and s.next_seed == 1
    s.close()


def test_bank_write_failure_keeps_what_was_written_and_says_how_many(session, tmp_path):
    res = export_bank(session, 4, tmp_path / "out", FakeWriter(fail_at=3))
    assert res.error and not res.ok and len(res.files) == 2
    assert "nach 2 von 4 Dateien" in res.message and "Datenträger voll" in res.message
    assert session.next_seed == 3  # only the written shots count


def test_bank_parent_that_is_a_file_is_an_error(session, tmp_path):
    f = tmp_path / "datei"
    f.write_text("x")
    res = export_bank(session, 1, f, FakeWriter())
    assert res.error and "Ordner konnte nicht angelegt werden" in res.message


@pytest.mark.parametrize("count", [0, -1, BANK_MAX + 1, True, 2.5])
def test_bank_count_out_of_range_is_refused(session, tmp_path, count):
    res = export_bank(session, count, tmp_path / "out", FakeWriter())
    assert res.error and not (tmp_path / "out").exists()


def test_category_writer_without_laser_category_is_a_message(monkeypatch, tmp_path):
    from audio_engine import io
    from audio_engine.categories import CategoryUnavailable

    def raise_unavailable(*a, **k):
        raise CategoryUnavailable("laser has no renderer")

    monkeypatch.setattr(io, "write_sample", raise_unavailable)
    with pytest.raises(BlasterError, match="Bank nicht möglich"):
        CategoryBankWriter().write({"family": "classic"}, 1, np.zeros(4), 22050, tmp_path, "x", "d")
