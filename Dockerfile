# UltraBet — production image.
#
# Сборка:
#   docker build -t ultrabet:latest .
# Запуск:
#   docker run --rm --env-file .env -v $(pwd)/data:/app/data ultrabet:latest
#
# Образ slim, без компилятора. Если ставить lightgbm/numpy с нуля — ставить
# сборочные пакеты в build-stage и копировать готовые wheels.

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# --- system deps ---
RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# --- python deps ---
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# --- application ---
COPY . /app

RUN mkdir -p /app/data /app/logs /app/data/models /app/data/backups

# Создаём непривилегированного пользователя.
RUN groupadd --system ultrabet && useradd --system --gid ultrabet --home /app ultrabet \
    && chown -R ultrabet:ultrabet /app
USER ultrabet

# Healthcheck — простой импорт config (для оркестратора этого достаточно,
# реальный probe по Telegram polling сделать нельзя).
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "from config import get_settings; get_settings(); print('ok')" \
        || exit 1

CMD ["python", "-m", "main"]
