"""#544 (user, Windows exe): "beim laser blaster ist der letzte Schuss irgendwie bass buggy und
wird nicht ganz fertig gespielt".

Cause found (measured, see the PR): the engine cuts every sound at ``length_ms`` with a 5 ms
fade (contract, ``length_ms``). The Blaster window never adapted the length when more shots,
a wider spacing, echo or reverb made the salvo longer, so the last shot was cut while still
loud: preset "pew" with 5 shots ended 20.4 dB below its peak, "plasma-driven" with 5 shots
0.2 dB below. The live preview also cut every sound at a fixed 800 ms ("blaster-echo":
-25.8 dB). Whether this is also what the user calls "bass buggy" is not established.

End level here = loudest sample in the 20 ms before the last 5 ms (the fade), relative to the
file's peak. A sound that rang out is far below -45 dB there.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from gui.app import create_app  # noqa: E402

RANG_OUT_DB = -45.0


def end_db(x: np.ndarray, sr: int) -> float:
    peak = float(np.max(np.abs(x)))
    a, b = len(x) - int(0.025 * sr), len(x) - int(0.005 * sr)
    return 20.0 * np.log10(max(float(np.max(np.abs(x[a:b]))), 1e-12) / peak)


class SilentBackend:
    available = True

    def play(self, wav_path) -> None:
        pass

    def stop(self) -> None:
        pass


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


@pytest.fixture
def win(qapp, tmp_path):
    from gui.blaster.window import BlasterWindow

    w = BlasterWindow(backend=SilentBackend(), out_dir=tmp_path / "out", work_dir=tmp_path / "w")
    assert w.session.engine is not None, w.session.unavailable_reason
    w.live_check.setChecked(False)  # no worker-thread preview in this test
    yield w
    w.close()


@pytest.mark.parametrize("preset", ["pew", "plasma-driven"])
def test_last_shot_of_a_five_shot_salvo_rings_out(win, preset):
    win.apply_preset(preset)
    before = win.settings.get("length_ms")
    win._on_edited("salvo_count", 5)
    win._on_committed("salvo_count")
    assert win.settings.get("length_ms") > before  # grown, and shown in the field
    assert "erhöht" in win.status.text()
    res = win.session.fire()
    assert res.shot is not None
    assert end_db(res.shot.mono, res.shot.sample_rate) < RANG_OUT_DB


def test_a_length_the_user_sets_himself_is_kept_and_he_is_warned(win):
    win.apply_preset("pew")
    win._on_edited("salvo_count", 5)
    win._on_committed("salvo_count")
    win._on_edited("length_ms", 300)
    win._on_committed("length_ms")
    assert win.settings.get("length_ms") == 300
    assert "abgeschnitten" in win.status.text()


def test_every_lengthening_field_is_a_blaster_field():
    from gui_core import blaster_params as bp

    assert bp.LENGTHENING_FIELDS <= set(bp.FIELD_NAMES) | {"bpm"}
    assert "length_ms" not in bp.LENGTHENING_FIELDS and "salvo_count" in bp.LENGTHENING_FIELDS


def test_preview_of_an_echo_preset_rings_out():
    from audio_engine.laser import render_resolved, resolve_laser_params
    from gui_core import blaster_params as bp

    s = bp.load_named_preset("blaster-echo")
    r = resolve_laser_params({**bp.preview_params(s), "seed": 1})
    assert end_db(render_resolved(r), int(r["sample_rate"])) < RANG_OUT_DB
