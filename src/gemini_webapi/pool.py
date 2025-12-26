# src/gemini_webapi/pool.py
"""
Multi-Account Client Pool для Gemini API.
Поддерживает Round-Robin балансировку с Fallback при ошибках.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .client import GeminiClient
from .exceptions import AuthError, GeminiError, UsageLimitExceeded
from .types import ModelOutput
from .utils import logger


@dataclass
class AccountConfig:
    """Конфигурация одного аккаунта."""
    id: str
    name: str
    psid: str
    psidts: Optional[str] = None
    proxy: Optional[str] = None


@dataclass
class AccountState:
    """Состояние аккаунта в пуле."""
    config: AccountConfig
    client: Optional[GeminiClient] = None
    healthy: bool = True
    consecutive_failures: int = 0
    unhealthy_until: Optional[datetime] = None
    requests_served: int = 0
    last_used: Optional[datetime] = None
    last_error: Optional[str] = None
    
    @property
    def is_available(self) -> bool:
        """Проверяет, доступен ли аккаунт для использования."""
        if not self.healthy:
            if self.unhealthy_until and datetime.now() >= self.unhealthy_until:
                # Cooldown прошёл, восстанавливаем
                self.healthy = True
                self.consecutive_failures = 0
                self.unhealthy_until = None
                logger.info(f"Account '{self.config.id}' recovered after cooldown")
                return True
            return False
        return True
    
    def to_dict(self) -> dict:
        """Сериализация для API ответа."""
        return {
            "id": self.config.id,
            "name": self.config.name,
            "status": "healthy" if self.healthy else "unhealthy",
            "requests_served": self.requests_served,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "last_error": self.last_error,
            "unhealthy_until": self.unhealthy_until.isoformat() if self.unhealthy_until else None,
        }


@dataclass
class PoolSettings:
    """Настройки пула."""
    unhealthy_cooldown_seconds: int = 300
    max_consecutive_failures: int = 3


class ClientPool:
    """
    Пул клиентов Gemini с Round-Robin балансировкой и Fallback.
    
    Использование:
        pool = ClientPool()
        await pool.load_config("/path/to/accounts.json")
        await pool.init_all()
        
        response = await pool.execute(prompt="Hello", model="gemini-3.0-pro")
    """
    
    def __init__(self):
        self.accounts: dict[str, AccountState] = {}
        self.settings = PoolSettings()
        self._current_index: int = 0
        self._lock = asyncio.Lock()
        self._account_order: list[str] = []  # Для round-robin
        self._state_dir: Optional[Path] = None
    
    def load_config(self, config_path: str | Path) -> None:
        """Загружает конфигурацию аккаунтов из JSON файла."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Accounts config not found: {path}")
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Загрузка настроек
        if settings := data.get("settings"):
            self.settings = PoolSettings(
                unhealthy_cooldown_seconds=settings.get("unhealthy_cooldown_seconds", 300),
                max_consecutive_failures=settings.get("max_consecutive_failures", 3),
            )
        
        # Загрузка аккаунтов
        for acc_data in data.get("accounts", []):
            config = AccountConfig(
                id=acc_data["id"],
                name=acc_data.get("name", acc_data["id"]),
                psid=acc_data["psid"],
                psidts=acc_data.get("psidts"),
                proxy=acc_data.get("proxy"),
            )
            self.accounts[config.id] = AccountState(config=config)
            self._account_order.append(config.id)
        
        logger.info(f"Loaded {len(self.accounts)} accounts from config")
    
    def add_account_from_env(self, psid: str, psidts: Optional[str] = None, 
                              proxy: Optional[str] = None) -> None:
        """Добавляет аккаунт из ENV переменных (обратная совместимость)."""
        config = AccountConfig(
            id="default",
            name="Default Account (from ENV)",
            psid=psid,
            psidts=psidts,
            proxy=proxy,
        )
        self.accounts["default"] = AccountState(config=config)
        self._account_order.append("default")
        logger.info("Added default account from ENV variables")
    
    async def init_all(
        self,
        timeout: float = 120,
        auto_refresh: bool = True,
        refresh_interval: float = 540,
    ) -> None:
        """Инициализирует все клиенты в пуле."""
        init_tasks = []
        
        for account_id, state in self.accounts.items():
            client = GeminiClient(
                secure_1psid=state.config.psid,
                secure_1psidts=state.config.psidts,
                proxy=state.config.proxy,
            )
            state.client = client
            
            async def init_client(acc_id: str, c: GeminiClient):
                try:
                    await c.init(
                        timeout=timeout,
                        auto_close=False,
                        auto_refresh=auto_refresh,
                        refresh_interval=refresh_interval,
                        verbose=False,
                    )
                    logger.success(f"Account '{acc_id}' initialized successfully")
                except Exception as e:
                    logger.error(f"Failed to initialize account '{acc_id}': {e}")
                    self.accounts[acc_id].healthy = False
                    self.accounts[acc_id].last_error = str(e)
            
            init_tasks.append(init_client(account_id, client))
        
        await asyncio.gather(*init_tasks)
        
        healthy_count = sum(1 for s in self.accounts.values() if s.healthy)
        logger.info(f"Pool initialized: {healthy_count}/{len(self.accounts)} accounts healthy")
    
    async def close_all(self) -> None:
        """Закрывает все клиенты."""
        for state in self.accounts.values():
            if state.client:
                await state.client.close()
        logger.info("All clients closed")
    
    def _get_next_healthy(self) -> Optional[AccountState]:
        """Возвращает следующий здоровый аккаунт (Round-Robin)."""
        if not self._account_order:
            return None
        
        # Пробуем найти здоровый аккаунт начиная с текущего индекса
        for _ in range(len(self._account_order)):
            account_id = self._account_order[self._current_index]
            self._current_index = (self._current_index + 1) % len(self._account_order)
            
            state = self.accounts[account_id]
            if state.is_available and state.client and state.client._running:
                return state
        
        return None
    
    def _get_by_id(self, account_id: str) -> Optional[AccountState]:
        """Возвращает аккаунт по ID."""
        return self.accounts.get(account_id)
    
    def _mark_unhealthy(self, state: AccountState, error: Exception) -> None:
        """Помечает аккаунт как нездоровый."""
        state.consecutive_failures += 1
        state.last_error = f"{type(error).__name__}: {str(error)}"
        
        if state.consecutive_failures >= self.settings.max_consecutive_failures:
            state.healthy = False
            state.unhealthy_until = datetime.now() + timedelta(
                seconds=self.settings.unhealthy_cooldown_seconds
            )
            logger.warning(
                f"Account '{state.config.id}' marked unhealthy until "
                f"{state.unhealthy_until.isoformat()} after {state.consecutive_failures} failures"
            )
    
    def _mark_success(self, state: AccountState) -> None:
        """Сбрасывает счётчик ошибок при успехе."""
        state.consecutive_failures = 0
        state.requests_served += 1
        state.last_used = datetime.now()
    
    async def execute(
        self,
        prompt: str,
        account_id: Optional[str] = None,
        **kwargs,
    ) -> ModelOutput:
        """
        Выполняет запрос с Round-Robin балансировкой и Fallback.
        
        Args:
            prompt: Текст запроса
            account_id: Явный выбор аккаунта (опционально)
            **kwargs: Дополнительные параметры для generate_content
            
        Returns:
            ModelOutput от Gemini
            
        Raises:
            GeminiError: Если все аккаунты недоступны
        """
        async with self._lock:
            # Явный выбор аккаунта
            if account_id:
                state = self._get_by_id(account_id)
                if not state:
                    raise GeminiError(f"Account '{account_id}' not found")
                if not state.is_available:
                    raise GeminiError(
                        f"Account '{account_id}' is unhealthy until "
                        f"{state.unhealthy_until.isoformat() if state.unhealthy_until else 'unknown'}"
                    )
                if not state.client or not state.client._running:
                    raise GeminiError(f"Account '{account_id}' client is not running")
                
                # Без fallback при явном выборе
                try:
                    result = await state.client.generate_content(prompt=prompt, **kwargs)
                    self._mark_success(state)
                    return result
                except Exception as e:
                    self._mark_unhealthy(state, e)
                    raise
            
            # Round-Robin с Fallback
            tried_accounts: set[str] = set()
            last_error: Optional[Exception] = None
            
            while len(tried_accounts) < len(self.accounts):
                state = self._get_next_healthy()
                
                if not state:
                    break
                
                if state.config.id in tried_accounts:
                    continue
                
                tried_accounts.add(state.config.id)
                
                try:
                    logger.debug(f"Trying account '{state.config.id}'...")
                    result = await state.client.generate_content(prompt=prompt, **kwargs)
                    self._mark_success(state)
                    logger.debug(f"Account '{state.config.id}' succeeded")
                    return result
                    
                except (UsageLimitExceeded, AuthError) as e:
                    # Критические ошибки — помечаем unhealthy и пробуем следующий
                    logger.warning(f"Account '{state.config.id}' failed: {e}")
                    self._mark_unhealthy(state, e)
                    last_error = e
                    continue
                    
                except Exception as e:
                    # Прочие ошибки — инкремент счётчика, пробуем следующий
                    logger.warning(f"Account '{state.config.id}' error: {e}")
                    state.consecutive_failures += 1
                    state.last_error = str(e)
                    last_error = e
                    continue
            
            # Все аккаунты перепробованы
            raise GeminiError(
                f"All accounts exhausted. Last error: {last_error}"
            )
    
    def get_health_status(self) -> dict[str, Any]:
        """Возвращает статус здоровья пула для API."""
        healthy = sum(1 for s in self.accounts.values() if s.is_available)
        return {
            "total": len(self.accounts),
            "healthy": healthy,
            "unhealthy": len(self.accounts) - healthy,
            "accounts": [state.to_dict() for state in self.accounts.values()],
        }
