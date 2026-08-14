from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import edge_tts
import os
import uuid
import requests
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip, AudioFileClip

app = FastAPI(title="Edge TTS & Reel Video Generation Service")

# Дефолтний фон, якщо картинка з новини не передана (поклади у корінь проєкта)
DEFAULT_BACKGROUND = "background.jpg"

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Video & TTS Service is running!"}

def create_text_frame(text: str, bg_path: str, output_path: str):
    """Створює вертикальне зображення 1080x1920 з фоном та плашкою для тексту"""
    try:
        img = Image.open(bg_path).convert("RGB")
    except Exception:
        # Якщо файл фон-картинки не знайдено, робимо темно-сірий фоновий холст
        img = Image.new("RGB", (1080, 1920), color=(20, 20, 20))

    # Масштабуємо фон під вертикальний формат Reels/Shorts (1080x1920)
    img = img.resize((1080, 1920))
    draw = ImageDraw.Draw(img)

    # Напівпрозора чорна плашка по центру для читабельності тексту
    # Координати: x1, y1, x2, y2
    draw.rectangle([(80, 750), (1000, 1250)], fill=(0, 0, 0, 200))

    # Спроба завантажити стандартний системний шрифт, або дефолтний
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 55)
    except IOError:
        try:
            font = ImageFont.truetype("arial.ttf", 55)
        except IOError:
            font = ImageFont.load_default()

    # Простий алгоритм переносу слів у рядки
    margin_x = 120
    max_width = 1080 - (margin_x * 2)
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = current_line + " " + word if current_line else word
        # Визначаємо ширину тексту
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    # Малюємо рядки по центру плашки
    y_text = 820
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        x = (1080 - w) // 2  # центруємо по горизонталі
        draw.text((x, y_text), line, font=font, fill="white")
        y_text += 75

    img.save(output_path)

@app.post("/generate-video")
async def generate_video(data: dict):
    text = data.get("text")
    voice = data.get("voice", "uk-UA-OstapNeural")
    rate = data.get("rate", "+0%")
    image_url = data.get("image_url")  # Посилання на фото з новини (якщо є)

    if not text:
        raise HTTPException(status_code=400, detail="Text field is required")

    uid = uuid.uuid4().hex[:8]
    audio_path = os.path.join("/tmp", f"audio_{uid}.mp3")
    image_path = os.path.join("/tmp", f"img_{uid}.jpg")
    output_video_path = os.path.join("/tmp", f"video_{uid}.mp4")

    try:
        # 1. Генерируємо аудіо через edge-tts
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
        await communicate.save(audio_path)

        # 2. Визначаємося з фоновим зображенням
        bg_to_use = DEFAULT_BACKGROUND
        if image_url:
            try:
                response = requests.get(image_url, timeout=5)
                if response.status_code == 200:
                    with open(image_path, "wb") as f:
                        f.write(response.content)
                    bg_to_use = image_path
            except Exception:
                pass # Якщо не вдалося завантажити картинку з новини, впадемо на дефолтний фон

        if not os.path.exists(bg_to_use):
            # Якщо немає ніякого фону, створюємо чорну заглушку
            img = Image.new("RGB", (1080, 1920), color=(10, 10, 10))
            img.save(image_path)
            bg_to_use = image_path

        # 3. Створюємо кадр із текстом та фоном
        create_text_frame(text, bg_to_use, image_path)

        # 4. Завантажуємо звук і формуємо відео з однієї картинки на тривалість звуку
        audio_clip = AudioFileClip(audio_path)
        video_clip = ImageClip(image_path).with_duration(audio_clip.duration)
        
        # Встановлюємо звук для відео
        final_video = video_clip.set_audio(audio_clip)

        # 5. Рендеримо готовий MP4 файл
        final_video.write_videofile(
            output_video_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast",
            logger=None
        )

        # Закриваємо клієнти
        audio_clip.close()
        video_clip.close()
        final_video.close()

        # Прибираємо сміття з /tmp
        for p in [audio_path, image_path]:
            if os.path.exists(p) and p != image_path: # не видаляємо дефолтний фон якщо він юзається
                os.remove(p)

        return FileResponse(output_video_path, media_type="video/mp4", filename=f"news_reel_{uid}.mp4")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
