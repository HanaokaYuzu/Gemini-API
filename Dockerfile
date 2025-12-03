# Multi-stage build для оптимизации размера образа
FROM python:3.11-slim as builder

WORKDIR /build

# Установка build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копирование файлов проекта
COPY pyproject.toml ./
COPY src/ ./src/

# Установка зависимостей
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -e .

# ============================================
# Production stage
# ============================================
FROM python:3.11-slim

WORKDIR /app

# Установка runtime dependencies (если нужны)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Копирование установленных пакетов из builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Копирование исходников библиотеки
COPY src/ ./src/
COPY pyproject.toml ./

# Установка дополнительных зависимостей для app.py
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Копирование приложения
COPY app.py ./

# Создание non-root пользователя для безопасности
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/cookies && \
    chown -R appuser:appuser /app

USER appuser

# Переменные окружения
ENV PYTHONUNBUFFERED=1 \
    GEMINI_COOKIE_PATH=/app/cookies

# По умолчанию запуск в CLI режиме
CMD ["python", "app.py"]
