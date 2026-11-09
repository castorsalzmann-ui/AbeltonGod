"""German descriptions of the shipped presets for the GUI (#467). No Qt.

The preset files keep their English ``description`` (the CLI and the sidecars use it); the GUI
shows these German texts instead, keyed by ``(category, preset name)``. A preset without an entry
here (e.g. a user preset) falls back to the file's own text. A test checks that every shipped
preset has an entry.
"""

from __future__ import annotations

PRESET_TEXTS_DE: dict[tuple[str, str], str] = {
    # kick
    ("kick", "centre"): "Nahe den Medianen des gemessenen Referenzbereichs (mittlerer Endton, "
                        "sauberer Körper, mäßiger Klick), mit langsamerem Pitch-Abfall als die "
                        "meisten Referenzen (nach Gehör gewählt).",
    ("kick", "dark-dry"): "Tiefer Endton, wenig Klick, dunklere Färbung, kein Drive.",
    ("kick", "dense"): "Die Werte von centre mit bewusst zugefügtem Drive; gleicher Seed wie "
                       "centre, unterscheidet sich also nur im Drive (in Hörtests nach Gehör "
                       "gewählt).",
    ("kick", "driven"): "Maximaler Klick, helle Färbung, bewusster Drive, hoher Endton.",
    ("kick", "punchy"): "Höherer Endton, einer der zwei schnellsten Pitch-Abfälle, mehr Klick, "
                        "leichter Drive.",
    ("kick", "rumble-ready"): "Langer, sauberer, tiefer Ausklang als Quelle für eine "
                              "Rumble-Kette in Live.",
    # hat
    ("hat", "closed-loose"): "Geschlossene Hi-Hat, längerer Abfall, tiefere Hochpass-Ecke "
                             "(Startset der Hat-Zielnotiz).",
    ("hat", "closed-std"): "Geschlossene Hi-Hat, mittlerer Abfall, mittlere Hochpass-Ecke "
                           "(Startset der Hat-Zielnotiz).",
    ("hat", "closed-tight"): "Geschlossene Hi-Hat, kurzer Abfall, hohe Hochpass-Ecke "
                             "(Startset der Hat-Zielnotiz).",
    ("hat", "open-long"): "Offene Hi-Hat, langer Abfall, untere bis mittlere Hochpass-Ecke "
                          "(Startset der Hat-Zielnotiz).",
    ("hat", "open-short"): "Offene Hi-Hat, kurzer offener Abfall, mittlere Hochpass-Ecke "
                           "(Startset der Hat-Zielnotiz).",
    # snare
    ("snare", "bright"): "Höhere Hochpass-Ecke des Rauschens (Startset, N4 noise_hp_hz 3500).",
    ("snare", "default"): "Die Vertrags-Standardwerte ausgeschrieben (Körper 190 Hz, "
                          "Rausch-Abfall 180 ms).",
    ("snare", "long"): "Langer Rausch-Ausklang (Startset der Snare-Zielnotiz, N3 lang).",
    ("snare", "tight"): "Kurzer Rausch-Ausklang, höherer Körper (Startset der Snare-Zielnotiz, "
                        "N3 kurz).",
    ("snare", "tonal"): "Mehr Körper, weniger Rauschen (Startset, N2 body_level 0,85).",
    # clap
    ("clap", "bright"): "Startset B der Clap-Referenzanalyse: breiter Bandpass, hohe "
                        "Hochpass-Ecke.",
    ("clap", "default"): "Die Vertrags-Standardwerte ausgeschrieben (drei Bursts, mittlerer "
                         "Bandpass, 200 ms Nachhall).",
    ("clap", "long"): "Startset L der Clap-Referenzanalyse: vier Bursts, langer Nachhall, "
                      "mittlerer Bandpass.",
    ("clap", "short"): "Startset S der Clap-Referenzanalyse: vier Bursts, kurzer Nachhall, "
                       "mittlerer Bandpass.",
    ("clap", "xtreme-crushed"): "Bit-Reduktion und Sample-and-Hold-Ratenreduktion, höhere "
                                "Hochpass-Ecke.",
    ("clap", "xtreme-folded"): "Höhere Bandpass-Mitte mit Sinus-Wavefolding.",
    ("clap", "xtreme-gated"): "Langer Nachhall, von einem harten Gate abgeschnitten.",
    ("clap", "xtreme-metal"): "Ringmodulation mit 400-Hz-Träger plus Kammfilter mit "
                              "Rückkopplung.",
    ("clap", "xtreme-reversed"): "Kräftiger, mittellanger Nachhall, zeitlich umgekehrt "
                                 "(Anschwellen am Ende).",
    ("clap", "xtreme-saturated"): "Standard-Stimme, nur mit starkem Drive.",
    ("clap", "xtreme-wreck"): "Drive, Wavefolder, Bit-Reduktion, Ratenreduktion und Kammfilter "
                              "zusammen; das obere Ende des Bereichs, kein Ausgangspunkt.",
    # rim
    ("rim", "clave"): "Ein einzelner Teilton nahe 2500 Hz, kein oberer Teilton (level2 0), "
                      "Startset.",
    ("rim", "high"): "Höherer unterer Teilton (Startset, Platzhalterwerte).",
    ("rim", "long"): "Längerer Abfall beider Teiltöne (Startset, Platzhalterwerte).",
    ("rim", "rim"): "Die Vertrags-Standardwerte ausgeschrieben (zwei gedämpfte Teiltöne, kurzer "
                    "Rausch-Klick).",
    ("rim", "tight"): "Kürzerer Abfall beider Teiltöne (Startset, Platzhalterwerte).",
    # bass
    ("bass", "bright"): "Sägezahn, Rechteck und Sinus, höhere Grenzfrequenz, mehr Resonanz, "
                        "tiefere Filter-Hüllkurve.",
    ("bass", "default"): "Die Vertrags-Standardwerte ausgeschrieben (Note 43, Sägezahn plus "
                         "Sinus, 250 ms Gate).",
    ("bass", "goa-roll-long"): "Hypothese Goa-Rollbass: Gate knapp unter einer 16tel bei "
                               "140-146 BPM, langsameres Schließen des Filters, Sägezahn plus "
                               "Sinus auf Note 36.",
    ("bass", "goa-roll-medium"): "Hypothese Goa-Rollbass: Gate etwa 0,8 einer 16tel bei "
                                 "140-146 BPM, mittleres Schließen des Filters, Sägezahn plus "
                                 "Sinus auf Note 36.",
    ("bass", "goa-roll-short"): "Hypothese Goa-Rollbass: Gate etwa 0,6 einer 16tel bei "
                                "140-146 BPM, schnelles Schließen des Filters, Sägezahn plus "
                                "Sinus auf Note 36.",
    ("bass", "low"): "Die Standardwerte auf Note 31 mit längerem Gate (eine Hypothese aus der "
                     "Recherche zur Note).",
    ("bass", "rolling"): "Gate etwa eine 16tel bei 136 BPM, kurzes Release, tiefere "
                         "Filter-Hüllkurve.",
    ("bass", "sub"): "Sinus mit leisem Sinus eine Oktave tiefer, tiefe Grenzfrequenz, keine "
                     "Filter-Hüllkurve, kein Drive.",
    # laser
    ("laser", "blaster"): "Basisschuss (v0.2): Plasma 1900 bis 110 Hz über 700 ms, Drive 0,15, "
                          "Tiefpass 24 dB/Okt. bei 3 kHz, kein Rauschen / Knistern / FM, mittig.",
    ("laser", "blaster-burst5"): "Blaster, Salve aus 5 Schüssen bei 12 Schuss/s mit "
                                 "beschleunigter Rate, Schwenk links nach rechts, Humanize 0,3.",
    ("laser", "blaster-double"): "Blaster, Salve aus 2 Schüssen im Abstand 160 ms, -3 dB pro "
                                 "Schuss.",
    ("laser", "blaster-echo"): "Blaster mit tempo-synchronem (1/8 bei 128 BPM), gedämpftem "
                               "Ping-Pong-Echo.",
    ("laser", "blaster-reverb"): "Blaster mit 1,8 s algorithmischem Hall (Anteil 0,35).",
    ("laser", "blaster-triple-lrl"): "Blaster, Salve aus 3 Schüssen im Abstand 150 ms, "
                                     "links-rechts-links.",
    ("laser", "glitch"): "Dimension glitch: gestufte Tonhöhe mit Gate pro Stufe, "
                         "Knister-Verstimmung, Echo.",
    ("laser", "ion"): "Dimension ion: Sinus mit zwei unharmonischen oberen Teiltönen, "
                      "steigender Sweep, Echo, breit.",
    ("laser", "pew"): "Dimension pew: Sinus-Sweep von hoch nach tief, kurzer Abfall, keine "
                      "Modulation.",
    ("laser", "pew-wide-echo"): "Dimension pew mit Ping-Pong-Echo und voller Stereobreite.",
    ("laser", "plasma"): "Dimension plasma: bandbegrenzter Sägezahn-Sweep mit FM, Rauschen und "
                         "Knistern.",
    ("laser", "plasma-driven"): "Dimension plasma mit Drive und später Sweep-Kurve.",
    ("laser", "rift"): "Dimension rift: zwei gespiegelte Sweeps, Ringmodulation, Rauschen, "
                       "langer Abfall, breit.",
    ("laser", "subboom"): "Dimension subboom: Sweep-Stimme plus Sub-Schicht zwei Oktaven tiefer, "
                          "langer Abfall.",
    # perc (#475)
    ("perc", "bongo"): "Modell Conga eine Oktave höher, kürzerer Abfall, Glide und Tick wie "
                       "die Conga des Artefakts (Platzhalterwerte).",
    ("perc", "clave"): "Modell Clave mit Grundwerten (Sinus 2400 Hz), leiser Tick, Hochpass "
                       "400 Hz.",
    ("perc", "conga"): "Die Vertrags-Standardwerte ausgeschrieben (Modell Conga, Grundton C4, "
                       "Glide 1,25, Tick 0,2).",
    ("perc", "conga-dry"): "Conga ohne Tick, kürzerer Abfall (Platzhalterwerte).",
    ("perc", "cowbell"): "Modell Cowbell mit Grundwerten (Rechtecke 540 + 800 Hz, Bandpass "
                         "2,6 kHz), leiser Tick.",
    ("perc", "hard-groove-tom"): "Tom nur für Hard Groove (D-032): Grundton C3, Tick und "
                                 "Glide-Zeit wie die Tom des Artefakts.",
    ("perc", "hard-groove-tom-low"): "Tom nur für Hard Groove (D-032): 5 Halbtöne tiefer, "
                                     "längerer Abfall, leichter Drive.",
    ("perc", "shaker"): "Modell Shaker mit Grundwerten (bandgefiltertes Rauschen, 12 ms "
                        "Anstieg).",
    ("perc", "shaker-long"): "Shaker mit doppeltem Abfall, langsamerem Anstieg, 3 Halbtöne "
                             "tiefer.",
    # fx (#482): all written at 135 BPM; the tempo must match the track
    # risers (#547): the level starts at -60 dB, so the start is near silence
    ("fx", "riser-8bar"): "Rausch-Riser über 8 Takte: Bandpass steigt, Pegel steigt von "
                          "-60 dB aus. Gespeichert mit 135 BPM: Tempo auf den Track "
                          "einstellen.",
    ("fx", "riser-16bar"): "Rausch-Riser über 16 Takte: Bandpass steigt, Pegel steigt von "
                           "-60 dB aus. Gespeichert mit 135 BPM: Tempo auf den Track "
                           "einstellen.",
    ("fx", "riser-32bar"): "Rausch-Riser über 32 Takte: Bandpass steigt, Pegel steigt von "
                           "-60 dB aus. Gespeichert mit 135 BPM: Tempo auf den Track "
                           "einstellen.",
    ("fx", "downlifter"): "Rausch-Downlifter über 2 Takte: Bandpass fällt, Pegel fällt "
                          "(Standardwerte der Art). Gespeichert mit 135 BPM: Tempo auf den "
                          "Track einstellen.",
    ("fx", "sweep"): "Resonanter Tiefpass-Rausch-Sweep über 4 Takte (Standardwerte der Art). "
                     "Gespeichert mit 135 BPM: Tempo auf den Track einstellen.",
    ("fx", "impact"): "Kurzer Rauschstoß mit fallendem Sinus und langem Hall (Standardwerte "
                      "der Art). Gespeichert mit 135 BPM: Tempo auf den Track einstellen.",
    ("fx", "noise-crash"): "Hochpass-Rauschen, das ab dem Drop über 4 Takte ausblendet "
                           "(Standardwerte der Art). Gespeichert mit 135 BPM: Tempo auf den "
                           "Track einstellen.",
    ("fx", "reverse-crash"): "Metallische Teiltöne und Rauschen werden über einen Takt lauter "
                             "und enden genau auf dem Taktstrich (Standardwerte der Art). "
                             "Gespeichert mit 135 BPM: Tempo auf den Track einstellen.",
    # atmos (#533): all written at 135 BPM; note names as in Live (MIDI 36 = C1, 60 = C3)
    ("atmos", "air-bed"): "Rausch-Fläche mit den Standardwerten der Art: geneigtes Rauschen, "
                          "Hoch- und Tiefpass, langsam wandernder Tiefpass, 8 Takte. "
                          "Gespeichert mit 135 BPM: Tempo auf den Track einstellen.",
    ("atmos", "dark-bed"): "Rausch-Fläche mit tieferem Tiefpass und einem Hall, der ab 400 Hz "
                           "gedämpft wird (die dunkle Variante der Recherche-Notiz), 8 Takte. "
                           "Gespeichert mit 135 BPM: Tempo auf den Track einstellen.",
    ("atmos", "pumping-bed"): "Rausch-Fläche mit einem Pegel-Einbruch auf jedem Beat und "
                              "zufällig geformter langsamer Bewegung, 4 Takte. Gespeichert mit "
                              "135 BPM: Tempo auf den Track einstellen.",
    ("atmos", "drone-root-fifth"): "Drone mit den Standardwerten der Art: Grundton C1, Quinte "
                                   "und Oktave, schwebende Paare und langsame Pegel-Drift, "
                                   "8 Takte. Gespeichert mit 135 BPM: Tempo auf den Track "
                                   "einstellen.",
    ("atmos", "drone-octaves-e1"): "Drone auf E0 (MIDI 28) in drei Oktaven mit breiteren "
                                   "schwebenden Paaren, 16 Takte. Gespeichert mit 135 BPM: "
                                   "Tempo auf den Track einstellen.",
    ("atmos", "resonant-bed"): "Rauschen durch Resonatoren auf den Teiltönen von C1, Quinte "
                               "und Oktave (Standardwerte der Art), 8 Takte. Gespeichert mit "
                               "135 BPM: Tempo auf den Track einstellen.",
    ("atmos", "granular-drone"): "Grains der internen C1-Drone, verstreut in Zeit und Panorama "
                                 "(Standardwerte der Art), 8 Takte. Gespeichert mit 135 BPM: "
                                 "Tempo auf den Track einstellen.",
    ("atmos", "granular-metal"): "Kurze Grains der metallischen Rechteck-Bank auf C2 (MIDI 48) "
                                 "mit zufälligen Tonhöhen-Abweichungen, 8 Takte. Gespeichert "
                                 "mit 135 BPM: Tempo auf den Track einstellen.",
}


def preset_text_de(category: str, preset: str, fallback: str) -> str:
    """The German description of a shipped preset, else ``fallback`` (the file's own text)."""
    return PRESET_TEXTS_DE.get((category, preset), fallback)
