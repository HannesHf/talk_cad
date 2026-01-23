import os
import re
import base64
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
from build123d import * # Importiert alle CAD Funktionen in den globalen Scope

# 1. Config laden
load_dotenv()
app = FastAPI()

# Frontend statisch ausliefern
app.mount("/view", StaticFiles(directory="static", html=True), name="static")

@app.get("/")
async def root():
    return RedirectResponse(url="/view/index.html")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

class PromptRequest(BaseModel):
    prompt: str

# UPDATE: Verbesserter System Prompt mit striktem Template
SYSTEM_PROMPT = """
Du bist ein Python-Experte für die 3D-CAD-Bibliothek 'build123d'.
Deine Aufgabe: Wandle den User-Wunsch in validen Python-Code um.

REGELN:
1. Importiere NICHTS. (Alles von build123d ist bereits verfügbar).
2. Das finale Objekt MUSS in einer Variable namens `part` gespeichert werden.
3. Nutze KEINE `show()`, `export_stl()` oder `print()` Befehle.
4. WICHTIG: `BuildPart` (z.B. `p`) ist ein Builder, KEIN Shape. Du kannst Builder nicht direkt addieren oder subtrahieren. Nutze IMMER `.part` (z.B. `p.part`), um das geometrische Objekt zu erhalten.

TEMPLATE:
```python
with BuildPart() as p:
    Box(10, 10, 10)
    # ...
    
# Immer .part abrufen!
part = p.part
```
# WICHTIG: Zuweisung an 'part'
part = p.part
Antworte NUR mit dem Python-Code. Keine Erklärungen. """

@app.post("/generate")
async def generate_model(request: PromptRequest):
    print(f"🤖 User Prompt: {request.prompt}")

    # 1. AI Anfrage
    try:
        completion = client.chat.completions.create(
            model="deepseek/deepseek-r1", 
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": request.prompt}
            ],
            temperature=0.1 # Geringere Kreativität für stabileren Code
        )
        ai_response = completion.choices[0].message.content
        
        # Code Cleaning: Extrahiert den Python-Block (wichtig für R1, das oft <think> Tags nutzt)
        match = re.search(r"```python(.*?)```", ai_response, re.DOTALL)
        if match:
            clean_code = match.group(1).strip()
        else:
            clean_code = ai_response.replace("```python", "").replace("```", "").strip()
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Connection Error: {str(e)}")

    # 2. Code Ausführen (Sandbox-ish)
    # Wir kopieren die aktuellen Globals (damit build123d Befehle verfügbar sind)
    exec_globals = globals().copy()
    exec_locals = {}

    try:
        print("--- Executing AI Code ---")
        print(clean_code)
        print("-------------------------")
        
        exec(clean_code, exec_globals, exec_locals)
        
        # Prüfung: Hat der Code 'part' erstellt?
        if "part" not in exec_locals:
            raise ValueError("Der generierte Code hat keine Variable 'part' definiert.")
        
        generated_part = exec_locals["part"]
        
        # Sicherheitsnetz: Falls User versehentlich den Builder statt das Part zurückgibt
        if hasattr(generated_part, "part"):
            generated_part = generated_part.part

    except Exception as e:
        print(f"❌ Execution Error: {e}")
        raise HTTPException(status_code=400, detail=f"Code Error: {str(e)}")

    # 3. Analyse & Export
    try:
        volume = 0
        if hasattr(generated_part, "volume"):
            volume = generated_part.volume
        
        warning = None
        if volume < 10:
            warning = "⚠️ Warnung: Das Objekt scheint leer oder extrem klein zu sein."

        # Export zu STL (Binary -> Base64)
        export_stl(generated_part, "temp.stl")
        
        with open("temp.stl", "rb") as f:
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
        raise HTTPException(status_code=500, detail=f"Export Error: {str(e)}")

if __name__ == "__main__": 
    import uvicorn 
    uvicorn.run(app, host="0.0.0.0", port=8000)