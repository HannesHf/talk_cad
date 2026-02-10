import os
import re
import base64
import uuid
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from dotenv import load_dotenv
from build123d import * # Importiert alle CAD Funktionen in den globalen Scope

# 1. Config laden
load_dotenv()

# API Key Check & Validation
api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key or "dein-api-key" in api_key:
    print("\n❌ FEHLER: OPENROUTER_API_KEY fehlt oder ist noch der Platzhalter!")
    print("👉 Bitte öffne die '.env' Datei und trage deinen echten Key von openrouter.ai ein.\n")

app = FastAPI()

# --- CORS SETUP ---
# Erlaubt Zugriff von separaten Frontends (z.B. VS Code Live Server, React, Vue)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Frontend statisch ausliefern
app.mount("/view", StaticFiles(directory="static", html=True), name="static")

@app.get("/")
async def root():
    return RedirectResponse(url="/view/index.html")

# --- LANGCHAIN SETUP ---
# Agent 1 & 3 (Planer & QA)
llm_gemma = ChatOpenAI(
    model="google/gemini-2.0-flash-001", 
    base_url="https://openrouter.ai/api/v1",
    api_key=api_key,
    temperature=0.1
)

# Agent 2 (Coder)
llm_coder = ChatOpenAI(
    model="anthropic/claude-3.5-sonnet",
    base_url="https://openrouter.ai/api/v1",
    api_key=api_key,
    temperature=0.1
)

class PromptRequest(BaseModel):
    prompt: str
    base_code: str | None = None

# --- AGENT PROMPTS ---

PLANNER_PROMPT = """
Du bist der **CAD-Architekt (Agent 1)**. Deine Aufgabe ist die Vorauswertung der Nutzeranfrage.
1. Analysiere den Wunsch des Nutzers.
2. Identifiziere die notwendigen geometrischen Komponenten (z.B. Basis, Löcher, Halterungen).
3. Definiere sinnvolle Standard-Maße, falls keine angegeben sind.
4. Erstelle einen strukturierten Bauplan für den Programmierer.

Gib NUR den Plan zurück, keinen Python-Code.
"""

CODER_PROMPT = """
Du bist der **Coding-Agent (Agent 2)** in diesem Repository.
Deine Aufgabe: Schreibe Python-Code mit der Bibliothek `build123d`, um den Plan des Architekten umzusetzen.

**SYSTEM-ANFORDERUNGEN (WICHTIG):**
Dieses Repository rendert 3D-Modelle im Browser. Damit das funktioniert, musst du dich an folgende Schnittstelle halten:
1. **Output-Variable**: Das finale 3D-Objekt MUSS am Ende der Variable `part` zugewiesen werden (z.B. `part = my_obj.part`). Ohne dies kann das System nichts anzeigen.
2. **Environment**: `build123d` ist bereits importiert (`from build123d import *`). Mache KEINE Imports.
3. **Syntax & Anti-Patterns**: 
   - Nutze `with BuildPart() as p:` für komplexe Teile.
   - **KEIN** `p.add(...)`. Objekte innerhalb des `with`-Blocks werden automatisch hinzugefügt. Nutze `add(obj)` (global im Block) nur für externe Objekte.
   - **KEIN** `RoundedBox`. Nutze `Box` und anschließend `fillet(edges, radius)` oder extrudiere ein `RoundedRectangle`.
   - Primitive (`Box`, `Cylinder`) haben **KEINEN** `direction` Parameter. Nutze `Rotation(...)` oder `Locations(...)`.

**BUILD123D CHEAT SHEET (NUTZE DIESE SIGNATUREN):**
- `Box(length, width, height)` (KEIN `depth`, KEIN `fillet` im Konstruktor)
- `Cylinder(radius, height)` (KEIN `direction`)
- `Sphere(radius)`
- `with Locations((x, y, z)):` oder `with Locations([(x,y,z), ...]):` (NUR Listen von Tupeln oder einzelne Tupel! Keine Generatoren oder Shapes übergeben.)
- `Location((x,y,z))` (Singular) für direkte Transformationen.
- `fillet(objects, radius)` -> z.B. `fillet(part.edges(), radius=2)`
- `chamfer(objects, length)`
- `extrude(sketch, amount)`

Antworte NUR mit dem Python-Codeblock.
"""

QA_PROMPT = """
Du bist der **Quality Assurance Agent (Agent 3)**.
Prüfe den generierten Code und das Ergebnis.
Kriterien:
1. Wurde die Variable `part` korrekt definiert?
2. Wurden die Anforderungen des Nutzers und des Plans erfüllt?
3. Ist der Code syntaktisch plausibel für `build123d` (keine erfundenen Klassen wie `RoundedBox`)?
4. **Zusammenhang**: Prüfe kritisch, ob alle Teile miteinander verbunden sind. Schweben Teile (z.B. Beine) in der Luft oder haben sie Kontakt zum Hauptkörper?

Antworte mit "PASS", wenn das Modell an den Nutzer gegeben werden kann.
Falls Fehler vorliegen, antworte mit "FAIL: <Kurze Erklärung des Fehlers>", damit der Coder es korrigieren kann.
"""

@app.post("/generate")
async def generate_model(request: PromptRequest):
    print(f"🤖 User Prompt: {request.prompt}")

    # --- SCHRITT 1: PLANNER (Vorauswertung) ---
    print("🤔 Agent 1: Erstelle Bauplan...")
    planner_input = f"Nutzer-Wunsch: {request.prompt}"
    if request.base_code:
        planner_input += f"\nBasierend auf existierendem Code:\n{request.base_code}"
    
    plan_response = await llm_gemma.ainvoke([
        SystemMessage(content=PLANNER_PROMPT),
        HumanMessage(content=planner_input)
    ])
    plan = plan_response.content
    print(f"📋 Plan:\n{plan}\n")

    # --- SCHRITT 2: CODER (Generierung) ---
    # Wir bauen den Kontext für den Coder auf
    coder_messages = [SystemMessage(content=CODER_PROMPT)]
    
    coder_input = f"Nutzer-Anfrage: {request.prompt}\n\nTechnischer Bauplan:\n{plan}"
    if request.base_code:
        coder_input += f"\n\nModifiziere diesen existierenden Code:\n```python\n{request.base_code}\n```"
    
    coder_messages.append(HumanMessage(content=coder_input))

    # Retry Loop Configuration
    MAX_RETRIES = 10
    clean_code = ""
    generated_part = None
    error_log = []
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            print(f" Agent 2: Generiere Code (Versuch {attempt + 1})...")
            
            # Generierung
            response = await llm_coder.ainvoke(coder_messages)
            ai_response = response.content
            
            # Code Cleaning
            match = re.search(r"```python(.*?)```", ai_response, re.DOTALL)
            if match:
                clean_code = match.group(1).strip()
            else:
                clean_code = ai_response.replace("```python", "").replace("```", "").strip()

            # Execution Sandbox
            print("⚙️  System: Führe Code aus...")
            exec_globals = globals().copy()
            for unsafe in ['os', 'client', 'app', 'load_dotenv']:
                exec_globals.pop(unsafe, None)
            exec_locals = {}

            exec(clean_code, exec_globals, exec_locals)
            
            # Technische Validierung (Variable 'part')
            if "part" not in exec_locals:
                raise ValueError("Variable 'part' fehlt. Der Code muss mit 'part = ...' enden.")
            
            generated_part = exec_locals["part"]
            if hasattr(generated_part, "part"): generated_part = generated_part.part # Unwrap Builder

            # --- SCHRITT 3: QA AGENT (Vorbewertung) ---
            print("🧐 Agent 3: Quality Check...")
            qa_messages = [
                SystemMessage(content=QA_PROMPT),
                HumanMessage(content=f"Nutzer-Anfrage: {request.prompt}\n\nGenerierter Code:\n```python\n{clean_code}\n```")
            ]
            qa_response = await llm_gemma.ainvoke(qa_messages)
            qa_verdict = qa_response.content
            
            if "FAIL" in qa_verdict:
                print(f"❌ QA abgelehnt: {qa_verdict}")
                raise ValueError(f"QA Agent Feedback: {qa_verdict}")
            
            print("✅ QA: PASS")
            
            # Validierung der Geometrie-Typen (Compound/Solid check)
            if isinstance(generated_part, (list, tuple)):
                valid_parts = []
                for obj in generated_part:
                    if obj is None: continue
                    if hasattr(obj, "part"): obj = obj.part
                    elif hasattr(obj, "sketch"): continue 
                    elif hasattr(obj, "line"): continue 
                    if isinstance(obj, (Sketch, Curve)): continue 
                    valid_parts.append(obj)
                if not valid_parts: raise ValueError("Keine gültigen 3D-Objekte.")
                generated_part = Compound(children=valid_parts)

            if isinstance(generated_part, (Sketch, Curve)):
                 raise ValueError("Ergebnis ist 2D. Bitte extrudieren.")
            
            # Success!
            break

        except Exception as e:
            print(f"⚠️ Fehler/Kritik in Versuch {attempt + 1}: {e}")
            error_log.append(f"Versuch {attempt + 1}: {str(e)}")
            
            if attempt < MAX_RETRIES:
                tb = traceback.format_exc()
                error_msg = f"Fehler: {str(e)}\n\nTraceback:\n{tb}"
                
                is_repeated_error = any(str(e) in log_entry for log_entry in error_log[:-1])
                
                hint = ""
                if "'wrapped'" in error_msg:
                    hint = "\nHINT: Fehler 'has no attribute wrapped' bedeutet meist, dass du 'Locations' (Plural) oder ein 'tuple' anstelle eines Shapes verwendest. Nutze 'Locations' NUR im 'with'-Statement. Nutze Listen [] für mehrere Objekte."
                if "Locations doesn't accept type" in error_msg:
                    hint = "\nHINT: 'Locations' akzeptiert nur (x,y,z) Tupel oder Listen davon. Keine Shapes, keine Generatoren! Nutze [ (x,y,z) for i in range(...) ] um Listen zu bauen."
                
                if is_repeated_error:
                    hint += "\n\n🛑 KRITISCH: Du hast diesen Fehler bereits gemacht! Deine vorherige Lösung hat NICHT funktioniert. Versuche einen RADIKAL ANDEREN Ansatz (z.B. Koordinaten manuell berechnen statt relative Positionierung)."

                coder_messages.append(AIMessage(content=ai_response))
                coder_messages.append(HumanMessage(content=f"⚠️ KORREKTUR NÖTIG:\n{error_msg}{hint}\n\nBitte korrigiere den Code. Halte dich STRIKT an das Cheat Sheet."))
            else:
                history_str = "\n".join(error_log)
                raise HTTPException(status_code=400, detail=f"Generierung fehlgeschlagen:\n{history_str}")

    # 3. Analyse & Export
    try:
        volume = 0
        if hasattr(generated_part, "volume"):
            volume = generated_part.volume
        
        warning = None
        if volume < 10:
            warning = "⚠️ Warnung: Das Objekt scheint leer oder extrem klein zu sein."

        # Use unique filename to avoid concurrency issues
        temp_filename = f"temp_{uuid.uuid4()}.stl"

        # Export zu STL (Binary -> Base64)
        export_stl(generated_part, temp_filename)
        
        with open(temp_filename, "rb") as f:
            stl_content = base64.b64encode(f.read()).decode('utf-8')

        return {
            "status": "success",
            "stl_data": stl_content,
            "code": clean_code,
            "analysis": {
                "volume": round(volume, 2),
                "warning": warning,
                "plan": plan,
                "errors": error_log
            }
        }
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Export Error: {str(e)}")
    finally:
        # Cleanup temp file
        if 'temp_filename' in locals() and os.path.exists(temp_filename):
            os.remove(temp_filename)

if __name__ == "__main__": 
    import uvicorn 
    uvicorn.run(app, host="0.0.0.0", port=8000)