# Multi-stage build для оптимизации размера образа
FROM python:3.11-slim as builder

WORKDIR /build

# Установка build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Установка зависимостей gemini-webapi вручную (из pyproject.toml)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    'httpx[http2]~=0.28.1' \
    'loguru~=0.7.3' \
    'orjson~=3.11.1' \
    'pydantic~=2.12.2'

# ============================================
# Production stage
# ============================================
FROM python:3.11-slim

WORKDIR /app

# Установка runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копирование установленных зависимостей из builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Копирование исходников gemini_webapi НАПРЯМУЮ в site-packages
COPY src/gemini_webapi /usr/local/lib/python3.11/site-packages/gemini_webapi/

# Установка дополнительных зависимостей для app.py
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Копирование приложения
COPY app.py ./

# Создание non-root пользователя для безопасности
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/cookies && \
    chmod 777 /app/cookies && \
    chown -R appuser:appuser /app

USER appuser

# Переменные окружения
ENV PYTHONUNBUFFERED=1 \
    GEMINI_COOKIE_PATH=/app/cookies

# По умолчанию запуск в CLI режиме
CMD ["python", "app.py"]
