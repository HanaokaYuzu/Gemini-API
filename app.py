#!/usr/bin/env python3
"""
Gemini API Docker Application

Поддерживает два режима работы:
1. CLI - простой скрипт для одиночных запросов
2. API - FastAPI сервер с HTTP endpoints
"""

import asyncio
import os
import sys
from typing import Optional
from pathlib import Path

from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()


# ============================================
# CLI Mode
# ============================================
async def run_cli():
    """Простой CLI режим для одиночных запросов"""
    from gemini_webapi import GeminiClient, set_log_level
    
    # Настройка логирования
    log_level = os.getenv("LOG_LEVEL", "INFO")
    set_log_level(log_level)
    
    # Получение credentials из переменных окружения
    psid = os.getenv("GEMINI_PSID")
    psidts = os.getenv("GEMINI_PSIDTS")
    proxy = os.getenv("GEMINI_PROXY")
    
    if not psid:
        print("❌ Ошибка: GEMINI_PSID не установлен!")
        print("📝 Установите переменные окружения в .env файле")
        sys.exit(1)
    
    # Создание клиента
    client = GeminiClient(
        secure_1psid=psid,
        secure_1psidts=psidts,
        proxy=proxy
    )
    
    # Инициализация
    timeout = int(os.getenv("GEMINI_TIMEOUT", "30"))
    auto_refresh = os.getenv("GEMINI_AUTO_REFRESH", "true").lower() == "true"
    refresh_interval = int(os.getenv("GEMINI_REFRESH_INTERVAL", "540"))
    
    try:
        await client.init(
            timeout=timeout,
            auto_close=False,
            auto_refresh=auto_refresh,
            refresh_interval=refresh_interval,
            verbose=True
        )
        
        print("✅ Gemini клиент инициализирован!")
        print("=" * 60)
        
        # Простой пример запроса
        prompt = "Привет! Расскажи анекдот про программистов на русском языке."
        print(f"📤 Запрос: {prompt}\n")
        
        response = await client.generate_content(prompt)
        
        print(f"📥 Ответ:\n{response.text}")
        print("=" * 60)
        
        # Пример диалога
        print("\n🔄 Создание диалога...\n")
        chat = client.start_chat()
        
        msg1 = await chat.send_message("Объясни, почему этот анекдот смешной")
        print(f"📥 Ответ 2:\n{msg1.text}")
        print("=" * 60)
        
        # Сохранение metadata для продолжения диалога
        print(f"\n💾 Metadata диалога: {chat.metadata}")
        print("   (можно использовать для продолжения после перезапуска)")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)
    finally:
        await client.close()
        print("\n✅ Клиент закрыт")


# ============================================
# API Mode
# ============================================
def run_api():
    """FastAPI сервер для приёма HTTP запросов"""
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field
    import uvicorn
    from gemini_webapi import set_log_level
    from gemini_webapi.pool import ClientPool
    from contextlib import asynccontextmanager
    
    # Модели запросов/ответов
    class AskRequest(BaseModel):
        prompt: str = Field(..., min_length=1, description="Текст запроса к Gemini")
        model: Optional[str] = Field(None, description="Модель (gemini-2.5-flash, gemini-2.5-pro и т.д.)")
        aspect_ratio: Optional[str] = Field(None, description="Соотношение сторон (16:9, 4:3, 1:1, etc.)")
        image_url: Optional[str] = Field(None, description="[DEPRECATED] Одиночный URL изображения. Используйте image_urls.")
        image_urls: Optional[list[str]] = Field(None, description="Массив URL изображений для обработки")
        account_id: Optional[str] = Field(None, description="Явный выбор аккаунта (опционально, по умолчанию Round-Robin)")
        
    class AskResponse(BaseModel):
        text: str = Field(..., description="Текстовый ответ от Gemini")
        thoughts: Optional[str] = Field(None, description="Процесс размышления (для про-моделей)")
        images: list[str] = Field(default_factory=list, description="URLs изображений в ответе")
        metadata: list = Field(default_factory=list, description="Metadata диалога для продолжения")
    
    class HealthResponse(BaseModel):
        status: str
        message: str
    
    # Создание FastAPI приложения (перенесено до lifespan)
    app = FastAPI(
        title="Gemini API Proxy",
        description="HTTP API для взаимодействия с Google Gemini",
        version="1.0.0"
    )
    
    # Lifecycle management
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Инициализация и закрытие пула клиентов"""
        # Startup
        log_level = os.getenv("LOG_LEVEL", "INFO")
        set_log_level(log_level)
        
        # Создаём пул
        pool = ClientPool()
        
        # Загрузка конфигурации
        accounts_file = os.getenv("GEMINI_ACCOUNTS_FILE")
        if accounts_file and os.path.exists(accounts_file):
            # Новый режим: загрузка из JSON
            pool.load_config(accounts_file)
            print(f"📂 Загружена конфигурация из {accounts_file}")
        else:
            # Обратная совместимость: ENV переменные
            psid = os.getenv("GEMINI_PSID")
            psidts = os.getenv("GEMINI_PSIDTS")
            proxy = os.getenv("GEMINI_PROXY")
            
            if not psid:
                raise RuntimeError(
                    "Укажите GEMINI_ACCOUNTS_FILE или GEMINI_PSID в переменных окружения!"
                )
            
            pool.add_account_from_env(psid=psid, psidts=psidts, proxy=proxy)
            print("📋 Используется аккаунт из ENV переменных")
        
        # Инициализация всех клиентов
        timeout = int(os.getenv("GEMINI_TIMEOUT", "120"))
        auto_refresh = os.getenv("GEMINI_AUTO_REFRESH", "true").lower() == "true"
        refresh_interval = int(os.getenv("GEMINI_REFRESH_INTERVAL", "540"))
        
        await pool.init_all(
            timeout=timeout,
            auto_refresh=auto_refresh,
            refresh_interval=refresh_interval,
        )
        
        app.state.pool = pool
        
        health = pool.get_health_status()
        print(f"✅ FastAPI сервер запущен. Пул: {health['healthy']}/{health['total']} аккаунтов активно")
        
        yield
        
        # Shutdown
        if hasattr(app.state, 'pool') and app.state.pool:
            await app.state.pool.close_all()
            print("✅ Все клиенты закрыты")
    
    # Установка lifespan ПОСЛЕ создания app
    app.router.lifespan_context = lifespan
    
    # ============================================
    # Request Logging Middleware
    # ============================================
    from fastapi import Request
    import time
    
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Логирование всех входящих запросов"""
        # Пропускаем логирование health-проверок
        if request.url.path == "/health":
            return await call_next(request)
            
        start_time = time.time()
        
        # Логируем до обработки
        print(f"🔵 Incoming Request:")
        print(f"   Method: {request.method}")
        print(f"   URL: {request.url}")
        print(f"   Path: {request.url.path}")
        print(f"   Headers: {dict(request.headers)}")
        print(f"   Client: {request.client.host if request.client else 'unknown'}")
        
        # Обрабатываем запрос
        response = await call_next(request)
        
        # Логируем после обработки
        process_time = time.time() - start_time
        print(f"✅ Response:")
        print(f"   Status: {response.status_code}")
        print(f"   Processing time: {process_time:.3f}s")
        print(f"   ---")
        
        return response
    
    
    @app.post("/ask", response_model=AskResponse)
    async def ask_gemini(request: Request, ask_request: AskRequest):
        """
        Отправка запроса в Gemini и получение ответа
        
        **Пример запроса:**
        ```json
        {
            "prompt": "Расскажи анекдот про программистов",
            "model": "gemini-2.5-flash"
        }
        ```
        """
        pool: ClientPool = request.app.state.pool
        
        if not pool or not pool.accounts:
            raise HTTPException(status_code=503, detail="Пул клиентов не инициализирован")
        
        health = pool.get_health_status()
        if health["healthy"] == 0:
            raise HTTPException(status_code=503, detail="Все аккаунты недоступны")
        
        try:
            print(f"📤 Отправка запроса в Gemini: {ask_request.prompt[:50]}...")
            
            # Сбор всех URL изображений (поддержка как image_url, так и image_urls)
            all_image_urls: list[str] = []
            if ask_request.image_urls:
                all_image_urls.extend(ask_request.image_urls)
            if ask_request.image_url and ask_request.image_url not in all_image_urls:
                all_image_urls.append(ask_request.image_url)
            
            # Скачивание всех изображений
            temp_image_paths: list[str] = []
            if all_image_urls:
                print(f"📥 Скачивание {len(all_image_urls)} изображений...")
                from httpx import AsyncClient as HttpxAsyncClient
                import tempfile
                
                async with HttpxAsyncClient(timeout=30.0) as http_client:
                    for idx, img_url in enumerate(all_image_urls):
                        try:
                            print(f"   [{idx+1}/{len(all_image_urls)}] {img_url[:60]}...")
                            img_response = await http_client.get(img_url)
                            img_response.raise_for_status()
                            
                            # Определяем расширение из Content-Type или URL
                            content_type = img_response.headers.get("content-type", "")
                            if "jpeg" in content_type or "jpg" in content_type:
                                ext = ".jpg"
                            elif "png" in content_type:
                                ext = ".png"
                            elif "webp" in content_type:
                                ext = ".webp"
                            elif "gif" in content_type:
                                ext = ".gif"
                            else:
                                ext = os.path.splitext(img_url.split("?")[0])[1] or ".jpg"
                            
                            # Сохраняем во временный файл
                            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
                                tmp_file.write(img_response.content)
                                temp_image_paths.append(tmp_file.name)
                            
                            print(f"   ✅ Сохранено: {tmp_file.name}")
                        except Exception as download_error:
                            print(f"   ⚠️ Ошибка скачивания [{idx+1}]: {download_error}")
                            # Очистка уже скачанных файлов
                            for path in temp_image_paths:
                                try:
                                    os.unlink(path)
                                except:
                                    pass
                            raise HTTPException(status_code=400, detail=f"Failed to download image {idx+1}: {str(download_error)}")
            
            # Отправка запроса
            kwargs = {}
            if ask_request.model:
                kwargs["model"] = ask_request.model
            
            # Если указан aspect_ratio, передаем его в client
            if ask_request.aspect_ratio:
                kwargs["aspect_ratio"] = ask_request.aspect_ratio
            
            # Если есть изображения, передаем их как файлы
            if temp_image_paths:
                kwargs["files"] = temp_image_paths

            response = await pool.execute(
                prompt=ask_request.prompt,
                account_id=ask_request.account_id,
                **kwargs
            )
            
            # Удаляем временные файлы
            for temp_path in temp_image_paths:
                if os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                        print(f"🗑️ Временный файл удален: {temp_path}")
                    except Exception as del_error:
                        print(f"⚠️ Не удалось удалить временный файл: {del_error}")
            
            # Обработка изображений: скачивание и конвертация в Base64
            image_data_list = []
            if response.images:
                print(f"🎨 Сгенерировано изображений: {len(response.images)}")
                
                import base64
                from httpx import AsyncClient
                
                for i, img in enumerate(response.images):
                    try:
                        # Получаем куки для скачивания (если это GeneratedImage)
                        cookies = getattr(img, "cookies", None)
                        
                        # Скачиваем байты изображения
                        # Используем HTTP/1.1 и стандартные заголовки для надежности
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                            "Referer": "https://gemini.google.com/",
                            "Origin": "https://gemini.google.com"
                        }
                        
                        # Retry logic
                        max_retries = 3
                        img_bytes = None
                        last_error = None
                        
                        for attempt in range(max_retries):
                            try:
                                async with AsyncClient(
                                    http2=False,
                                    follow_redirects=True, 
                                    cookies=cookies, 
                                    proxy=gemini_client.proxy,
                                    headers=headers,
                                    timeout=30.0
                                ) as client:
                                    # Для GeneratedImage нужно добавить параметр размера
                                    url = img.url
                                    if hasattr(img, "validate_cookies"): # Check if GeneratedImage
                                        if "=s" not in url:
                                            url += "=s2048" # Full size
                                        
                                    print(f"   ⬇️ Downloading image (attempt {attempt+1}/{max_retries}): {url[:50]}...")
                                    img_resp = await client.get(url)
                                    img_resp.raise_for_status()
                                    img_bytes = img_resp.content
                                    break # Success
                            except Exception as e:
                                print(f"   ⚠️ Download attempt {attempt+1} failed: {e}")
                                last_error = e
                                import asyncio
                                await asyncio.sleep(1 * (attempt + 1)) # Backoff
                        
                        if img_bytes is None:
                            raise last_error or Exception("Failed to download image after retries")

                        # Проверяем настройки S3
                        s3_endpoint = os.getenv("S3_ENDPOINT_URL")
                        s3_key = os.getenv("S3_ACCESS_KEY_ID")
                        s3_secret = os.getenv("S3_SECRET_ACCESS_KEY")
                        s3_bucket = os.getenv("S3_BUCKET_NAME")
                        
                        if s3_endpoint and s3_key and s3_secret and s3_bucket:
                            # Загрузка в S3
                            try:
                                import boto3
                                from botocore.client import Config
                                
                                session = boto3.session.Session()
                                s3_client = session.client(
                                    's3',
                                    endpoint_url=s3_endpoint,
                                    aws_access_key_id=s3_key,
                                    aws_secret_access_key=s3_secret,
                                    config=Config(signature_version='s3v4'),
                                    region_name=os.getenv("S3_REGION_NAME", "auto")
                                )
                                
                                # Генерируем имя файла (UUID)
                                import uuid
                                filename = f"{uuid.uuid4()}.png"
                                # Папка в бакете
                                folder = "gemini-file-generate"
                                key = f"{folder}/{filename}"
                                
                                print(f"   ☁️ Uploading to S3: {key}...")
                                s3_client.put_object(
                                    Bucket=s3_bucket,
                                    Key=key,
                                    Body=img_bytes,
                                    ContentType='image/png',
                                    ACL='public-read' # Делаем файл публичным
                                )
                                
                                # Формируем публичную ссылку
                                public_domain = os.getenv("S3_PUBLIC_DOMAIN")
                                if public_domain:
                                    # Если домен указан без протокола, добавляем https
                                    if not public_domain.startswith("http"):
                                        public_domain = f"https://{public_domain}"
                                    # Убираем trailing slash если есть
                                    public_domain = public_domain.rstrip("/")
                                    final_url = f"{public_domain}/{key}"
                                else:
                                    # Fallback на endpoint url
                                    # Обычно формат: endpoint/bucket/key
                                    endpoint = s3_endpoint.rstrip("/")
                                    final_url = f"{endpoint}/{s3_bucket}/{key}"
                                    
                                image_data_list.append(final_url)
                                print(f"   ✅ Image uploaded: {final_url}")
                                
                            except Exception as s3_err:
                                print(f"⚠️ S3 Upload Error: {s3_err}")
                                # Fallback to Base64 on error
                                b64_data = base64.b64encode(img_bytes).decode('utf-8')
                                data_uri = f"data:image/png;base64,{b64_data}"
                                image_data_list.append(data_uri)
                        else:
                            # Fallback to Base64 if S3 not configured
                            b64_data = base64.b64encode(img_bytes).decode('utf-8')
                            mime_type = "image/png"
                            data_uri = f"data:{mime_type};base64,{b64_data}"
                            image_data_list.append(data_uri)
                            print(f"   🖼️ Image {i+1} converted to Base64 ({len(b64_data)} chars)")

                    except Exception as img_err:
                        error_msg = f"⚠️ Error downloading image {i}: {str(img_err)}"
                        print(error_msg)
                        image_data_list.append(f"ERROR: {str(img_err)} | URL: {img.url}")
            
            print(f"   📊 Final image_data_list ({len(image_data_list)} items): {image_data_list}")

            # Формирование ответа
            return AskResponse(
                text=response.text,
                thoughts=response.thoughts,
                images=image_data_list,
                metadata=response.metadata
            )
            
        except Exception as e:
            print(f"❌ Ошибка: {type(e).__name__}: {e}")
            # import traceback
            # traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Ошибка при обработке запроса: {str(e)}")
    
    @app.get("/health", response_model=HealthResponse)
    async def health_check(request: Request):
        """Проверка статуса сервиса"""
        pool: ClientPool = request.app.state.pool
        
        if pool:
            health = pool.get_health_status()
            if health["healthy"] > 0:
                return HealthResponse(
                    status="healthy",
                    message=f"Gemini API работает: {health['healthy']}/{health['total']} аккаунтов активно"
                )
        return HealthResponse(
            status="unhealthy",
            message="Все аккаунты недоступны"
        )
    
    @app.get("/health/accounts")
    async def health_accounts(request: Request):
        """Детальный статус всех аккаунтов в пуле"""
        pool: ClientPool = request.app.state.pool
        
        if not pool:
            raise HTTPException(status_code=503, detail="Пул не инициализирован")
        
        return pool.get_health_status()
    
    # Модель для reload запроса
    class ReloadRequest(BaseModel):
        account_id: Optional[str] = Field(None, description="ID аккаунта для перезагрузки (если пусто — перезагрузить все из конфига)")
        psid: Optional[str] = Field(None, description="Новый PSID (опционально)")
        psidts: Optional[str] = Field(None, description="Новый PSIDTS (опционально)")
    
    @app.post("/admin/reload")
    async def reload_accounts(request: Request, reload_request: ReloadRequest):
        """
        Горячая перезагрузка аккаунтов без остановки сервиса.
        
        **Варианты использования:**
        
        1. Перезагрузить все из конфига (если он изменился):
        ```json
        {}
        ```
        
        2. Перезагрузить конкретный аккаунт с новыми куками:
        ```json
        {"account_id": "main", "psid": "new_psid", "psidts": "new_psidts"}
        ```
        """
        pool: ClientPool = request.app.state.pool
        
        if not pool:
            raise HTTPException(status_code=503, detail="Пул не инициализирован")
        
        timeout = int(os.getenv("GEMINI_TIMEOUT", "120"))
        auto_refresh = os.getenv("GEMINI_AUTO_REFRESH", "true").lower() == "true"
        refresh_interval = int(os.getenv("GEMINI_REFRESH_INTERVAL", "540"))
        
        if reload_request.account_id:
            # Перезагрузить один аккаунт
            success = await pool.reload_account(
                account_id=reload_request.account_id,
                new_psid=reload_request.psid,
                new_psidts=reload_request.psidts,
                timeout=timeout,
                auto_refresh=auto_refresh,
                refresh_interval=refresh_interval,
            )
            return {
                "action": "reload_single",
                "account_id": reload_request.account_id,
                "success": success,
            }
        else:
            # Перезагрузить все из конфига
            accounts_file = os.getenv("GEMINI_ACCOUNTS_FILE")
            if not accounts_file:
                raise HTTPException(
                    status_code=400, 
                    detail="GEMINI_ACCOUNTS_FILE не задан. Укажите account_id для перезагрузки конкретного аккаунта."
                )
            
            results = await pool.reload_all_from_config(
                config_path=accounts_file,
                timeout=timeout,
                auto_refresh=auto_refresh,
                refresh_interval=refresh_interval,
            )
            return {
                "action": "reload_all",
                "results": results,
                "summary": {
                    "total": len(results),
                    "success": sum(1 for v in results.values() if v),
                    "failed": sum(1 for v in results.values() if not v),
                }
            }

    # Запуск сервера
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )


# ============================================
# Main Entry Point
# ============================================
if __name__ == "__main__":
    mode = os.getenv("MODE", "cli").lower()
    
    if mode == "api":
        print("🚀 Запуск в API режиме...")
        run_api()
    else:
        print("🚀 Запуск в CLI режиме...")
        asyncio.run(run_cli())
