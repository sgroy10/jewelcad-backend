FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

ENV PORT=8080
EXPOSE 8080
CMD ["gunicorn", "app:app", "--workers", "2", "--threads", "4", "--timeout", "120", "--bind", "0.0.0.0:8080"]
