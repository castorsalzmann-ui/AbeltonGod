"""#515: the GUI copilot (``gui_core.chat``) renders fx through the same Toolbox and guard into
the library's FX folder. Fake model only: nothing here is evidence for Claude or Live."""

from __future__ import annotations

import json
import wave

from chat_helpers import make_chat, turn_generate, turn_text, wavs

# impact.json (kind impact) with 1 + 0.5 beats at 140 BPM: 1.5 * 60 * 48000 / 140 = 30857.14
FX = {"category": "fx", "preset": "impact", "prompt": "", "seed": 4, "variants": 1,
      "adjust": [{"key": "bpm", "value": 140}, {"key": "length_beats", "value": 1},
                 {"key": "tail_beats", "value": 0.5}]}


def test_gui_copilot_offers_fx_and_writes_it_into_the_fx_folder(tmp_path):
    session, model = make_chat(tmp_path, [turn_generate(args=FX),
                                          turn_text("Impact ist fertig.")])
    reply = session.ask("Mach einen kurzen Impact, 140 BPM")
    assert reply.success, reply.text
    # what the model was offered: generate_sample with fx in its category enum and the tempo rule
    spec = next(t for t in model.requests[0].tools if t.name == "generate_sample")
    assert "fx" in spec.input_schema["properties"]["category"]["enum"]
    assert "always put the Live project's tempo into adjust as bpm" in spec.description
    made = wavs(tmp_path / "out")
    assert len(made) == 1
    assert made[0].parent == tmp_path / "out" / "Samples" / "FX" / "Transitions"
    assert reply.files == tuple(made)
    with wave.open(str(made[0]), "rb") as w:
        assert (w.getnframes(), w.getnchannels()) == (30857, 2)
    meta = json.loads(made[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["category"] == "fx" and meta["parameters"]["bpm"] == 140
    assert meta["parameters"]["kind"] == "impact"


def test_gui_copilot_refuses_fx_without_tempo_and_writes_nothing(tmp_path):
    args = {**FX, "preset": "", "adjust": []}
    session, model = make_chat(tmp_path, [turn_generate(args=args), turn_text("Abgelehnt.")])
    reply = session.ask("Mach einen Riser")
    assert wavs(tmp_path / "out") == []
    assert reply.files == ()
    # the refusal went back to the model as an error result naming bpm
    sent = json.dumps([str(r) for r in model.requests])
    assert "bpm is required for fx" in sent
