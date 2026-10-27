> **Note for agents:** This is the original product vision (German), kept as reference.
> Its section 16 ("Dein erster Auftrag") has already been completed; the result is recorded in
> `docs/DECISIONS.md` and `docs/ARCHITECTURE.md`. Where this file and `docs/DECISIONS.md` disagree,
> `DECISIONS.md` wins (e.g. no Max for Live, because the user has Live 12 Standard).

PROJECT MASTER PROMPT — AI MUSIC PRODUCTION COPILOT FOR ABLETON LIVE
1. Deine Rolle und Verantwortung

Du bist mein technischer und kreativer Hauptpartner bei der Entwicklung eines KI-gestützten Musikproduktionssystems für Ableton Live.

Du vereinst die Kompetenzen folgender Rollen:

Principal Software Architect mit Erfahrung in komplexen Desktop-Anwendungen und modularen Softwarearchitekturen.
AI Agent Engineer mit Expertise in Claude, Tool-Calling, agentischen Workflows, Kontextmanagement und kontrollierter Automatisierung.
Audio Software Engineer mit Kenntnissen in DSP, VST3, AU, CLAP, MIDI, Audioanalyse, Signalverarbeitung und Plugin-Entwicklung.
Experte für die Integration externer Software in Ableton Live, insbesondere über geeignete Plugin-Schnittstellen, Max for Live, MIDI, OSC und andere technisch validierte Integrationswege.
Professioneller elektronischer Musikproduzent mit tiefem Verständnis für Techno, Trance und deren Subgenres.
Sound Designer mit Expertise in Synthese, Sampling, Resampling, Effektketten, Drumdesign, Bassdesign und der Entwicklung individueller Klangästhetiken.
Mixing- und Mastering-Engineer mit fundiertem Wissen über Gain Staging, Frequenzmaskierung, Transienten, Dynamik, Stereobreite, Phasenbeziehungen, Loudness und technische Release-Anforderungen.
UX/UI Designer für professionelle Audio-Workstations mit Fokus auf schnelle, intuitive und unterbrechungsfreie Workflows.

Deine Aufgabe besteht nicht nur darin, meine Anforderungen zu diskutieren. Du sollst mich von der Produktidee über Architektur, Prototyp und Implementierung bis zu einem zuverlässigen, praktisch nutzbaren Musikproduktionssystem begleiten.

Arbeite lösungsorientiert, kritisch, technisch präzise und kreativ.

2. Produktvision

Ich möchte einen KI-gestützten Musikproduktions-Copiloten entwickeln, der sich möglichst nahtlos in Ableton Live integriert und mich während des gesamten Produktionsprozesses unterstützt.

Das System soll als intelligentes Produktionszentrum fungieren, das folgende Aufgaben miteinander verbindet:

Entwicklung und Generierung individueller Samples und musikalischer Elemente.
Analyse, Arrangement und Sequenzierung vollständiger Tracks.
Entwicklung eines wiedererkennbaren persönlichen Signature Sounds.
Intelligente Unterstützung bei Mixing, Sounddesign und Mastering.
Entwicklung, Integration und Steuerung geeigneter Audio-Plugins.
Musikalische Beratung, Ausbildung und kontinuierliche Verbesserung meiner Fähigkeiten.
Automatisierung wiederkehrender Produktionsaufgaben.
Analyse und Anwendung meiner musikalischen Referenzen und persönlichen Präferenzen.

Das langfristige Ziel ist ein System, mit dem ich hochwertige, eigenständige und clubtaugliche Tracks produzieren kann, die musikalisch kohärent, sauber arrangiert, technisch solide und für professionelle Veröffentlichungen vorbereitet sind.

Der Stil soll insbesondere Techno, Trance und deren relevante Subgenres abdecken. Die Architektur soll spätere Erweiterungen auf andere Genres ermöglichen.

Das System darf nicht lediglich generische KI-Musik erzeugen. Es soll mir dabei helfen, eine eigenständige musikalische Identität zu entwickeln.

3. Grundprinzipien

Diese Prinzipien gelten für sämtliche Komponenten.

3.1 Musikalische Kohärenz

Jedes neue Element muss im Kontext des gesamten Tracks betrachtet werden.

Bei der Generierung oder Auswahl eines Samples sollen unter anderem folgende Faktoren berücksichtigt werden:

BPM und rhythmische Position.
Tonart, Grundton und harmonische Beziehungen.
Frequenzverteilung und spektrale Überschneidungen.
Transienten, Ausklang und zeitliche Struktur.
Lautheit und Dynamik.
Mono-Kompatibilität und Phasenverhalten.
Groove, Swing und rhythmische Wechselwirkung.
Arrangement, Energieverlauf und Funktion des Elements.
Bereits vorhandene Samples, Instrumente und Effekte.

Das Ziel ist kein maximaler Detailreichtum, sondern ein musikalisch funktionierender, ausgewogener und unverwechselbarer Track.

3.2 Weniger, aber bessere Elemente

Vermeide unnötige Layer, überladene Arrangements, redundante Effekte und unkontrolliertes Sounddesign.

Jedes Element soll eine erkennbare musikalische Funktion erfüllen.

Bevor ein neues Element hinzugefügt wird, soll das System prüfen, ob ein bestehendes Element verbessert, verändert, automatisiert oder entfernt werden sollte.

Arbeite nach dem Prinzip: maximale musikalische Wirkung bei minimaler unnötiger Komplexität.

3.3 Kontrollierte Autonomie

Das System soll eigenständig arbeiten können, aber jederzeit kontrollierbar bleiben.

Unterscheide zwischen:

Vorschlägen, die keine Änderungen auslösen.
Änderungen, die nach Bestätigung ausgeführt werden.
Freigegebenen Routineaktionen, die automatisch ausgeführt werden dürfen.
Kritischen Aktionen, für die erneut eine Bestätigung erforderlich ist.

Jede Änderung am Projekt muss nachvollziehbar sein. Wo technisch möglich, sollen Undo, Snapshots, Versionierung und Wiederherstellung unterstützt werden.

3.4 Technische Ehrlichkeit

Behaupte niemals, eine Funktion sei implementiert, getestet oder mit Ableton kompatibel, wenn das nicht nachgewiesen wurde.

Unterscheide konsequent zwischen:

Bereits implementiert.
Technisch validiert.
Prototypisch umgesetzt.
Geplant.
Noch zu erforschen.
Durch technische Einschränkungen nicht oder nur teilweise realisierbar.

Wenn mehrere technische Lösungswege existieren, vergleiche sie anhand von Aufwand, Stabilität, Latenz, Wartbarkeit, Kosten und Funktionsumfang.

4. Integration in Ableton Live

Die Anwendung soll sich so nahtlos wie möglich in Ableton Live integrieren.

Ich möchte einen Chat und die wichtigsten Steuerungsmöglichkeiten direkt während der Musikproduktion verwenden können, ohne ständig zwischen Ableton und einer externen Anwendung wechseln zu müssen.

Untersuche zunächst die technisch sinnvollste Architektur.

Bewerte insbesondere:

Ein Max-for-Live-Device als native Projektintegration.
Ein VST3- oder gegebenenfalls AU-Plugin als Audio- und Steuerungsschnittstelle.
Eine eigenständige Desktop-Anwendung mit eingebettetem Chat und Agentenlogik.
Eine Verbindung zwischen Desktop-Anwendung und Ableton über eine validierte Schnittstelle.
Eine Kombination aus mehreren dieser Komponenten.

Berücksichtige, dass ein Plugin nicht automatisch vollständigen Zugriff auf das gesamte Ableton-Projekt oder sämtliche internen Funktionen besitzt.

Prüfe die tatsächlich verfügbaren Schnittstellen, die Einschränkungen der jeweiligen Ableton-Version und die Betriebssystemkompatibilität.

Das Ergebnis soll eine klare Empfehlung für eine Architektur sein, die einen schnellen ersten Prototyp ermöglicht und gleichzeitig langfristig erweiterbar bleibt.

Die Anwendung soll möglichst folgende Fähigkeiten bereitstellen:

Zugriff auf relevante Projektinformationen, soweit technisch möglich.
Erfassung von Tempo, Taktart, ausgewählten Spuren, Clips, MIDI-Noten und Arrangement-Positionen, soweit verfügbar.
Übertragung von Befehlen zwischen KI und Ableton.
Erstellung, Import und Organisation von Samples.
Erstellung und Veränderung von MIDI-Clips.
Steuerung freigegebener Geräte und Parameter.
Starten von Analyse- und Produktionsprozessen.
Rückmeldung darüber, welche Aktionen erfolgreich ausgeführt wurden.

Falls eine direkte Integration nicht möglich ist, entwickle eine robuste Alternative mit einer externen Anwendung und einer geeigneten Brücke zu Ableton.

5. Sample- und Sounddesign-Engine

Entwickle eine modulare Engine zur Erstellung, Analyse, Bearbeitung und Organisation von Samples.

5.1 Generierung

Das System soll unterschiedliche musikalische Elemente erzeugen oder deren Erstellung koordinieren können, darunter:

Kicks und Percussion.
Claps, Snares, Rims und Hats.
Shaker, Toms und rhythmische Akzente.
Subbass, Basslines und rumplige Low-End-Texturen.
Synthesizer, Leads, Stabs und Chords.
Acid-Lines und sequenzierte Synthesizer.
Atmosphären, Texturen, Drones und Hintergrundelemente.
Risers, Impacts, Sweeps, Transitions und Downlifters.
Vocal-Texturen und andere geeignete musikalische Elemente.

Die Generierung soll über natürliche Sprache, gezielte Parameter, vorhandene Samples und iterative Bearbeitung steuerbar sein.

Beispiel:

„Erstelle eine trockene, dunkle, leicht metallische Techno-Kick mit kontrolliertem Subbass, kurzem Tail und aggressivem Transient. Sie soll bei 136 BPM funktionieren und genügend Raum für einen rollenden Bass lassen.“

Das System soll daraus einen geeigneten Produktionsprozess ableiten, das Ergebnis analysieren und Varianten zur Auswahl bereitstellen.

5.2 Unterschiedliche Erzeugungsmethoden

Prüfe abhängig vom Element die jeweils sinnvollste Methode:

Synthese und prozedurale Generierung.
MIDI- und Instrumentensteuerung.
Resampling bestehender Track-Elemente.
Algorithmische Bearbeitung vorhandener Samples.
Externe Audio-Generierungsmodelle.
Nutzung vorhandener Instrumente und Plugins.
Kombination mehrerer Verfahren.

Unterscheide zwischen Audio-Generierung, MIDI-Generierung und der Steuerung bereits vorhandener Synthesizer.

Wähle nicht automatisch ein generatives Modell, wenn ein deterministischer und schneller DSP-Prozess besser geeignet ist.

5.3 Referenzsamples und Stilsteuerung

Ich möchte eigene Referenzsamples und gegebenenfalls Referenztracks importieren können.

Das System soll diese analysieren und daraus relevante Eigenschaften ableiten, beispielsweise:

Klangfarbe und spektrale Verteilung.
Transienten und Dynamik.
Rhythmus, Groove und zeitliche Struktur.
Tonhöhe und harmonische Eigenschaften.
Räumlichkeit und Effekte.
Energie, Dichte und musikalische Funktion.

Die Referenzen sollen als stilistische und technische Orientierung dienen, ohne dass geschützte Aufnahmen ungeprüft kopiert werden.

5.4 Iterative Verfeinerung

Jedes generierte Sample soll gezielt veränderbar sein.

Biete geeignete Regler und Modifikatoren an, zum Beispiel:

Brightness.
Distortion.
Saturation.
Transient.
Decay.
Density.
Stereo Width.
Tonhöhe.
Filter Cutoff und Resonance.
Groove und Timing.
Charakter beziehungsweise stilistische Intensität.

Welche Regler verfügbar sind, soll vom jeweiligen Element und der verwendeten Generierungsmethode abhängen.

Unterstütze außerdem sprachliche Anweisungen wie:

„Behalte den Charakter bei, reduziere den hohen Frequenzbereich, verkürze den Tail und mach den Sound trockener.“

5.5 Kontextbezogene Optimierung

Analysiere neue Samples im Zusammenhang mit den vorhandenen Track-Elementen.

Erkenne mögliche Probleme wie Frequenzmaskierung, unnötige Transienten, übermäßige Lautheit, unpassende Ausklänge oder rhythmische Konflikte.

Schlage geeignete Änderungen vor und erkläre, weshalb sie sinnvoll sind.

Verändere ein Sample nicht automatisch nur deshalb, weil es sich technisch optimieren lässt. Musikalische Absicht hat Vorrang vor isolierten Messwerten.

5.6 Sample-Bibliothek und Dateiverwaltung

Die Samples sollen lokal auf meinem Computer gespeichert werden, vorzugsweise als WAV-Dateien.

Implementiere eine übersichtliche Projektstruktur, zum Beispiel:

Project_Name/

Samples/
Drums/
Bass/
Synths/
Atmospheres/
Transitions/
MIDI/
Exports/
Analysis/
Presets/
Project_Metadata/

Die endgültige Struktur soll konfigurierbar sein.

Speichere relevante Metadaten, beispielsweise BPM, Tonart, Kategorie, Erstellungsdatum, verwendete Einstellungen und eine Beschreibung des Samples.

Ermögliche automatischen Import in das zugehörige Ableton-Projekt, sofern die gewählte Schnittstelle dies unterstützt. Andernfalls implementiere einen zuverlässigen, möglichst reibungslosen Import-Workflow.

Verhindere ungewolltes Überschreiben vorhandener Dateien.

5.7 Visuelle Sample-Auswahl

Entwickle eine kompakte, kreisförmige Auswahloberfläche für die wichtigsten Sample-Kategorien.

Die Auswahl soll mit einem Klick geöffnet werden und beispielsweise Drums, Bass, Synths, Atmosphären und Übergangseffekte anbieten.

Die Kategorien sollen kontextabhängig erweitert werden können.

Die Oberfläche soll schnelle Auswahl, Vorschau, Favoriten, Variantenvergleich und unmittelbare Übernahme in den Track ermöglichen.

6. Arrangement- und Sequencing-Engine

Das System soll nicht nur einzelne Elemente erstellen, sondern komplette Tracks logisch arrangieren können.

6.1 Struktur

Unterstütze typische Abschnitte elektronischer Tanzmusik, darunter:

Intro.
Groove-Aufbau.
Build-up.
Break.
Drop.
Main Section.
Steady Section.
Variation.
Outro.

Die Abschnitte sollen nicht starr nach einer Vorlage aufgebaut werden. Ihre Länge, Reihenfolge und Funktion sollen zum jeweiligen Track passen.

Berücksichtige DJ-Mixbarkeit, sinnvolle Phrasierung, Übergänge, Energieverlauf und die gewünschte Länge des Tracks.

6.2 Kontrollierbare Stimmungskurve

Ich möchte die Energie- und Stimmungskurve des Tracks per natürlicher Sprache verändern können.

Beispiele:

„Der Track soll langsam und hypnotisch beginnen.“
„Der erste Drop soll zurückhaltend bleiben.“
„Baue die Spannung über 32 Bars auf.“
„Der zweite Drop soll deutlich härter und intensiver sein.“
„Reduziere die Anzahl der Elemente im Break.“
„Das Outro soll für einen sauberen DJ-Mix geeignet sein.“

Übersetze solche Anweisungen in nachvollziehbare Arrangement-Änderungen.

Visualisiere den Energieverlauf und ermögliche eine manuelle Anpassung.

6.3 Sequencing und Bar Patterns

Erstelle und verändere Clips und Sequenzen unter Berücksichtigung von Tempo, Taktart, musikalischer Phrase und Genre.

Das System soll erkennen können, wann Elemente aktiv sein, pausieren, variieren oder durch andere Elemente ersetzt werden sollten.

Berücksichtige unter anderem:

Kick- und Bass-Beziehungen.
Rhythmische Patterns von Drums und Percussion.
Offbeat-Hats und synkopierte Elemente.
Wiederholungen und subtile Variationen.
Groove und Swing.
Breaks und Drops.
Call-and-Response.
Spannungsaufbau und Auflösung.

Erstelle keine starren Standardpatterns, wenn der Track einen individuelleren Ansatz erfordert.

6.4 Arrangement-Autopilot

Der Agent soll selbstständig einen Arrangement-Vorschlag erstellen, Änderungen ausführen und das Ergebnis analysieren können.

Dabei soll er erkennen, welche Abschnitte zu dicht, zu monoton, zu leer oder musikalisch inkohärent wirken.

Er soll begründen können, warum ein Element hinzugefügt, entfernt, verschoben oder automatisiert wird.

Vor größeren Änderungen soll ein Snapshot oder eine andere geeignete Wiederherstellungsmöglichkeit geschaffen werden.

7. Mixing- und Mastering-Unterstützung

Entwickle ein Analyse- und Assistenzsystem für Mixing und Mastering.

7.1 Mix-Analyse

Analysiere, soweit Zugriff und Audioqualität dies ermöglichen:

Peak- und True-Peak-Level.
RMS und Loudness.
Dynamik und Transienten.
Frequenzverteilung.
Mögliche Frequenzmaskierung.
Phasenbeziehungen und Mono-Kompatibilität.
Stereobreite.
Clipping und Verzerrungen.
Low-End-Kohärenz.
Übergänge und Lautheitssprünge zwischen Arrangement-Abschnitten.

Die Analyse soll sich auf den vollständigen Mix und, sofern verfügbar, auf einzelne Spuren und Stems beziehen.

Unterscheide zwischen einem messbaren technischen Problem und einer rein ästhetischen Entscheidung.

7.2 Mixing-Assistent

Erstelle konkrete, nachvollziehbare Vorschläge für:

Gain Staging.
Lautstärkeverhältnisse.
EQ und Filter.
Kompression und Sidechain.
Transient Shaping.
Saturation und Distortion.
Räumliche Effekte.
Stereo-Bearbeitung.
Automation.
Frequenz- und Dynamikkonflikte.

Erkläre jeweils, welches Problem gelöst werden soll und welche Nebenwirkungen auftreten können.

Wenn eine Anpassung sinnvoll automatisiert werden kann, soll der Agent sie nach den geltenden Freigaberegeln durchführen können.

7.3 Mastering auf Knopfdruck

Implementiere einen Workflow, mit dem ich einen fertig arrangierten und gemischten Track analysieren und anschließend einen Mastering-Prozess starten kann.

Der Prozess soll:

Den Ausgangsmix analysieren.
Technische Probleme erkennen.
Eine geeignete Bearbeitungskette auswählen.
EQ, Dynamikbearbeitung, gegebenenfalls Sättigung und Limiting sinnvoll einsetzen.
Lautheit und True Peak kontrollieren.
Das Ergebnis mit dem Ausgangsmix vergleichen.
Eine exportierbare Version erstellen.
Die vorgenommenen Änderungen dokumentieren.

Die Bearbeitung soll nicht automatisch jedes Problem mit einem EQ lösen.

Übermäßige Kompression, unnötige Lautheit und hörbare Verzerrungen sind zu vermeiden.

Zielwerte sollen vom Veröffentlichungszweck, Genre, Ausgangsmaterial und gegebenenfalls den Anforderungen des Zielmediums abhängen.

Garantien für absolute Verzerrungsfreiheit, universelle Streaming-Optimalität oder professionelle Release-Qualität darfst du nicht versprechen.

Biete eine schnelle Automatik und einen fortgeschrittenen Modus mit manueller Kontrolle an.

8. Eigene Plugins und Plugin-Intelligenz

Das System soll mich bei der Auswahl, Integration und gegebenenfalls Entwicklung von Audio-Plugins unterstützen.

8.1 Plugin-Recherche

Wenn ich ein bestimmtes klangliches Ergebnis erzielen möchte, soll das System prüfen, ob es am sinnvollsten ist:

Ein vorhandenes Ableton-Gerät zu verwenden.
Ein möglichst kostengünstiges oder kostenloses Plugin zu nutzen.
Eine vorhandene Plugin-Kette zu kombinieren.
Einen eigenen DSP-Prozess zu implementieren.
Ein eigenes Plugin zu entwickeln.

Vergleiche die Alternativen hinsichtlich Klangqualität, Funktionsumfang, Performance, Bedienbarkeit, Lizenz, Wartung und Entwicklungsaufwand.

8.2 Plugin-Wissen

Erstelle eine Wissensbasis über relevante Plugins und ihre Parameter.

Nutze offizielle Dokumentationen, überprüfbare Quellen und verfügbare Plugin-Metadaten.

Unterscheide zwischen nachgewiesenem Wissen über ein Plugin und einer aus dem Signalfluss abgeleiteten Vermutung.

Berücksichtige, dass ein Plugin nicht automatisch selbstständig gelernt oder ausgelesen werden kann. Wenn keine geeignete API oder Dokumentation verfügbar ist, verwende eine alternative, klar gekennzeichnete Methode.

8.3 Eigene Plugins

Entwickle bei Bedarf eigene Audio-Tools, die meinen Signature Sound unterstützen.

Mögliche Beispiele sind:

Charaktervolle Drum- und Bass-Prozessoren.
Spezielle Filter und Sättigungsprozessoren.
Kreative Modulations- und Übergangseffekt-Generatoren.
Groove- und Sequencing-Werkzeuge.
Kontextbezogene Analyse- und Mixing-Assistenten.

Prüfe vor jeder Eigenentwicklung, ob eine bestehende Lösung geeigneter wäre.

Eigene Plugins sollen modular, performant, wartbar und möglichst mit einer passenden Plugin-Schnittstelle für Ableton Live verfügbar sein.

9. Auto-Pilot und Produktionsworkflow

Der Autopilot soll einen strukturierten, adaptiven Produktionsprozess anbieten.

Er soll mich durch die Entstehung eines Tracks führen, ohne kreative Freiheit einzuschränken.

Ein möglicher Ablauf:

Stil, Referenzen und kreative Richtung definieren.
BPM, Groove und grundlegende musikalische Parameter festlegen.
Kick und Low-End entwickeln.
Grundlegendes Drum- und Percussion-Gerüst erstellen.
Bassline und rhythmische Beziehungen ausarbeiten.
Charakteristische Haupt- und Nebenelemente entwickeln.
Atmosphären, Texturen und Übergänge ergänzen.
Arrangement und Energieverlauf aufbauen.
Sounddesign und Automationen verfeinern.
Mixing-Analyse und Korrekturen durchführen.
Mastering und technische Exportkontrolle durchführen.

Dieser Ablauf ist eine Ausgangsbasis und keine starre Vorschrift.

Der Agent soll erkennen, wann ein anderer Einstieg musikalisch sinnvoller ist.

Ich möchte den Produktionsprozess jederzeit über natürliche Sprache steuern können, beispielsweise:

„Überspringe die weitere Drum-Arbeit und entwickle eine ungewöhnliche Acid-Line.“

„Gehe zurück zur Kick und erstelle drei Alternativen.“

„Analysiere den aktuellen Track und erkläre die drei wichtigsten Verbesserungen.“

„Übernimm die Arrangement-Entscheidungen selbst, aber frage mich vor Änderungen an bestehenden Samples.“

Der Autopilot soll seinen aktuellen Zustand, das nächste sinnvolle Ziel und offene Entscheidungen anzeigen.

Er soll Ergebnisse prüfen, statt lediglich Aufgaben auszuführen und ungeprüft als abgeschlossen zu markieren.

10. Mentor und musikalischer Tutor

Der Mentor ist ein zentraler Bestandteil des Produkts.

Er soll ein fundiertes Verständnis für Musiktheorie, elektronische Musikproduktion, Sounddesign, Mixing und Arrangement besitzen.

Sein Schwerpunkt liegt auf Techno, Trance und deren Subgenres.

10.1 Erklärungen

Wenn ich ein Problem beschreibe oder eine Änderung anfordere, soll der Mentor bei Bedarf erklären:

Was im Track aktuell passiert.
Welches musikalische oder technische Problem vorliegt.
Welche Lösungsmöglichkeiten existieren.
Warum eine bestimmte Lösung sinnvoll sein könnte.
Welche klanglichen Nebenwirkungen zu erwarten sind.
Wie ich die betreffende Technik selbst anwenden und verstehen kann.

Die Erklärungen sollen an meinem aktuellen Projekt orientiert sein und nicht aus allgemeinen Lehrbuchtexten bestehen.

10.2 Stem- und Audioanalyse

Der Mentor soll hochgeladene Audiodateien und verfügbare Stems möglichst präzise analysieren.

Untersuche beispielsweise:

Rhythmus und Groove.
Tempo und gegebenenfalls Taktart.
Tonalität und harmonische Struktur.
Instrumentierung und Klangcharakter.
Frequenzverteilung.
Dynamik und Transienten.
Räumlichkeit und Effektcharakter.
Arrangement und musikalische Funktion.

Kennzeichne unsichere Schätzungen und unterscheide zwischen direkter Messung, automatischer Klassifikation und subjektiver Interpretation.

10.3 Langfristige Lernunterstützung

Das System soll meine Entscheidungen und freigegebenen Präferenzen berücksichtigen, um mit der Zeit bessere Empfehlungen zu geben.

Es soll wiederkehrende klangliche Vorlieben erkennen und daraus ein persönliches Profil entwickeln.

Dieses Profil soll einstellbar, überprüfbar und zurücksetzbar sein.

Ziel ist es, meine Fähigkeiten und meinen Signature Sound zu fördern, nicht meine Entscheidungen durch einen undurchsichtigen Algorithmus zu ersetzen.

11. Benutzeroberfläche und Interaktion

Die Oberfläche soll sich optisch und funktional an einer professionellen Audio-Workstation orientieren und mit Ableton Live harmonieren.

Prioritäten:

Kompaktes, aufgeräumtes Layout.
Dunkles Farbschema und klare visuelle Hierarchie.
Direkter Chat für natürliche Sprache.
Kontextbezogene Aktionen.
Schneller Zugriff auf Sample-Generierung und Arrangement.
Visuelle Darstellung von Track-Struktur und Energieverlauf.
Übersichtliche Regler für häufige Sounddesign-Parameter.
Sample-Vorschau und Variantenvergleich.
Sichtbarer Status des Autopiloten.
Klare Anzeige von Warnungen, Änderungen und offenen Freigaben.
Undo und Wiederherstellung, wo technisch möglich.

Die Oberfläche soll den Produktionsprozess unterstützen, ohne unnötig Aufmerksamkeit vom Musikmachen abzuziehen.

Gestalte die UI modular, damit fortgeschrittene Funktionen später ergänzt werden können, ohne die Grundbedienung zu überladen.

12. Technische Architektur und Qualitätsanforderungen

Entwickle eine modulare Architektur mit klar getrennten Verantwortlichkeiten.

Untersuche unter anderem folgende Komponenten:

Desktop- und UI-Schicht.
Ableton-Integrationsschicht.
Agenten- und Orchestrierungsschicht.
Claude-API-Anbindung.
Audioanalyse und DSP.
Sample-Generierung.
MIDI- und Arrangement-Engine.
Plugin-System.
Projekt- und Metadatenverwaltung.
Lokale Dateiverwaltung.
Test- und Logging-System.

Wähle Technologien erst nach einem nachvollziehbaren Vergleich aus.

Berücksichtige Betriebssystem, Latenz, Stabilität, Ressourcenverbrauch, Wartbarkeit, Lizenzbedingungen und Kosten.

Prüfe insbesondere, welche Aufgaben lokal ausgeführt werden können und welche eine externe API oder ein zusätzliches Modell benötigen.

Audio-Generierung, Echtzeit-Audioverarbeitung und Agentenlogik sollen nicht unnötig miteinander gekoppelt werden.

Echtzeitkritische Audioprozesse dürfen nicht von unvorhersehbaren Netzwerkantworten oder blockierenden KI-Aufrufen abhängen.

Berücksichtige sichere Speicherung von API-Schlüsseln, Datenschutz, Berechtigungen, Fehlerbehandlung und Schutz vor unbeabsichtigten Projektänderungen.

13. Entwicklungsstrategie

Entwickle das System schrittweise.

Beginne nicht damit, alle Funktionen gleichzeitig umzusetzen.

Phase 1: Technische Machbarkeit
Prüfe die relevanten Ableton-Schnittstellen.
Vergleiche mögliche Integrationsarchitekturen.
Identifiziere technische Risiken und Abhängigkeiten.
Definiere einen realistischen MVP.
Lege eine überprüfbare Architekturentscheidung vor.
Phase 2: Funktionierender MVP

Baue zunächst einen kleinen, tatsächlich nutzbaren Prototyp.

Der MVP soll nach Möglichkeit Folgendes ermöglichen:

Eine kompakte, bedienbare Oberfläche.
Eine funktionierende Claude-Anbindung.
Einen zuverlässigen Kommunikationsweg zu Ableton.
Einen Chat mit Zugriff auf ausgewählten Projektkontext.
Generierung oder Bearbeitung mindestens eines Sample-Typs.
Lokale Speicherung und Import von Samples.
Eine einfache, nachvollziehbare Automatisierungsaktion.
Logging, Fehlerbehandlung und Wiederherstellung, wo möglich.

Die konkrete Auswahl der ersten Funktionen soll von der technischen Machbarkeit und dem höchsten praktischen Nutzen abhängen.

Phase 3: Produktionsfunktionen

Erweitere das System schrittweise um:

Mehrere Sample-Kategorien.
MIDI- und Arrangement-Generierung.
Referenzanalyse.
Mixing-Assistenz.
Sounddesign- und Plugin-Steuerung.
Autopilot.
Erweiterte UI.
Persönliches Klangprofil.
Phase 4: Qualitätssicherung

Teste die Integration mit realen Ableton-Projekten.

Prüfe Stabilität, Performance, Wiederherstellbarkeit, Audioqualität, Dateiverwaltung und Verhalten bei Fehlern.

Dokumentiere bekannte Einschränkungen und offene Probleme.

14. Arbeitsweise bei der Zusammenarbeit

Arbeite in klar abgegrenzten Schritten.

Bevor du umfangreichen Code schreibst, sollst du:

Die Anforderungen strukturieren.
Technische Annahmen identifizieren.
Offene Entscheidungen auflisten.
Die wichtigsten Risiken bewerten.
Geeignete technische Lösungswege recherchieren.
Eine begründete Empfehlung abgeben.
Einen umsetzbaren Entwicklungsplan definieren.

Verwende aktuelle und möglichst offizielle technische Dokumentationen, wenn die Machbarkeit von APIs, Ableton-Schnittstellen, Plugins oder Frameworks davon abhängt.

Verifiziere insbesondere Versionsabhängigkeiten und behaupte keine Funktionen, die eine Schnittstelle nicht tatsächlich bereitstellt.

Wenn wichtige Informationen fehlen, stelle gezielte Rückfragen. Stelle nicht unnötig viele Fragen gleichzeitig. Wo eine sichere Annahme ausreicht, dokumentiere sie und fahre fort.

Bei der Implementierung:

Erstelle vollständige, nachvollziehbare Dateien.
Erkläre, wo jede Datei hingehört.
Gib konkrete Installations- und Startanweisungen.
Beschreibe erforderliche Abhängigkeiten.
Ergänze geeignete Tests.
Prüfe Schnittstellen zwischen den Modulen.
Dokumentiere bekannte Einschränkungen.
Erfinde keine Testergebnisse.
Vermeide unnötige Abstraktionen und vorzeitige Optimierung.

Wenn du Code änderst, berücksichtige die bestehenden Abhängigkeiten und vermeide es, bereits funktionierende Komponenten ohne Grund neu zu schreiben.

15. Definition of Done

Eine Funktion gilt erst dann als fertig, wenn:

Die Implementierung vorhanden ist.
Ihre Abhängigkeiten dokumentiert sind.
Die vorgesehenen Tests durchgeführt wurden.
Fehlerfälle berücksichtigt wurden.
Das Verhalten mit der Spezifikation übereinstimmt.
Bekannte Einschränkungen dokumentiert sind.
Der praktische Nutzen nachvollziehbar überprüft werden kann.

Unterscheide klar zwischen einem visuellen Mock-up, einem funktionsfähigen Prototyp und einer produktionsreifen Implementierung.

16. Dein erster Auftrag

Beginne noch nicht mit der vollständigen Implementierung.

Erstelle zunächst eine fundierte technische und produktstrategische Analyse.

Liefere mir in dieser Reihenfolge:

Eine präzise Zusammenfassung des Produkts und seines zentralen Nutzens.
Eine priorisierte Anforderungsliste mit MVP, späteren Funktionen und optionalen Erweiterungen.
Eine technische Machbarkeitsanalyse für die Integration in Ableton Live.
Einen Vergleich der geeigneten Integrationsarchitekturen.
Eine Empfehlung für den konkreten Technologie-Stack.
Eine modulare Systemarchitektur mit Datenflüssen und Verantwortlichkeiten.
Einen Plan für Sample-Generierung, Audioanalyse, MIDI, Arrangement und Mixing.
Eine Strategie für Claude, externe Modelle und lokale Audioverarbeitung.
Eine Einschätzung zu Entwicklungsaufwand, laufenden Kosten, Risiken und Lizenzfragen.
Einen konkreten Umsetzungsplan mit überprüfbaren Meilensteinen.
Eine Liste der wichtigsten offenen Fragen, deren Beantwortung die Architektur wesentlich beeinflussen würde.

Nutze aktuelle Quellen für zeitabhängige technische Aussagen und kennzeichne Annahmen ausdrücklich.

Priorisiere eine Architektur, mit der ich schnell ein funktionierendes System entwickeln und anschließend kontrolliert erweitern kann.

Mein übergeordnetes Ziel ist nicht, möglichst viele KI-Funktionen zu sammeln. Ich möchte einen zuverlässigen, musikalisch intelligenten und kreativen Produktionspartner entwickeln, der mir hilft, eigenständige Tracks auf professionellem Niveau zu produzieren und meinen persönlichen Signature Sound konsequent weiterzuentwickeln.