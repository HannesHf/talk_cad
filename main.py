import os
import re
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
from build123d import * # Importiert die CAD Befehle

# 1. Config laden
load_dotenv()
app = FastAPI()

# Frontend statisch ausliefern
app.mount("/view", StaticFiles(directory="static", html=True), name="static")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

# Datenmodell für den Request
class PromptRequest(BaseModel):
    prompt: str

# SYSTEM PROMPT: Das "Gehirn", das dem LLM sagt, wie es CAD machen soll
SYSTEM_PROMPT = """
Du bist ein Experte für 'build123d' (eine Python CAD Library).
Deine Aufgabe: Generiere NUR Python-Code basierend auf dem User-Wunsch.
Regeln:
1. Importiere NICHTS (build123d ist schon geladen).
2. Erstelle das finale Objekt und nenne die Variable 'part'.
3. Nutze KEINE `show()` oder `export()` Befehle. Nur Geometrie erstellen.
4. Antworte NUR mit dem Code-Block, kein Text davor oder danach.

Beispiel:
User: "Ein Würfel 10x10x10"
Code:
with BuildPart() as part:
    Box(10, 10, 10)
"""

@app.post("/generate")
async def generate_model(request: PromptRequest):
    print(f"🤖 User will: {request.prompt}")

    # 1. AI Anfragen (Wir nutzen deepseek-coder weil günstig & gut)
    try:
        completion = client.chat.completions.create(
            model="deepseek/deepseek-coder", 
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": request.prompt}
            ]
        )
        ai_code = completion.choices[0].message.content
        
        # Code aus Markdown-Block extrahieren (```python ... ```)
        clean_code = ai_code.replace("```python", "").replace("```", "").strip()
        print(f"🐍 Generierter Code:\n{clean_code}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")

    # 2. Code Ausführen (Vorsicht: exec() ist riskant in Prod, ok für Prototyp)
    local_vars = {}
    try:
        # Wir geben dem Script Zugriff auf build123d Globals
        exec(clean_code, globals(), local_vars)
        
        if "part" not in local_vars:
            raise ValueError("Der AI-Code hat keine Variable 'part' erstellt.")
        
        generated_part = local_vars["part"]

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Code Execution Error: {str(e)}")

    # 3. Konsistenz-Check (CV-Highlight!)
    # Hier prüfen wir einfache Physik
    volume = 0
    if hasattr(generated_part, "volume"):
        volume = generated_part.volume
    
    warning = None
    if volume < 100:
        warning = "Hinweis: Das Bauteil ist sehr klein (Volumen < 100mm³)."

    # 4. Export als STL String
    exporter = export_stl(generated_part, "temp.stl") # Speichert kurz
    with open("temp.stl", "r") as f:
        stl_content = f.read()
    
    return {
        "status": "success",
        "stl_data": stl_content, # Das 3D Modell als Text
        "code": clean_code,      # Damit du siehst, was passiert ist
        "analysis": {
            "volume": round(volume, 2),
            "warning": warning
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(main, host="0.0.0.0", port=8000)