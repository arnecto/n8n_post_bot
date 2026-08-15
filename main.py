from fastapi import FastAPI, BackgroundTasks, HTTPException
import edge_tts
import os
import uuid
import subprocess
import aiohttp
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
load_dotenv()

# Ініціалізація FastAPI додатку
app = FastAPI()

# Безпечне отримання секретних даних із змінних середовища Render
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID", "1792535510")

# Шляхи до файлів ресурсів (шрифти, фон) відносно поточної директорії
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(BASE_DIR, "Montserrat-VariableFont_wght.ttf")
BG_PATH = os.path.join(BASE_DIR, "background.jpg")

# Налаштування роздільної здатності відео (Vertical format 9:16) та кольорів для тексту
CANVAS_W, CANVAS_H = 1080, 1920
BOX_BG = (10, 8, 20, 210)       # Напівпрозорий темний фон для блоку тексту
BOX_ACCENT = (255, 138, 61, 255) # Колір декоративної лінії зліва
TEXT_COLOR = (255, 255, 255, 255)# Білий колір самого тексту

# Перевірка життєздатності сервісу (Health check)
@app.get("/")
async def root():
    return {"status": "ok"}

# Універсальна асинхронна функція для виконання запитів до Telegram Bot API
async def telegram_api(method: str, payload: dict):
    if not TELEGRAM_BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as response:
                res_json = await response.json()
                return res_json.get("result")
        except Exception as e:
            print(f"Telegram API error ({method}): {e}")
            return None

# Відправка початкового повідомлення про початок процесу генерації
async def send_progress_message(text: str):
    payload = {
        "chat_id": CHAT_ID,
        "text": text
    }
    result = await telegram_api("sendMessage", payload)
    return result.get("message_id") if result else None

# Редагування існуючого повідомлення для оновлення прогрес-бару
async def edit_progress_message(message_id: int, text: str):
    if not message_id:
        return
    payload = {
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "text": text
    }
    await telegram_api("editMessageText", payload)

# Генерація текстової шкали прогрес-бару (наприклад: [████░░░░░░] 40%)
def make_progress_bar(percent: int) -> str:
    blocks = int(percent / 10)
    bar = "█" * blocks + "░" * (10 - blocks)
    return f"[{bar}] {percent}%"

# Розбиття довгого тексту на окремі рядки, щоб вони вміщувалися по ширині екрана
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

# Створення графічного зображення з текстом (оверлей поверх фону) через бібліотеку Pillow
def create_text_overlay(text, output_path):
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    max_text_width = CANVAS_W - 200
    max_box_height = int(CANVAS_H * 0.6)

    # Автоматичний підбір розміру шрифту, щоб текст гарно вліз у блок
    font_size = 50
    while font_size >= 26:
        font = ImageFont.truetype(FONT_PATH, font_size)
        lines = wrap_text(draw, text, font, max_text_width)
        line_height = int(font_size * 1.3)
        box_height = (line_height * len(lines)) + 100
        if box_height <= max_box_height: break
        font_size -= 4

    # Малювання плашки та тексту на полотні
    box_top = (CANVAS_H - box_height) // 2
    box_left, box_right = 60, CANVAS_W - 60
    draw.rounded_rectangle([box_left, box_top, box_right, box_top + box_height], radius=30, fill=BOX_BG)
    draw.rounded_rectangle([box_left, box_top + 30, box_left + 10, box_top + box_height - 30], radius=5, fill=BOX_ACCENT)

    y = box_top + 50
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (CANVAS_W - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), line, font=font, fill=TEXT_COLOR)
        y += line_height
    img.save(output_path)

# Головна фонова задача обробки та рендерингу відео
async def process_video_task(text: str, uid: str):
    audio_path = f"/tmp/audio_{uid}.mp3"
    overlay_path = f"/tmp/overlay_{uid}.png"
    output_video_path = f"/tmp/video_{uid}.mp4"

    # 1. Надсилаємо початкове сповіщення в Telegram (0%)
    msg_id = await send_progress_message(f"🎬 Генерація відео розпочата...\n{make_progress_bar(0)}")

    try:
        # 2. Етап синтезу мови (Edge-TTS) -> оновлюємо до 20%
        await edit_progress_message(msg_id, f"🎙 Синтез голосу (TTS)...\n{make_progress_bar(20)}")
        communicate = edge_tts.Communicate(text, "uk-UA-PolinaNeural")
        await communicate.save(audio_path)

        # 3. Етап генерації картинки з текстом (Pillow) -> оновлюємо до 50%
        await edit_progress_message(msg_id, f"🎨 Створення дизайну тексту...\n{make_progress_bar(50)}")
        create_text_overlay(text, overlay_path)

        # 4. Етап рендерингу через FFmpeg -> оновлюємо до 80%
        # ОПТИМІЗАЦІЯ ДЛЯ RENDER: додано "-threads 1" та "-preset ultrafast", 
        # щоб процес не перевищував ліміт оперативної пам'яті (уникнення помилки 137 OOM)
        await edit_progress_message(msg_id, f"⚙️ Рендеринг відео через FFmpeg...\n{make_progress_bar(80)}")
        
        result = subprocess.run([
            "ffmpeg", "-y", 
            "-threads", "1",          # Використовувати лише 1 потік процесора (економія RAM)
            "-loop", "1", "-i", BG_PATH,
            "-i", overlay_path, "-i", audio_path,
            "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
            "-map", "[v]", "-map", "2:a",
            "-c:v", "libx264", 
            "-tune", "stillimage", 
            "-preset", "ultrafast",   # Максимально швидкий та легкий пресет кодування
            "-c:a", "aac",
            "-shortest", "-pix_fmt", "yuv420p", output_video_path
        ], capture_output=True, text=True)

        # Перевірка чи успішно завершився FFmpeg
        if result.returncode != 0:
            print(f"FFMPEG Error: {result.stderr}")
            await edit_progress_message(msg_id, "❌ Помилка під час рендерингу відео!")
            return

        # 5. Завантаження готового відео у Telegram -> ставимо 95%
        await edit_progress_message(msg_id, f"📤 Завантаження у Telegram...\n{make_progress_bar(95)}")

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
        async with aiohttp.ClientSession() as session:
            with open(output_video_path, "rb") as video_file:
                data = aiohttp.FormData()
                data.add_field('chat_id', CHAT_ID)
                data.add_field('video', video_file, filename='video.mp4')
                data.add_field('caption', "✅ Твоє відео готове!")
                async with session.post(url, data=data) as response:
                    await response.json()

        # Видаляємо службове текстове повідомлення з прогрес-баром, щоб не засмічувати чат
        if msg_id:
            async with aiohttp.ClientSession() as session:
                await session.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage", json={"chat_id": CHAT_ID, "message_id": msg_id})

    except Exception as e:
        print(f"Task error: {e}")
        if msg_id:
            await edit_progress_message(msg_id, f"❌ Сталася помилка: {str(e)}")
            
    finally:
        # Очищення тимчасових файлів з дисків контейнера у будь-якому випадку (успіх/помилка)
        for p in [audio_path, overlay_path, output_video_path]:
            if os.path.exists(p): os.remove(p)

# Ендпоінт, який приймає POST-запити від n8n і запускає фоновий процес
@app.post("/generate-video")
async def generate_video(data: dict, background_tasks: BackgroundTasks):
    text = data.get("text")
    if not text: raise HTTPException(status_code=400, detail="No text provided")
    
    # Генеруємо унікальний ідентифікатор для сесії
    uid = uuid.uuid4().hex[:8]
    
    # Додаємо задачу у фонові процеси FastAPI, щоб не блокувати відповідь сервера
    background_tasks.add_task(process_video_task, text, uid)
    return {"status": "processing_started", "uid": uid}
