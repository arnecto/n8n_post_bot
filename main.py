from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import edge_tts
import os
import uuid

app = FastAPI(title="Edge TTS API Service")

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Edge TTS Service is running!"}

@app.post("/tts")
async def generate_tts(data: dict):
    text = data.get("text")
    voice = data.get("voice", "uk-UA-OstapNeural")  # Голос за замовчуванням (або uk-UA-PolinaNeural)
    rate = data.get("rate", "+0%")

    if not text:
        raise HTTPException(status_code=400, detail="Text field is required")

    filename = f"audio_{uuid.uuid4().hex[:8]}.mp3"
    filepath = os.path.join("/tmp", filename)

    try:
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
        await communicate.save(filepath)
        return FileResponse(filepath, media_type="audio/mpeg", filename=filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
