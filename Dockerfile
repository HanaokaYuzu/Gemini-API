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
# Используем SETUPTOOLS_SCM_PRETEND_VERSION для обхода проблемы с .git в .dockerignore
ENV SETUPTOOLS_SCM_PRETEND_VERSION=1.0.0
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir .

# ============================================
# Production stage
# ============================================
FROM python:3.11-slim

WORKDIR /app

# Установка runtime dependencies (если нужны)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Копирование установленных зависимостей из builder (без самого пакета gemini_webapi)
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Копирование исходников библиотеки ПОЛНОСТЬЮ (важно для всех подмодулей)
COPY src/gemini_webapi /usr/local/lib/python3.11/site-packages/gemini_webapi

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
