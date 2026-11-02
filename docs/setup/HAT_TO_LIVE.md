# Hi-Hat nach Live importieren (nicht auf deinem Rechner geprüft)

Der Import (`scripts/live_import.py`) erkennt die Kategorie `hat` aus dem Sidecar und prüft, dass
die WAV im Ordner `Samples/Drums/Hats` deines Projekts liegt. Es werden dieselben Funktionen wie
beim Kick/Clap gesendet (`create_audio_track`, `create_audio_clip`, Read-backs). Es wird nichts
umbenannt und keine neue Ableton-Funktion benutzt. Bisher nur mit dem Fake-AbletonOSC in CI
geprüft, **nicht in Live**.

Ablauf wie in `docs/setup/CLAP_TO_LIVE.md`, nur mit einer Hat-WAV aus `Samples/Drums/Hats`.
Eine Hat-WAV in einem anderen Kategorie-Ordner wird mit Exit 4 abgewiesen, bevor etwas an Live
geht. Ergebnis-Block bitte als Kommentar in Issue #129 posten.

Snare folgt über denselben Registry-Weg, sobald die Snare-Stimme auf `main` ist.
