"""gui_core.reference (#480): texts and the never-raising worker function (no Qt)."""

from __future__ import annotations

from audio_engine.io import encode_wav
from audio_engine.kick import render_resolved
from gui_core import reference as G
from gui_core.form import CategoryFormModel


def test_value_texts():
    assert G.value_text("fundamental_hz", None) == "–"
    assert G.value_text("fundamental_hz", 52.04) == "52,0 Hz"
    assert G.value_text("decay_40db_ms", 312.4) == "312 ms"
    assert G.value_text("sub_share", 0.8149) == "81 %"


def test_worker_function_turns_every_failure_into_a_message(tmp_path, monkeypatch):
    out = G.analyse_reference(tmp_path / "fehlt.wav")
    assert not out.ok and "Datei nicht lesbar" in out.error

    def boom(path):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(G, "match_reference_file", boom)
    out = G.analyse_reference(tmp_path / "x.wav")
    assert not out.ok and out.error == "Analyse fehlgeschlagen: kaputt"


def test_rows_and_texts_for_a_match(tmp_path):
    from audio_engine.reference import candidates

    cand = candidates()[3]
    path = tmp_path / "r.wav"
    path.write_bytes(encode_wav(render_resolved(cand.params), 48000, 24))
    out = G.analyse_reference(path)
    assert out.ok
    rows = G.table_rows(out.match)
    assert [r[0] for r in rows] == [label for _, label, _, _ in G.ROWS]
    assert "48000 Hz, 24 Bit, Mono" in G.file_text(out.match, path)
    assert out.match.nearest.name in G.candidate_text(out.match)


def test_apply_to_form_changes_only_the_spread_fields_and_seed():
    from audio_engine.reference import candidates

    cand = next(c for c in candidates() if c.variant == 5)
    model = CategoryFormModel("kick")
    changed = G.apply_to_form(model, cand)
    assert model.preset == cand.preset
    assert "seed" in changed and set(changed) <= set(G.APPLIED_FIELDS)
    req = model.build_request()
    for name in G.APPLIED_FIELDS:
        assert req[name] == cand.params[name]
    assert req["variants"] == 1
