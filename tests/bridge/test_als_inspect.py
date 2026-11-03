"""als_inspect reads a gzip XML set. The XML below is SYNTHETIC: it only exercises the
script's reading code and says nothing about Live's real schema (that is what the user's
own saved set, test S1 of the delivery note, is for)."""

import gzip
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "als_inspect", Path(__file__).resolve().parents[2] / "scripts" / "als_inspect.py")
als = importlib.util.module_from_spec(spec)
spec.loader.exec_module(als)

XML = b"""<Ableton MajorVersion="5" Creator="synthetic"><LiveSet>
<MasterTrack><DeviceChain><Mixer><Tempo><Manual Value="145"/></Tempo></Mixer>
</DeviceChain></MasterTrack>
<Tracks><MidiTrack><Name><EffectiveName Value="bass"/></Name>
<MidiClip/><MidiClip/><MidiNoteEvent/></MidiTrack><AudioTrack/></Tracks>
<Locators><Locators><Locator><Name Value="Intro"/><Time Value="0"/></Locator></Locators></Locators>
</LiveSet></Ableton>"""


def test_summary_of_synthetic_set(tmp_path):
    p = tmp_path / "s.als"
    p.write_bytes(gzip.compress(XML))
    text = "\n".join(als.summarise(als.load_set(p)))
    assert "tempo (Master Tempo/Manual): 145" in text
    assert "track MidiTrack: 'bass', clips: 2, notes: 1" in text
    assert "track AudioTrack: '(no EffectiveName)', clips: 0" in text
    assert "locator 'Intro' at beat 0" in text


def test_unknown_layout_reports_not_found(tmp_path):
    p = tmp_path / "s.als"
    p.write_bytes(gzip.compress(b"<Ableton><LiveSet/></Ableton>"))
    text = "\n".join(als.summarise(als.load_set(p)))
    assert "tempo (Master Tempo/Manual): not found" in text and "Tracks: not found" in text


def test_bad_file_exit_code(tmp_path, capsys):
    p = tmp_path / "x.als"
    p.write_bytes(b"\x00\x01garbage")
    assert als.main([str(p)]) == 2
    assert als.main([str(tmp_path / "missing.als")]) == 2
