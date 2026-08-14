from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import edge_tts
import os
import uuid
import subprocess
from PIL import Image, ImageDraw, ImageFont

app = FastAPI()

# Конфігурація дизайну
CANVAS_W, CANVAS_H = 1080, 1920
BOX_BG = (10, 8, 20, 210)         # Напівпрозорий чорний
BOX_ACCENT = (255, 138, 61, 255)  # Помаранчевий акцент
TEXT_COLOR = (255, 255, 255, 255)
FONT_PATH = "Montserrat-VariableFont_wght.ttf" # Переконайся, що він у корені
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(BASE_DIR, "Montserrat-VariableFont_wght.ttf")
BG_PATH = os.path.join(BASE_DIR, "background.jpg")

def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), trial, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            current = trial
        else:
            if current: lines.append(current)
            current = word
    if current: lines.append(current)
    return lines

def create_text_overlay(text, output_path):
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    max_text_width = CANVAS_W - 200
    max_box_height = int(CANVAS_H * 0.6)

    # Адаптивний підбір розміру шрифту
    font_size = 50
    while font_size >= 26:
        font = ImageFont.truetype(FONT_PATH, font_size)
        lines = wrap_text(draw, text, font, max_text_width)
        line_height = int(font_size * 1.3)
        box_height = (line_height * len(lines)) + 100
        if box_height <= max_box_height:
            break
        font_size -= 4

    box_top = (CANVAS_H - box_height) // 2
    box_left, box_right = 60, CANVAS_W - 60
    
    # Малюємо плашку
    draw.rounded_rectangle([box_left, box_top, box_right, box_top + box_height], radius=30, fill=BOX_BG)
    # Акцентна смужка
    draw.rounded_rectangle([box_left, box_top + 30, box_left + 10, box_top + box_height - 30], radius=5, fill=BOX_ACCENT)

    y = box_top + 50
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (CANVAS_W - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), line, font=font, fill=TEXT_COLOR)
        y += line_height

    img.save(output_path)

@app.post("/generate-video")
async def generate_video(data: dict):
    text = data.get("text")
    uid = uuid.uuid4().hex[:8]
    
    audio_path = f"/tmp/audio_{uid}.mp3"
    overlay_path = f"/tmp/overlay_{uid}.png"
    output_video_path = f"/tmp/video_{uid}.mp4"
    bg_path = "background.jpg" # Твій фоновий файл

    # 1. TTS
    communicate = edge_tts.Communicate(text, "uk-UA-PolinaNeural")
    await communicate.save(audio_path)

    # 2. Overlay
    create_text_overlay(text, overlay_path)

    # 3. FFMPEG (Склеюємо)
    # Беремо статичний фон і накладаємо текст + звук
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", bg_path,
        "-i", overlay_path, "-i", audio_path,
        "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac",
        "-shortest", "-pix_fmt", "yuv420p", output_video_path
    ], check=True)

    return FileResponse(output_video_path, media_type="video/mp4")
