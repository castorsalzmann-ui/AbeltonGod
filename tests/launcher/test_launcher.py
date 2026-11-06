"""Launcher dispatch and menu (#401). Linux CI; the exe itself is smoke-tested on Windows by
.github/workflows/build-exe.yml."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from launcher import cli, tools
from launcher.tools import BY_NAME, TOOLS, Tool

# Written out here, not derived from the table under test.
EXPECTED_TOOLS = {
    "kick", "hat", "snare", "clap", "rim", "bass", "goa-arrangement", "goa-melody",
    "goa-patterns", "arrangement-midi", "live-import", "kick-to-live", "bridge-check",
    "arrangement-check", "install-abletonosc", "als-inspect", "plan", "chat",
}


def test_table_has_exactly_the_expected_tools():
    assert {t.name for t in TOOLS} == EXPECTED_TOOLS
    assert len(TOOLS) == len(EXPECTED_TOOLS)


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t.name)
def test_every_tool_resolves_to_a_real_main(tool: Tool):
    main = tools.resolve(tool)
    assert callable(main) and main.__name__ == "main"
    module = tool.module
    assert main.__module__ == module


@pytest.mark.parametrize("name,prefix", [
    ("kick", []), ("hat", ["--category", "hat"]), ("snare", ["--category", "snare"]),
    ("clap", ["--category", "clap"]), ("rim", ["--category", "rim"]),
    ("bass", ["--category", "bass"]),
])
def test_sound_tools_go_to_audio_engine_cli_with_category(monkeypatch, name, prefix):
    seen = []
    monkeypatch.setattr(tools, "resolve", lambda tool: lambda argv: seen.append(argv) or 0)
    assert tools.run_tool(BY_NAME[name], ["--preset", "x"]) == 0
    assert seen == [[*prefix, "--preset", "x"]]
    assert BY_NAME[name].module == "audio_engine.cli"


def test_exit_codes_pass_through(monkeypatch):
    monkeypatch.setattr(tools, "resolve", lambda tool: lambda argv: 5)
    assert tools.run_tool(BY_NAME["kick"], []) == 5
    monkeypatch.setattr(tools, "resolve", lambda tool: lambda argv: None)
    assert tools.run_tool(BY_NAME["kick"], []) == 0

    def exits(argv):
        raise SystemExit(2)

    monkeypatch.setattr(tools, "resolve", lambda tool: exits)
    assert tools.run_tool(BY_NAME["kick"], []) == 2


def test_real_kick_renders_a_wav(tmp_path: Path):
    code = cli.main(["kick", "--preset", "centre", "--seed", "7", "--out", str(tmp_path)])
    assert code == 0
    assert len(list(tmp_path.glob("*.wav"))) == 1


def test_real_goa_arrangement_through_launcher(tmp_path: Path):
    out = tmp_path / "goa"
    assert cli.main(["goa-arrangement", "--no-samples", "--out", str(out)]) == 0
    assert list(out.glob("*.mid"))


def test_unknown_tool_exits_2_with_list(capsys):
    assert cli.main(["nope"]) == 2
    err = capsys.readouterr().err
    assert "nope" in err
    for name in EXPECTED_TOOLS:
        assert name in err


def test_version_and_help(capsys):
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.startswith("AbeltonGod ")
    assert cli.main(["--help"]) == 0
    out = capsys.readouterr().out
    assert all(name in out for name in EXPECTED_TOOLS)


def test_menu_with_piped_stdin_runs_kick(tmp_path: Path):
    lines = iter(["kick", str(tmp_path / "o"), "--seed 7", ""])
    out = io.StringIO()
    code = cli.main(["--menu"], read=lambda prompt: next(lines), out=out)
    assert code == 0
    assert "Fertig (Exit-Code 0)" in out.getvalue()
    assert len(list((tmp_path / "o").glob("*.wav"))) == 1


def test_menu_by_number_and_new_subfolder(tmp_path: Path):
    n = [t.name for t in TOOLS].index("goa-melody") + 1
    lines = iter([str(n), str(tmp_path), "", ""])
    out = io.StringIO()
    assert cli.main(["--menu"], read=lambda prompt: next(lines), out=out) == 0
    assert list((tmp_path / "goa-melody").glob("*.mid"))


def test_menu_unknown_choice_and_eof():
    out = io.StringIO()
    lines = iter(["zzz", ""])
    assert cli.main(["--menu"], read=lambda p: next(lines), out=out) == 2

    def eof(prompt):
        raise EOFError

    assert cli.main(["--menu"], read=eof, out=io.StringIO()) == 0


def test_no_arguments_start_the_gui_and_pass_its_exit_code():
    calls = []

    def fake_gui():
        calls.append(1)
        return 7

    def no_read(prompt):
        raise AssertionError("the text menu must not run when the GUI starts")

    assert cli.main([], read=no_read, out=io.StringIO(), gui=fake_gui) == 7
    assert calls == [1]


def test_no_arguments_without_pyside_fall_back_to_the_text_menu():
    out = io.StringIO()
    code = cli.main([], read=lambda p: "", out=out, gui=lambda: None)
    assert code == 0
    text = out.getvalue()
    assert "PySide6 fehlt" in text and "Werkzeuge:" in text


def test_arguments_never_start_the_gui(tmp_path: Path):
    def boom():
        raise AssertionError("GUI started although arguments were given")

    for argv in (["--version"], ["--list"], ["kick", "--help"], ["nope"]):
        cli.main(argv, read=lambda p: "", out=io.StringIO(), gui=boom)
    out = tmp_path / "k"
    assert cli.main(["kick", "--preset", "centre", "--seed", "7", "--out", str(out)],
                    gui=boom) == 0
    assert len(list(out.glob("*.wav"))) == 1


def test_incomplete_install_blocks_the_gui(monkeypatch):
    monkeypatch.setattr(cli, "install_problems", lambda: ["contracts/ fehlt"])
    out = io.StringIO()
    assert cli.main([], read=lambda p: "", out=out, gui=lambda: 0) == cli.EXIT_SETUP
    assert "contracts/ fehlt" in out.getvalue()


def test_free_subdir_never_reuses(tmp_path: Path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x_2").mkdir()
    assert cli.free_subdir(tmp_path, "x") == tmp_path / "x_3"


def test_split_keeps_windows_paths():
    assert cli._split(r'--out "C:\My Files\a" --seed 3') == ["--out", r"C:\My Files\a",
                                                              "--seed", "3"]
