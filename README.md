# PDF Viewer mit Labels

Ein Python-GUI-Programm zum Anzeigen, Beschriften und Exportieren von PDF-Seiten.

## Features

- **PDF anzeigen** – Öffne beliebige PDF-Dateien über den Datei-Dialog.
- **Zoom** – Vergrößern/Verkleinern per Mausrad (`Strg + Mausrad`) oder Schaltflächen (`+` / `−`).
- **Verschieben** – Seiten-Inhalt mit der mittleren Maustaste oder rechten Maustaste verschieben.
- **Seitennavigation** – Pfeil-Tasten `←` / `→`, `Bild hoch` / `Bild runter`, oder die Seiten-Liste.
- **Label-Shortcuts**:
  | Taste | Label         |
  |-------|---------------|
  | `1`   | unwichtig     |
  | `2`   | wichtig       |
  | `3`   | sehr wichtig  |
  *(gleiche Taste nochmal drücken entfernt das Label)*
- **Labels speichern / laden** – Fortschritt wird als JSON-Datei gespeichert.
- **Wichtige Seiten exportieren** – Alle Seiten mit Label `wichtig` oder `sehr wichtig` werden in eine neue PDF-Datei extrahiert.

## Installation

```bash
pip install -r requirements.txt
```

## Starten

```bash
python pdf_viewer.py
```

## Abhängigkeiten

- [PyMuPDF](https://pymupdf.readthedocs.io/) ≥ 1.24
- [Pillow](https://pillow.readthedocs.io/) ≥ 10.0
- Python 3.10+, tkinter (in der Python-Standardbibliothek enthalten)
