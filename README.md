# TalkCAD

TalkCAD ist ein generativer CAD-Copilot, der es ermöglicht, 3D-Modelle für CAD-Anwendungen in Echtzeit durch natürliche Sprache zu erstellen.

<img width="2336" height="1198" alt="Image" src="https://github.com/user-attachments/assets/8e8b1356-779f-4f89-98f3-fe167bc4c948" />

Das Projekt nutzt **DeepSeek R1** (via OpenRouter, andere Modelle möglich) zur Generierung von Python-Code für die **build123d** CAD-Bibliothek. Das Ergebnis wird sofort als 3D-Modell im Browser visualisiert.

## 🚀 Features

- **Text-zu-CAD**: Beschreibe Bauteile in natürlicher Sprache (z.B. "Eine Platte 50x50x5 mit einem Loch D=10").
- **Live 3D-Preview**: Integrierter Three.js Viewer zur sofortigen Kontrolle.
- **Code-Generierung**: Der erzeugte Python-Code wird im Hintergrund ausgeführt.
- **STL-Visualisierung**: Das generierte Modell wird direkt im Browser gerendert.

## 🛠️ Technologie-Stack

- **Backend**: Python, FastAPI, Uvicorn
- **CAD-Kernel**: build123d
- **AI/LLM**: DeepSeek R1 (via OpenRouter API)
- **Frontend**: HTML5, Three.js (ES Modules)

## 📦 Installation & Start

### Voraussetzungen
- Python 3.10+
- Ein API-Key von [OpenRouter](https://openrouter.ai/)

### Setup mit `uv` (Empfohlen)

1. **API-Key setzen**:
   Erstelle eine `.env` Datei im Hauptverzeichnis:
   ```env
   OPENROUTER_API_KEY=sk-or-v1-dein-api-key...
   ```

2. **Starten**:
   `uv` kümmert sich automatisch um die virtuelle Umgebung und Abhängigkeiten.
   ```powershell
   uv run main.py
   ```

### Setup mit Standard-Pip

1. **Installation**:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate
   pip install -r requirements.txt
   ```

2. **Starten**:
   ```powershell
   python main.py
   ```

## 🖥️ Nutzung

1. Öffne den Browser unter **http://localhost:8000**.
2. Gib im Textfeld deinen Wunsch ein (z.B. "Ein Würfel 20mm Kantenlänge").
3. Klicke auf **Modell generieren**.

## 🔮 Roadmap

- Baugruppen-Support (Assemblies).
- Iterative Anpassungen (Chat-Modus).
- Export-Funktionen (STEP, STL Download).
