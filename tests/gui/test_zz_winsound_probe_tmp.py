"""TEMPORARY Windows CI probe for #543/#544 (removed before review): what winsound does on the
runner with the Acid preview WAV (22.05 kHz mono 16-bit) and a 48 kHz file. Fails on purpose
with the observations in the message so they show up in the CI log."""

from __future__ import annotations

import sys
import time

import numpy as np
import pytest

from audio_engine.io import encode_wav


@pytest.mark.skipif(sys.platform != "win32", reason="winsound probe")
def test_probe(tmp_path):
    import winsound

    from gui_core.acid_model import AcidModel
    from gui_core.acid_preview import preview_wav_bytes

    obs = []
    m = AcidModel()
    acid = tmp_path / "acid_preview.wav"
    acid.write_bytes(preview_wav_bytes(m.to_line(), m.bpm))
    t = np.arange(48000) / 48000
    k48 = tmp_path / "k48.wav"
    k48.write_bytes(encode_wav(0.5 * np.sin(2 * np.pi * 60 * t), 48000, 16))
    s48 = tmp_path / "s48.wav"
    s48.write_bytes(encode_wav(np.stack([0.5 * np.sin(2 * np.pi * 60 * t)] * 2, axis=1),
                               48000, 16))
    F, A, N = winsound.SND_FILENAME, winsound.SND_ASYNC, winsound.SND_NODEFAULT

    def run(label, fn):
        t0 = time.perf_counter()
        try:
            r = fn()
            obs.append(f"{label}: ok {r!r} {time.perf_counter() - t0:.3f}s")
        except Exception as exc:  # noqa: BLE001
            obs.append(f"{label}: {type(exc).__name__}: {exc} {time.perf_counter() - t0:.3f}s")

    for p in (acid, k48, s48):
        run(f"sync {p.name}", lambda p=p: winsound.PlaySound(str(p), F | N))
        run(f"async {p.name}", lambda p=p: winsound.PlaySound(str(p), F | A | N))
        run(f"rewrite-while-async {p.name}", lambda p=p: p.write_bytes(p.read_bytes()))
        c = p.with_name("copy_" + p.name)
        c.write_bytes(p.read_bytes())
        run(f"async copy {p.name}", lambda c=c: winsound.PlaySound(str(c), F | A | N))
        run(f"unlink-while-async {p.name}", lambda c=c: c.unlink())
        run("stop", lambda: winsound.PlaySound(None, 0))
    run("async missing", lambda: winsound.PlaySound(str(tmp_path / "nope.wav"), F | A | N))
    run("sync missing", lambda: winsound.PlaySound(str(tmp_path / "nope.wav"), F | N))
    run("memory sync", lambda: winsound.PlaySound(acid.read_bytes(), winsound.SND_MEMORY | N))
    pytest.fail("PROBE " + " | ".join(obs))
