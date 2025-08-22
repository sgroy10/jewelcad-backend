# Small, clean image
FROM python:3.11-slim

# Basics
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App
COPY app.py .

# Railway will use this port
EXPOSE 8000
ENV PORT=8000

# Start with gunicorn (no Railway start command needed)
CMD ["bash","-lc","gunicorn app:app --bind 0.0.0.0:${PORT}"]
