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
    from gemini_webapi import GeminiClient, set_log_level
    from contextlib import asynccontextmanager
    
    # Модели запросов/ответов
    class AskRequest(BaseModel):
        prompt: str = Field(..., min_length=1, description="Текст запроса к Gemini")
        model: Optional[str] = Field(None, description="Модель (gemini-2.5-flash, gemini-2.5-pro и т.д.)")
        
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
        """Инициализация и закрытие клиента"""
        # Startup
        log_level = os.getenv("LOG_LEVEL", "INFO")
        set_log_level(log_level)
        
        psid = os.getenv("GEMINI_PSID")
        psidts = os.getenv("GEMINI_PSIDTS")
        proxy = os.getenv("GEMINI_PROXY")
        
        if not psid:
            raise RuntimeError("GEMINI_PSID не установлен в переменных окружения!")
        
        # Используем app.state вместо глобальной переменной
        app.state.gemini_client = GeminiClient(
            secure_1psid=psid,
            secure_1psidts=psidts,
            proxy=proxy
        )
        
        timeout = int(os.getenv("GEMINI_TIMEOUT", "30"))
        auto_refresh = os.getenv("GEMINI_AUTO_REFRESH", "true").lower() == "true"
        refresh_interval = int(os.getenv("GEMINI_REFRESH_INTERVAL", "540"))
        
        await app.state.gemini_client.init(
            timeout=timeout,
            auto_close=False,
            auto_refresh=auto_refresh,
            refresh_interval=refresh_interval,
            verbose=True
        )
        
        print("✅ FastAPI сервер запущен, Gemini клиент инициализирован")
        
        yield
        
        # Shutdown
        if hasattr(app.state, 'gemini_client') and app.state.gemini_client:
            await app.state.gemini_client.close()
            print("✅ Gemini клиент закрыт")
    
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
        # Используем app.state вместо global
        gemini_client = request.app.state.gemini_client
        
        # Детальная проверка состояния клиента
        print(f"🔍 Проверка клиента:")
        print(f"   gemini_client is None: {gemini_client is None}")
        if gemini_client:
            print(f"   gemini_client._running: {gemini_client._running}")
        
        if not gemini_client:
            print(f"❌ Клиент = None")
            raise HTTPException(status_code=503, detail="Gemini клиент не инициализирован")
        
        if not gemini_client._running:
            print(f"❌ Клиент не в режиме running")
            raise HTTPException(status_code=503, detail="Gemini клиент не активен")
        
        try:
            print(f"📤 Отправка запроса в Gemini: {ask_request.prompt[:50]}...")
            
            # Отправка запроса
            kwargs = {}
            if ask_request.model:
                kwargs["model"] = ask_request.model
            
            response = await gemini_client.generate_content(
                prompt=ask_request.prompt,
                **kwargs
            )
            
            # Сохранение и обработка изображений
            image_urls = []
            if response.images:
                print(f"🎨 Сгенерировано изображений: {len(response.images)}")
                
                # Создаем директорию для статики если нет
                static_dir = Path("static/images")
                static_dir.mkdir(parents=True, exist_ok=True)
                
                for i, img in enumerate(response.images):
                    try:
                        # Сохраняем изображение локально
                        # Используем save() который под капотом использует куки клиента
                        saved_path = await img.save(
                            path="static/images",
                            skip_invalid_filename=False,
                            verbose=True
                        )
                        
                        if saved_path:
                            # Формируем публичный URL
                            filename = Path(saved_path).name
                            # Используем базовый URL из запроса или относительный путь
                            # В продакшене лучше использовать полный URL
                            public_url = f"{request.base_url}static/images/{filename}"
                            image_urls.append(public_url)
                            print(f"   🖼️ Image {i+1} saved: {public_url}")
                        else:
                            # Fallback на оригинальный URL если не удалось сохранить
                            image_urls.append(img.url)
                            
                    except Exception as img_err:
                        print(f"⚠️ Ошибка при сохранении изображения {i}: {img_err}")
                        image_urls.append(img.url)
            
            # Формирование ответа
            return AskResponse(
                text=response.text,
                thoughts=response.thoughts,
                images=image_urls,
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
        gemini_client = request.app.state.gemini_client
        
        if gemini_client and gemini_client._running:
            return HealthResponse(
                status="healthy",
                message="Gemini API работает нормально"
            )
        return HealthResponse(
            status="unhealthy",
            message="Gemini клиент не активен"
        )
    
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
