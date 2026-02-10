import os
import re
import base64
import uuid
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from openai import AsyncOpenAI
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

# Frontend statisch ausliefern
app.mount("/view", StaticFiles(directory="static", html=True), name="static")

@app.get("/")
async def root():
    return RedirectResponse(url="/view/index.html")

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=api_key,
)

class PromptRequest(BaseModel):
    prompt: str
    base_code: str | None = None

# UPDATE: Verbesserter System Prompt mit striktem Template
SYSTEM_PROMPT = """
Du bist ein erfahrener CAD-Ingenieur und Python-Experte für die Bibliothek 'build123d'.
Deine Aufgabe: Erstelle robusten, parametrischen Code für das gewünschte Bauteil.

ANFORDERUNGEN:
1. **Parametrik**: Definiere wichtige Maße als Variablen am Anfang (z.B. `length = 100`). Nutze diese Variablen für Abhängigkeiten (z.B. `hole_pos = length / 2`).
2. **Konstruktion**: Denke wie ein Ingenieur. Berücksichtige, wie Teile zusammenpassen (Fugen, Passungen, Stabilität, Montage).
3. **Logik**: Nutze Loops, Bedingungen (if/else) und mathematische Operationen für intelligente Modelle.
4. **Syntax**: 
   - Importiere NICHTS (alles ist da).
   - Primitive (Box, Cylinder) haben KEINEN `direction` Parameter -> Nutze `Rotation()` oder `Locations()`.
   - `BuildPart` ist ein Builder. Das geometrische Objekt ist `.part`.
   - Das finale Objekt MUSS in einer Variable namens `part` gespeichert werden.

TEMPLATE:
```python
# Parameter
width = 100
height = 20

with BuildPart() as p:
    Box(width, width, height)
    # Intelligente Features
    if width > 50:
        with Locations((0, 0, height/2)):
            Cylinder(radius=5, height=10, mode=Mode.SUBTRACT)
    
# Finales Objekt
part = p.part
```
# WICHTIG: Zuweisung an 'part'
part = p.part
Antworte NUR mit dem Python-Code. Keine Erklärungen. """

@app.post("/generate")
async def generate_model(request: PromptRequest):
    print(f"🤖 User Prompt: {request.prompt}")

    # Message History Setup
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    if request.base_code:
        user_content = f"""
Hier ist der existierende Python-Code einer build123d Konstruktion:
```python
{request.base_code}
```
Deine Aufgabe: Modifiziere diesen Code basierend auf folgendem Wunsch: "{request.prompt}".
Gib den kompletten, lauffähigen Code zurück (nicht nur den Diff).
"""
    else:
        user_content = request.prompt
        
    messages.append({"role": "user", "content": user_content})

    # Retry Loop Configuration
    MAX_RETRIES = 2
    clean_code = ""
    generated_part = None
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            print(f"🔄 Generierung Versuch {attempt + 1}/{MAX_RETRIES + 1}...")
            
            completion = await client.chat.completions.create(
                model="deepseek/deepseek-chat", # Schnelleres Modell (V3) statt R1
                messages=messages,
                temperature=0.1
            )
            ai_response = completion.choices[0].message.content
            
            # Code Cleaning
            match = re.search(r"```python(.*?)```", ai_response, re.DOTALL)
            if match:
                clean_code = match.group(1).strip()
            else:
                clean_code = ai_response.replace("```python", "").replace("```", "").strip()

            # Execution Sandbox
            exec_globals = globals().copy()
            for unsafe in ['os', 'client', 'app', 'load_dotenv']:
                exec_globals.pop(unsafe, None)
            exec_locals = {}

            print("--- Executing AI Code ---")
            print(clean_code)
            print("-------------------------")
            
            exec(clean_code, exec_globals, exec_locals)
            
            # Validation
            if "part" not in exec_locals:
                raise ValueError("Der generierte Code hat keine Variable 'part' definiert.")
            
            generated_part = exec_locals["part"]
            
            if hasattr(generated_part, "part"):
                generated_part = generated_part.part

            if isinstance(generated_part, (list, tuple)):
                valid_parts = []
                for obj in generated_part:
                    if obj is None: continue
                    if hasattr(obj, "part"): obj = obj.part
                    elif hasattr(obj, "sketch"): continue 
                    elif hasattr(obj, "line"): continue 

                if isinstance(obj, (Sketch, Curve)): continue 
                valid_parts.append(obj)
                
                if not valid_parts:
                    raise ValueError("Keine gültigen 3D-Objekte gefunden.")
                generated_part = Compound(children=valid_parts)

            if isinstance(generated_part, (Sketch, Curve)):
                 raise ValueError("Das generierte Objekt ist 2D. Bitte extrudiere es.")
            
            # Success!
            break

        except Exception as e:
            print(f"❌ Fehler in Versuch {attempt + 1}: {e}")
            
            if attempt < MAX_RETRIES:
                # Feedback Loop
                error_msg = str(e)
                messages.append({"role": "assistant", "content": ai_response})
                messages.append({"role": "user", "content": f"⚠️ Dein Code hat einen Fehler geworfen:\n{error_msg}\n\nBitte korrigiere den Code. Denke daran: Primitive wie Cylinder/Box haben KEINEN 'direction' Parameter (nutze Rotation). Gib den korrigierten Code komplett zurück."})
            else:
                raise HTTPException(status_code=400, detail=f"Code Error nach {MAX_RETRIES} Korrekturversuchen: {str(e)}")

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
                "warning": warning
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