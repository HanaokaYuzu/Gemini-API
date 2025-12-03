# 🔍 Диагностика 404 ошибки

## Проблема
```
404 - "404 page not found\n"
```

Это **НЕ от FastAPI** (FastAPI возвращает JSON), а от **Traefik/Dockploy**.

---

## ✅ Ваши настройки Dockploy (со скриншота)

![Dockploy Settings](file:///home/inves/.gemini/antigravity/brain/b21159f9-226d-4614-9e45-6304aa45402f/uploaded_image_1764789503487.png)

| Поле | Значение | Статус |
|------|----------|--------|
| Service Name | `gemini-api` | ✅ Правильно |
| Host | `gemini-automation-1-workers.contentmill.tech` | ✅ Правильно |
| Path | `/` | ✅ Правильно |
| Internal Path | `/` | ✅ Правильно |
| Strip Path | `OFF` | ✅ Правильно |
| Container Port | `8000` | ✅ Правильно |

**Настройки верные!** Проблема в другом.

---

## 🐛 Возможные причины 404

### 1. Контейнер не в той же Docker сети

**Проблема:** Traefik не может достучаться до контейнера.

**Проверка:**
```bash
# В Dockploy terminal
docker network inspect <traefik-network-name>
# Проверь что gemini-api в списке контейнеров
```

**Решение:** Убедись что в `docker-compose.yml` указана правильная сеть.

---

### 2. Service Name не совпадает с docker-compose

**Проблема:** В Dockploy указано `gemini-api`, а в docker-compose другое имя.

**Проверка:**
```bash
docker ps | grep gemini
```

**В вашем docker-compose.yml:**
```yaml
services:
  gemini-api:  # ⬅️ Это имя должно совпадать с Service Name в Dockploy
```

✅ У вас совпадает, всё ОК.

---

### 3. Traefik labels отсутствуют

**Проблема:** Если используется Traefik напрямую (не через Dockploy UI), нужны labels.

**Решение:** Dockploy добавляет labels автоматически, НО проверь что они добавились:

```bash
docker inspect gemini-api | grep -i traefik
```

Должны быть labels типа:
```
traefik.enable=true
traefik.http.routers.gemini-api.rule=Host(`gemini-automation-1-workers.contentmill.tech`)
traefik.http.services.gemini-api.loadbalancer.server.port=8000
```

---

### 4. Health check проходит, но приложение недоступно

**Проблема:** Контейнер запущен, но Traefik не может проксировать запросы.

**Проверка внутри контейнера:**
```bash
# В Dockploy terminal для gemini-api
docker exec -it <container-id> curl http://localhost:8000/health
```

Должно вернуть:
```json
{"status":"healthy","message":"Gemini API работает нормально"}
```

---

## 🔧 Что сделано для диагностики

### Добавлено в `app.py`:

**Request Logging Middleware** — теперь КАЖДЫЙ входящий запрос логируется:
```python
@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"🔵 Incoming Request:")
    print(f"   Method: {request.method}")
    print(f"   URL: {request.url}")
    print(f"   Path: {request.url.path}")
    # ...
```

**После деплоя с новым кодом увидишь в логах:**
- ✅ Если запросы ДОХОДЯТ до FastAPI → проблема не в Dockploy
- ❌ Если запросов НЕТ в логах → проблема в Traefik/Dockploy маршрутизации

---

## 🧪 Тесты для диагностики

### 1. Проверка внутри контейнера
```bash
# В Dockploy terminal
docker exec -it <gemini-api-container> sh
curl http://localhost:8000/health
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"prompt":"test"}'
```

Если работает → проблема в Traefik.

---

### 2. Проверка Network connectivity
```bash
# Найди Traefik network
docker network ls | grep traefik

# Проверь что gemini-api в этой сети
docker network inspect <traefik-network>
```

---

### 3. Проверка Traefik Dashboard
Если у тебя доступ к Traefik Dashboard:
- Открой `http://<traefik-host>:8080/dashboard/`
- Найди роутер для `gemini-automation-1-workers.contentmill.tech`
- Проверь что он ведёт на правильный сервис и порт

---

## ✅ Следующие шаги

1. **Запусти с новым логированием:**
   ```bash
   git pull  # В Dockploy
   docker-compose up -d --build
   ```

2. **Сделай запрос:**
   ```bash
   curl https://gemini-automation-1-workers.contentmill.tech/health
   ```

3. **Смотри логи:**
   ```bash
   docker logs -f <gemini-api-container>
   ```

4. **Анализируй:**
   - Видишь `🔵 Incoming Request` → запрос доходит, FastAPI обрабатывает
   - НЕ видишь `🔵` → запрос не доходит до контейнера, проблема в Traefik

---

## 🎯 Вероятная причина

Судя по "404 page not found\n" (текстовый ответ, а не JSON), это **100% ответ от Traefik**, не от FastAPI.

**Скорее всего:** Traefik не может найти сервис по имени `gemini-api`.

**Проверь:**
```bash
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}"
```

Должно быть что-то типа:
```
gemini-api    ...    0.0.0.0:8000->8000/tcp
```

Или в формате Dockploy:
```
gemini-worker-1-num-nglfr7-gemini-api-1
```

⚠️ Если имя контейнера **НЕ** `gemini-api`, а что-то вроде `gemini-worker-1-num-nglfr7-gemini-api-1`, то в Dockploy UI в поле **Service Name** нужно указать **ПОЛНОЕ имя контейнера**.

Попробуй изменить:
```
Service Name: gemini-worker-1-num-nglfr7-gemini-api-1
```

(вместо просто `gemini-api`)
