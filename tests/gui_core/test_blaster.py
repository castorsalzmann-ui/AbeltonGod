"""Blaster service layer (no Qt). Tests marked "real engine" use ``audio_engine.laser``; the
rest use the STUB of gui_core.blaster_stub or a tiny fake for speed. Nothing here says anything
about how a shot sounds."""

from __future__ import annotations

import hashlib
import json
import random
import wave
from pathlib import Path

import numpy as np
import pytest

from audio_engine.io import encode_wav
from audio_engine.laser import FAMILIES, render_laser
from gui_core import blaster as bl
from gui_core.blaster import (
    BANK_MAX,
    BlasterError,
    BlasterSession,
    BlasterSettings,
    CategoryBankWriter,
    export_bank,
    to_engine_params,
)
from gui_core.blaster_params import randomise
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
    """Writes <stem>.wav + <stem>.json like a sidecar writer would (test double, no engine)."""

    def __init__(self, fail_at=None):
        self.fail_at, self.n = fail_at, 0

    def write(self, params, seed, folder, stem, description):
        self.n += 1
        if self.fail_at == self.n:
            raise OSError("Datenträger voll")
        wav, js = Path(folder) / f"{stem}.wav", Path(folder) / f"{stem}.json"
        wav.write_bytes(b"RIFF")
        js.write_text(json.dumps({"seed": seed, "params": params, "description": description}))
        return wav, js


class FixedEngine:
    sample_rate = 48000

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


@pytest.fixture
def real_session(tmp_path):
    engine, msg = bl.load_engine()
    assert engine is not None, msg
    s = BlasterSession(engine, FakeBackend(), work_dir=tmp_path / "work")
    yield s
    s.close()

# ---- real engine ---------------------------------------------------------------------------------
@pytest.mark.parametrize("family", FAMILIES)
def test_real_engine_shot_per_family(real_session, family):
    real_session.settings = BlasterSettings().with_values(
        family=family, length_ms=100, stereo_width=0.6, noise_level=0.3)
    r = real_session.fire()
    assert r.shot is not None and not r.error, r.message
    shot = r.shot
    expected_n = round(shot.params["length_ms"] * 48000 / 1000)
    assert shot.samples.shape == (expected_n, 2) and shot.sample_rate == 48000
    assert np.all(np.isfinite(shot.samples))
    assert shot.peak_dbfs <= -0.3 + 1e-6  # contract default ceiling
    with wave.open(str(shot.wav_path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (2, 3, 48000)
        assert w.getnframes() == expected_n
    assert real_session.backend.bits == [16]


def test_real_engine_same_seed_same_bytes_and_seed_matters_with_noise(tmp_path):
    def wav_for(seed):
        engine, _ = bl.load_engine()
        s = BlasterSession(engine, FakeBackend(), tmp_path / f"w{seed}", first_seed=seed)
        s.settings = BlasterSettings().with_values(
            family="plasma", noise_level=0.5, crackle=0.4, length_ms=100)
        try:
            return s.fire().shot.wav_path.read_bytes()
        finally:
            s.close()

    assert wav_for(7) == wav_for(7)
    assert wav_for(7) != wav_for(8)


def test_real_engine_random_settings_render_valid_stereo(real_session):
    rng = random.Random(11)
    for _ in range(25):
        # every group (salvo, filter, delay, reverb too) over its contract range
        s = randomise(BlasterSettings(), ["weapon", "salvo", "filter", "delay", "reverb"],
                      rng.randint(0, 10**6)).with_values(length_ms=rng.choice([100, 600]))
        samples, params = real_session.render_shot(s, rng.randint(0, bl.SEED_MAX))
        n = round(params["length_ms"] * 48000 / 1000)
        assert samples.shape == (n, 2) and np.all(np.isfinite(samples))
        assert 0 < np.max(np.abs(samples)) <= 1.0


def test_shot_wav_equals_the_engines_own_encoding(real_session):
    r = real_session.fire()
    shot = r.shot
    ref = encode_wav(render_laser(shot.params, shot.seed), 48000, 24)
    assert shot.wav_path.read_bytes() == ref  # independent path: engine call + engine encoder


def test_real_bank_uses_the_repo_writer_layout_and_sidecars(tmp_path):
    s = BlasterSettings().with_values(family="rift", length_ms=100)
    res = export_bank(s, 5, 3, tmp_path / "proj", CategoryBankWriter())
    assert res.ok, res.message
    folder = tmp_path / "proj" / "Samples" / "FX" / "Lasers" / "laser_bank_001"
    assert res.folder == folder
    assert sorted(p.name for p in folder.iterdir()) == [
        f"laser_rift_s{n}.{e}" for n in (5, 6, 7) for e in ("json", "wav")]
    for seed in (5, 6, 7):
        wav = folder / f"laser_rift_s{seed}.wav"
        meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
        assert meta["category"] == "laser" and meta["engine"]["name"].endswith("-laser")
        assert meta["parameters"]["seed"] == seed and meta["parameters"]["family"] == "rift"
        assert meta["sha256"] == hashlib.sha256(wav.read_bytes()).hexdigest()
        with wave.open(str(wav)) as w:
            assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (2, 3, 48000)
        # the bank WAV is byte-identical to the shot the window would play for that seed
        ref = encode_wav(render_laser(to_engine_params(s), seed), 48000, 24)
        assert wav.read_bytes() == ref
    again = export_bank(s, 5, 1, tmp_path / "proj", CategoryBankWriter())
    assert again.folder == folder.parent / "laser_bank_002" and len(list(folder.iterdir())) == 6


# ---- shots (stub / fake engines) -----------------------------------------------------------------
def test_fire_uses_a_deterministic_seed_sequence(session):
    seeds = [session.fire().shot.seed for _ in range(4)]
    assert seeds == [1, 2, 3, 4] and session.next_seed == 5
    assert [c[1] for c in session.engine.calls] == [1, 2, 3, 4]
    assert [s.index for s in session.history] == [4, 3, 2, 1]  # newest first


def test_commit_after_a_separate_render_matches_fire(tmp_path):
    a = BlasterSession(StubLaserEngine(), FakeBackend(), tmp_path / "a")
    b = BlasterSession(StubLaserEngine(), FakeBackend(), tmp_path / "b")
    fired = a.fire().shot
    samples, params = b.render_shot(b.settings, b.next_seed)
    committed = b.commit(b.settings, 1, samples, params).shot
    assert fired.wav_path.read_bytes() == committed.wav_path.read_bytes()
    assert b.next_seed == 2 and len(b.history) == 1
    a.close()
    b.close()


def test_wav_files_are_valid_24_bit_stereo_and_16_bit_copies(session):
    shot = session.fire().shot
    with wave.open(str(shot.wav_path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (2, 3, 48000)
        assert w.getnframes() == len(shot.samples)
    with wave.open(str(shot.play_path)) as w:
        assert (w.getnchannels(), w.getsampwidth()) == (2, 2)
        first = np.frombuffer(w.readframes(2), dtype="<i2")
    assert first[0] == round(shot.samples[0, 0] * 32767)  # independent interleave check
    assert first[1] == round(shot.samples[0, 1] * 32767)
    assert session.backend.bits == [16] and len(shot.mono) == len(shot.samples)


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
    assert s.history == [] and s.next_seed == 1 and s.backend.played == []
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


def test_load_engine_returns_the_real_engine():
    engine, msg = bl.load_engine()
    assert msg == "" and engine.sample_rate == 48000
    out = engine.render(to_engine_params(BlasterSettings().with_values(length_ms=100)), 3)
    assert out.shape[1] == 2


def test_load_engine_reports_missing_module(monkeypatch):
    monkeypatch.setattr(bl.importlib.util, "find_spec", lambda name: None)
    engine, msg = bl.load_engine()
    assert engine is None and "audio_engine.laser fehlt" in msg


def test_load_engine_import_error_is_a_message(monkeypatch):
    def boom(name):
        raise ImportError("kaputt")

    monkeypatch.setattr(bl.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(bl.importlib, "import_module", boom)
    engine, msg = bl.load_engine()
    assert engine is None and "nicht ladbar" in msg and "kaputt" in msg


# ---- bank export (fake writer: folder rules and error paths) ---------------------
def test_bank_goes_into_a_new_library_folder_and_never_reuses_one(tmp_path):
    s = BlasterSettings().with_values(family="ion")
    lasers = tmp_path / "out" / "Samples" / "FX" / "Lasers"
    old = lasers / "laser_bank_001"
    old.mkdir(parents=True)
    keep = old / "laser_ion_s1.wav"
    keep.write_bytes(b"MINE")
    res = export_bank(s, 1, 2, tmp_path / "out", FakeWriter())
    assert res.ok and res.folder == lasers / "laser_bank_002"
    assert keep.read_bytes() == b"MINE" and [p.name for p in old.iterdir()] == [keep.name]
    meta = json.loads((res.folder / "laser_ion_s2.json").read_text())
    assert meta["seed"] == 2 and meta["params"]["family"] == "ion"
    assert export_bank(s, 1, 1, tmp_path / "out", FakeWriter()).folder == lasers / "laser_bank_003"


def test_bank_write_failure_keeps_what_was_written_and_says_how_many(tmp_path):
    res = export_bank(BlasterSettings(), 1, 4, tmp_path, FakeWriter(fail_at=3))
    assert res.error and not res.ok and len(res.files) == 2
    assert "nach 2 von 4 Dateien" in res.message and "Datenträger voll" in res.message


def test_bank_that_wrote_nothing_removes_its_empty_folder(tmp_path):
    res = export_bank(BlasterSettings(), 1, 2, tmp_path, FakeWriter(fail_at=1))
    assert res.error and res.folder is None and "nach 0 von 2" in res.message
    assert not (tmp_path / "Samples" / "FX" / "Lasers" / "laser_bank_001").exists()


def test_bank_unexpected_exception_becomes_a_result(tmp_path):
    class Boom:
        def write(self, *a):
            raise RuntimeError("kaputt")

    res = export_bank(BlasterSettings(), 1, 2, tmp_path, Boom())
    assert res.error and "RuntimeError: kaputt" in res.message


def test_bank_parent_that_is_a_file_is_an_error(tmp_path):
    f = tmp_path / "datei"
    f.write_text("x")
    res = export_bank(BlasterSettings(), 1, 1, f, FakeWriter())
    assert res.error and "Ordner konnte nicht angelegt werden" in res.message


@pytest.mark.parametrize("count", [0, -1, BANK_MAX + 1, True, 2.5])
def test_bank_count_out_of_range_is_refused(tmp_path, count):
    res = export_bank(BlasterSettings(), 1, count, tmp_path / "out", FakeWriter())
    assert res.error and not (tmp_path / "out").exists()


def test_bank_seed_range_is_checked(tmp_path):
    res = export_bank(BlasterSettings(), bl.SEED_MAX, 2, tmp_path / "out", FakeWriter())
    assert res.error and "Start-Seed" in res.message and not (tmp_path / "out").exists()


def test_category_writer_without_laser_category_is_a_message(monkeypatch, tmp_path):
    from audio_engine import io
    from audio_engine.categories import CategoryUnavailable

    def raise_unavailable(*a, **k):
        raise CategoryUnavailable("laser has no renderer")

    monkeypatch.setattr(io, "write_sample", raise_unavailable)
    with pytest.raises(BlasterError, match="Bank nicht möglich"):
        CategoryBankWriter().write(to_engine_params(BlasterSettings()), 1, tmp_path, "x", "d")
