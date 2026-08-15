FROM python:3.10-slim

# Встановлюємо системні залежності та FFmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Робоча директорія всередині контейнера
WORKDIR /app

# Копіюємо та встановлюємо залежності Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо весь код проекту та ресурси (main.py, шрифт, фон)
COPY . .

# Відкриваємо порт, який слухає FastAPI
EXPOSE 8000

# Команда для запуску веб-сервера
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
