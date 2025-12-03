# 📚 Полный Функционал Gemini-API

*Документация создана: 2025-12-04*  
*Версия: 1.0.0*

---

## 📋 Содержание

1. [Поддерживаемые Модели](#-поддерживаемые-модели)
2. [Типы Файлов](#-типы-файлов)
3. [Основные Методы API](#-основные-методы-api)
4. [Параметры Инициализации](#-параметры-инициализации)
5. [Работа с Изображениями](#-работа-с-изображениями)
6. [Gemini Gems (Системные Промпты)](#-gemini-gems-системные-промпты)
7. [Расширения Gemini](#-расширения-gemini)
8. [Режимы Работы](#-режимы-работы)
9. [HTTP API Endpoints](#-http-api-endpoints)
10. [Переменные Окружения](#-переменные-окружения)

---

## 🤖 Поддерживаемые Модели

### Актуальные модели (по состоянию на ноябрь 2025)

| Модель | Константа | Описание | Thinking Support |
|--------|-----------|----------|------------------|
| **Gemini 3.0 Pro** | `Model.G_3_0_PRO` | Продвинутая модель нового поколения | ❌ |
| **Gemini 2.5 Pro** | `Model.G_2_5_PRO` | Pro-версия с reasoning (размышлениями) | ✅ |
| **Gemini 2.5 Flash** | `Model.G_2_5_FLASH` | Быстрая модель для простых задач | ❌ |
| **Unspecified** | `Model.UNSPECIFIED` | Модель по умолчанию | ❌ |

### Использование

#### Через Enum константу
```python
from gemini_webapi.constants import Model

response = await client.generate_content(
    "Привет, мир!",
    model=Model.G_2_5_FLASH
)
```

#### Через строку
```python
response = await client.generate_content(
    "Привет, мир!",
    model="gemini-2.5-pro"
)
```

#### Кастомная модель (с custom header)
```python
custom_model = {
    "model_name": "gemini-experimental-999",
    "model_header": {
        "x-goog-ext-525001261-jspb": '[1,null,null,null,"custom_hash",null,null,0,[4]]'
    }
}

response = await client.generate_content(
    "Тест кастомной модели",
    model=custom_model
)
```

### Доступ к процессу размышления (Thinking)

Только для моделей с поддержкой reasoning (например, `gemini-2.5-pro`):

```python
response = await client.generate_content(
    "Решите сложную задачу: 1+1",
    model=Model.G_2_5_PRO
)

print(response.thoughts)  # Процесс размышления модели
print(response.text)      # Финальный ответ
```

---

## 📎 Типы Файлов

### Поддерживаемые форматы

API поддерживает загрузку файлов через метод `upload_file()`. По факту, **Gemini поддерживает любые файлы**, которые принимает web-интерфейс, включая:

#### 🖼️ Изображения
- PNG (`.png`)
- JPEG (`.jpg`, `.jpeg`)
- GIF (`.gif`)
- WebP (`.webp`)
- BMP (`.bmp`)

#### 📄 Документы
- PDF (`.pdf`)
- Текстовые файлы (`.txt`)
- Markdown (`.md`)
- И другие документы, которые поддерживает веб-интерфейс Gemini

### Использование файлов

#### Загрузка одного файла
```python
response = await client.generate_content(
    "Опиши содержимое этого файла",
    files=["path/to/document.pdf"]
)
```

#### Загрузка нескольких файлов
```python
from pathlib import Path

response = await client.generate_content(
    "Есть ли связь между этими файлами?",
    files=[
        "path/to/image.png",
        Path("path/to/document.pdf"),
        "path/to/another_image.jpg"
    ]
)
```

#### В диалоге
```python
chat = client.start_chat()
response = await chat.send_message(
    "Сравни эти два изображения",
    files=["image1.png", "image2.png"]
)
```

### Ограничения

- Файлы загружаются через Google's Upload Endpoint
- Файлы имеют TTL (Time-To-Live) = 1 день на серверах Google
- Максимальный размер файла зависит от ограничений Gemini web-интерфейса

---

## 🔧 Основные Методы API

### `GeminiClient` - Главный класс

#### Инициализация

```python
from gemini_webapi import GeminiClient

# С явными cookies
client = GeminiClient(
    secure_1psid="g.a000lwi...",
    secure_1psidts="sidts-CjEB...",
    proxy=None  # опционально
)

# Или автоматически из браузера (требует browser-cookie3)
client = GeminiClient()
```

#### `init()` - Запуск клиента

```python
await client.init(
    timeout=300,              # Таймаут запросов (секунды)
    auto_close=False,         # Автозакрытие при простое
    close_delay=300,          # Задержка перед автозакрытием
    auto_refresh=True,        # Автообновление cookies
    refresh_interval=540,     # Интервал обновления (секунды)
    verbose=True              # Подробные логи
)
```

#### `generate_content()` - Генерация контента

**Параметры:**
- `prompt` (str, обязательно) - текст запроса
- `files` (list[str | Path], опционально) - список файлов
- `model` (Model | str | dict, опционально) - выбор модели
- `gem` (Gem | str, опционально) - применить системный промпт
- `chat` (ChatSession, опционально) - контекст диалога
- `**kwargs` - дополнительные параметры для httpx.post()

**Возвращает:** `ModelOutput` объект

```python
response = await client.generate_content(
    prompt="Расскажи анекдот",
    model=Model.G_2_5_FLASH
)

print(response.text)       # Текст ответа
print(response.images)     # Список изображений
print(response.thoughts)   # Размышления (если модель поддерживает)
print(response.metadata)   # Метаданные диалога
print(response.candidates) # Альтернативные варианты ответа
```

#### `start_chat()` - Создание диалога

```python
# Новый диалог
chat = client.start_chat(
    model=Model.G_2_5_PRO,
    gem="coding-partner"  # ID гема
)

# Продолжение существующего диалога
previous_metadata = ["cid_value", "rid_value", "rcid_value"]
chat = client.start_chat(metadata=previous_metadata)
```

#### `close()` - Закрытие клиента

```python
await client.close(delay=0)  # delay в секундах
```

---

### `ChatSession` - Управление диалогом

#### `send_message()` - Отправка сообщения

```python
chat = client.start_chat()

response1 = await chat.send_message("Привет!")
response2 = await chat.send_message("Расскажи больше")
```

#### `choose_candidate()` - Выбор альтернативы

Gemini иногда возвращает несколько вариантов ответа:

```python
response = await chat.send_message("Порекомендуй книгу")

# Посмотреть все варианты
for i, candidate in enumerate(response.candidates):
    print(f"Вариант {i}: {candidate.text[:50]}...")

# Выбрать второй вариант
if len(response.candidates) > 1:
    new_answer = chat.choose_candidate(index=1)
    followup = await chat.send_message("Расскажи подробнее")
```

#### `metadata` - Сохранение контекста

```python
chat = client.start_chat()
await chat.send_message("Первое сообщение")

# Сохранить для восстановления позже
saved_metadata = chat.metadata

# ... через время ...

# Восстановить диалог
restored_chat = client.start_chat(metadata=saved_metadata)
response = await restored_chat.send_message("Помнишь мой первый вопрос?")
```

---

## ⚙️ Параметры Инициализации

### Cookies Management

```python
client = GeminiClient(
    secure_1psid="__Secure-1PSID cookie value",
    secure_1psidts="__Secure-1PSIDTS cookie value",  # опционально
    proxy="http://user:pass@proxy:8080"              # опционально
)
```

**Автоматическая загрузка из браузера** (если установлен `browser-cookie3`):
```python
# Автоматически из Chrome/Firefox/Edge
client = GeminiClient()
```

### Timeout Configuration

Контролирует максимальное время ожидания ответа от Gemini:

```python
await client.init(timeout=300)  # 5 минут
```

### Auto-Close (ресурсосбережение)

Для always-on сервисов (ботов):

```python
await client.init(
    auto_close=True,
    close_delay=300  # Закрыть после 5 минут простоя
)
```

### Auto-Refresh Cookies

Автоматическое обновление `__Secure-1PSIDTS` в фоне:

```python
await client.init(
    auto_refresh=True,
    refresh_interval=540  # Каждые 9 минут
)
```

### Proxy Support

```python
# HTTP Proxy
client = GeminiClient(proxy="http://proxy.example.com:8080")

# С авторизацией
client = GeminiClient(proxy="http://user:pass@proxy:8080")

# SOCKS5
client = GeminiClient(proxy="socks5://proxy:1080")
```

---

## 🎨 Работа с Изображениями

### Типы изображений

#### `WebImage` - Изображения из интернета

Возвращаются, когда просите **"send"** (отправь) изображения:

```python
response = await client.generate_content("Send me pictures of cats")

for img in response.images:
    print(type(img))  # <class 'gemini_webapi.types.WebImage'>
    print(img.url)
    print(img.title)
    print(img.alt)
```

#### `GeneratedImage` - AI-сгенерированные

Возвращаются, когда просите **"generate"** (создай) изображения:

```python
response = await client.generate_content("Generate a picture of a cat")

for img in response.images:
    print(type(img))  # <class 'gemini_webapi.types.GeneratedImage'>
```

### Сохранение изображений

#### Базовое сохранение
```python
response = await client.generate_content("Generate images of cats")

for i, image in enumerate(response.images):
    await image.save(
        path="downloads/",
        filename=f"cat_{i}.png",
        verbose=True
    )
```

#### Опции сохранения

```python
await image.save(
    path="temp/",                    # Директория для сохранения
    filename="custom_name.png",      # Имя файла (опционально)
    verbose=True,                    # Печать статуса
    skip_invalid_filename=True,      # Пропустить невалидные имена
    full_size=True                   # Для GeneratedImage: полный размер (2048x2048)
)
```

### Image-to-Image (редактирование)

```python
response = await client.generate_content(
    "Создай иконку приложения на основе этого изображения. Сделай её современной.",
    files=["banner.png"]
)

# Сохранить сгенерированные варианты
for i, img in enumerate(response.images):
    await img.save(filename=f"icon_variant_{i}.png")
```

### Генерация изображений в диалоге

```python
chat = client.start_chat()

response1 = await chat.send_message(
    "В чём разница между этими изображениями?",
    files=["image1.png", "image2.png"]
)

response2 = await chat.send_message(
    "Используй генератор изображений и создай новую версию первого изображения"
)

for img in response2.images:
    await img.save()
```

> **Важно:** Генерация изображений доступна не во всех регионах и только для пользователей 18+. [Подробности](https://support.google.com/gemini/answer/14286560)

---

## 💎 Gemini Gems (Системные Промпты)

Gems позволяют применять **системные промпты** (инструкции для модели).

### Получение списка Gems

```python
# Загрузить все доступные gems
await client.fetch_gems(include_hidden=False)

# Доступ к кешированным gems
gems = client.gems

# Фильтрация
system_gems = gems.filter(predefined=True)    # Системные
custom_gems = gems.filter(predefined=False)   # Пользовательские

# Поиск по ID
coding_gem = gems.get(id="coding-partner")

# Поиск по имени
my_gem = gems.get(name="My Custom Gem")
```

### Использование Gem

```python
await client.fetch_gems()
coding_partner = client.gems.get(id="coding-partner")

response = await client.generate_content(
    "Напиши функцию для сортировки массива",
    model=Model.G_2_5_FLASH,
    gem=coding_partner
)
```

### Создание Custom Gem

```python
new_gem = await client.create_gem(
    name="Python Tutor",
    prompt="Ты - опытный преподаватель Python. Объясняй концепции просто и с примерами.",
    description="Гем для обучения Python"
)

# Использовать созданный gem
response = await client.generate_content(
    "Объясни list comprehensions",
    gem=new_gem
)
```

### Обновление Gem

> **Важно:** При обновлении нужно передать **все** параметры

```python
await client.fetch_gems()
python_tutor = client.gems.get(name="Python Tutor")

updated_gem = await client.update_gem(
    gem=python_tutor,
    name="Advanced Python Tutor",
    prompt="Ты - эксперт Python. Давай продвинутые объяснения с best practices.",
    description="Продвинутый Python ассистент"
)
```

### Удаление Gem

```python
await client.delete_gem(python_tutor)
# или
await client.delete_gem("gem_id_string")
```

### Gem в Chat Session

```python
chat = client.start_chat(
    model=Model.G_2_5_FLASH,
    gem="coding-partner"
)

response = await chat.send_message("Нужен код для API")
```

---

## 🔌 Расширения Gemini

Gemini поддерживает расширения для доступа к внешним сервисам.

### Доступные расширения

- **@Gmail** - доступ к почте
- **@Youtube** - поиск видео
- **@Google Workspace** - документы, календарь
- **@Maps** - карты и локации

> **Важно:** 
> - Расширения должны быть активированы на [gemini.google.com/extensions](https://gemini.google.com/extensions)
> - Требуется включенная `Gemini Apps Activity`
> - Для пользователей до 18 лет работают только с английскими промптами

### Использование

#### Gmail
```python
response = await client.generate_content(
    "@Gmail Какие последние 3 письма в моём ящике?"
)
```

#### YouTube
```python
response = await client.generate_content(
    "@Youtube Найди последние видео Taylor Swift"
)
```

#### Google Workspace
```python
response = await client.generate_content(
    "@Docs Покажи мои последние документы"
)
```

#### Естественный язык (без @)
```python
response = await client.generate_content(
    "Найди в моей почте письма от начальника за последнюю неделю"
)
```

---

## 🏃 Режимы Работы

### 1. CLI Mode (для тестирования)

```bash
MODE=cli python app.py
```

**Функционал:**
- Одиночные запросы
- Пример диалога
- Демонстрация возможностей

### 2. API Mode (для продакшена)

```bash
MODE=api python app.py
```

Запускает FastAPI HTTP сервер на `0.0.0.0:8000`

---

## 🌐 HTTP API Endpoints

### `POST /ask`

Отправка запроса в Gemini

**Request Body:**
```json
{
  "prompt": "Расскажи анекдот про программистов",
  "model": "gemini-2.5-flash"
}
### 1. Отправка запроса (`/ask`)

**Endpoint:** `POST /ask`

**Параметры (JSON):**
*   `prompt` (str, required): Текст запроса.
*   `model` (str, optional): Модель для генерации.
    *   Доступные значения: `gemini-3.0-pro`, `gemini-2.5-pro`, `gemini-2.5-flash`.
    *   По умолчанию: `gemini-2.5-flash` (или последняя активная).

**Пример запроса (cURL):**
```bash
curl -X POST "http://localhost:8000/ask" \
     -H "Content-Type: application/json" \
     -d '{
           "prompt": "Напиши код на Python",
           "model": "gemini-2.5-pro"
         }'
```

**Response:**
```json
{
  "text": "Текст ответа от Gemini...",
  "thoughts": null,
  "images": ["url1", "url2"],
  "metadata": ["cid", "rid", "rcid"]
}
```

**Пример (Python):**
```python
import requests

response = requests.post(
    "http://localhost:8000/ask",
    json={
        "prompt": "Расскажи про async/await",
        "model": "gemini-2.5-pro"
    }
)

data = response.json()
print(data["text"])
```

### `GET /health`

Health check для мониторинга

**Response:**
```json
{
  "status": "healthy",
  "message": "Gemini API работает нормально"
}
```

**Пример:**
```bash
curl http://localhost:8000/health
```

---

## 🔐 Переменные Окружения

### Обязательные

```bash
# Cookies из браузера
GEMINI_PSID=g.a000lwi...
GEMINI_PSIDTS=sidts-CjEB...

# Режим работы
MODE=api  # или "cli"
```

### Опциональные - Сеть

```bash
# Proxy (формат: http://user:pass@ip:port)
GEMINI_PROXY=http://proxy.example.com:8080
```

### Опциональные - API Server

```bash
API_HOST=0.0.0.0
API_PORT=8000
```

### Опциональные - Gemini Client

```bash
# Таймаут запросов (секунды)
GEMINI_TIMEOUT=30

# Автообновление cookies
GEMINI_AUTO_REFRESH=true
GEMINI_REFRESH_INTERVAL=540

# Путь для хранения cookies (Docker volumes)
GEMINI_COOKIE_PATH=/tmp/gemini_webapi
```

### Опциональные - Логирование

```bash
# Уровень логов: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL=INFO
```

---

## 📊 ModelOutput - Структура ответа

```python
class ModelOutput:
    text: str                    # Текстовый ответ
    thoughts: str | None         # Размышления модели (если поддерживается)
    images: list[Image]          # Список изображений (WebImage | GeneratedImage)
    metadata: list[str]          # [conversation_id, reply_id, reply_candidate_id]
    candidates: list[Candidate]  # Альтернативные варианты ответа
    chosen: int                  # Индекс выбранного кандидата
```

**Использование:**
```python
response = await client.generate_content("Привет")

print(response.text)                     # Просто текст
print(response)                          # То же самое (используется __str__)
print(len(response.images))              # Количество изображений
print(response.metadata)                 # Для восстановления диалога
print(f"Вариантов ответа: {len(response.candidates)}")
```

---

## 🛠️ Утилиты и Хелперы

### Логирование

```python
from gemini_webapi import set_log_level

set_log_level("DEBUG")   # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

### Парсинг имён файлов

```python
from gemini_webapi.utils import parse_file_name
from pathlib import Path

filename = parse_file_name("path/to/document.pdf")
print(filename)  # "document.pdf"
```

---

## ⚠️ Исключения

```python
from gemini_webapi.exceptions import (
    AuthError,              # Неверные credentials
    TimeoutError,           # Таймаут запроса
    GeminiError,            # Общая ошибка Gemini
    APIError,               # Ошибка HTTP запроса
    UsageLimitExceeded,     # Превышен лимит использования
    ModelInvalid,           # Недоступная модель
)
```

**Обработка:**
```python
try:
    response = await client.generate_content("тест")
except AuthError:
    print("Неверные cookies!")
except TimeoutError:
    print("Запрос занял слишком много времени")
except UsageLimitExceeded:
    print("Превышен лимит запросов")
except APIError as e:
    print(f"Ошибка API: {e}")
```

---

## 🔄 Best Practices

### 1. Используйте Auto-Refresh для Always-On сервисов

```python
await client.init(
    auto_refresh=True,
    refresh_interval=540  # 9 минут
)
```

### 2. Сохраняйте metadata диалогов

```python
# Сохранить
chat = client.start_chat()
response = await chat.send_message("Привет")
metadata = chat.metadata
# ... сохранить в БД/файл

# Восстановить
chat = client.start_chat(metadata=metadata)
```

### 3. Обрабатывайте альтернативные ответы

```python
response = await chat.send_message("Порекомендуй книгу")

if len(response.candidates) > 1:
    # Дать пользователю выбор
    for i, candidate in enumerate(response.candidates):
        print(f"Вариант {i+1}: {candidate.text[:100]}...")
```

### 4. Используйте правильные модели

- **Gemini 2.5 Flash** - для быстрых, простых задач
- **Gemini 2.5 Pro** - для сложных задач с reasoning
- **Gemini 3.0 Pro** - новейшая модель (experimental)

### 5. Для Docker: Монтируйте volume для cookies

```yaml
services:
  gemini-api:
    environment:
      GEMINI_COOKIE_PATH: /tmp/gemini_webapi
    volumes:
      - ./gemini_cookies:/tmp/gemini_webapi
```

---

## 📈 Производительность

### Таймауты

- По умолчанию: **30 секунд** (из app.py)
- Рекомендуется: **300 секунд** для сложных запросов
- Настройка: `GEMINI_TIMEOUT` env var

### Ограничения

- Google может ограничивать частоту запросов
- При превышении: `UsageLimitExceeded` exception
- Решение: используйте разные аккаунты или ждите

---

## 🚀 Примеры Интеграции

### Discord Bot

```python
import discord
from gemini_webapi import GeminiClient

client = GeminiClient(...)
await client.init()

@bot.command()
async def ask(ctx, *, question):
    response = await client.generate_content(question)
    await ctx.send(response.text)
```

### Telegram Bot

```python
from telegram import Update
from telegram.ext import Application, CommandHandler

gemini = GeminiClient(...)
await gemini.init()

async def ask_handler(update: Update, context):
    prompt = " ".join(context.args)
    response = await gemini.generate_content(prompt)
    await update.message.reply_text(response.text)
```

### FastAPI Integration

```python
from fastapi import FastAPI
from gemini_webapi import GeminiClient

app = FastAPI()
gemini_client = None

@app.on_event("startup")
async def startup():
    global gemini_client
    gemini_client = GeminiClient(...)
    await gemini_client.init()

@app.post("/ask")
async def ask(prompt: str):
    response = await gemini_client.generate_content(prompt)
    return {"answer": response.text}
```

---

## 🐛 Troubleshooting

### "Failed to initialize client"
- **Причина:** Неверные cookies
- **Решение:** Получить новые `__Secure-1PSID` и `__Secure-1PSIDTS`

### "Model not available"
- **Причина:** Модель недоступна для аккаунта
- **Решение:** Использовать другую модель или проверить доступ

### "Usage limit exceeded"
- **Причина:** Превышен лимит запросов
- **Решение:** Подождать или использовать другой аккаунт

### "Connection timeout"
- **Причина:** Запрос занял слишком много времени
- **Решение:** Увеличить `GEMINI_TIMEOUT`

---

## 📝 Changelog

**Версия 1.0.0** (2025-12-04)
- Начальная версия документации
- Описание всех моделей, методов и параметров
- Примеры использования для всех функций

---

## 📞 Поддержка

- **GitHub Issues:** [HanaokaYuzu/Gemini-API/issues](https://github.com/HanaokaYuzu/Gemini-API/issues)
- **Документация:** [README.md](README.md)
- **PyPI:** [gemini-webapi](https://pypi.org/project/gemini-webapi)

---

**Документация подготовлена на основе анализа кода Gemini-API v1.0.0**
