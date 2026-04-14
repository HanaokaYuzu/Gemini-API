import asyncio
from datetime import datetime, timezone
import codecs
import io
import random
import time
import secrets
import uuid
from asyncio import Task
from pathlib import Path
from textwrap import shorten
from typing import Any, AsyncGenerator, Iterator, Optional

import orjson as json
from curl_cffi.requests import AsyncSession, Cookies, Response
from curl_cffi.requests.exceptions import ReadTimeout

from .components import ChatMixin, GemMixin, ResearchMixin
from .constants import (
    AccountStatus,
    Endpoint,
    ErrorCode,
    GRPC,
    Headers,
    Model,
    TEMPORARY_CHAT_FLAG_INDEX,
    STREAMING_FLAG_INDEX,
    GEM_FLAG_INDEX,
    CARD_CONTENT_RE,
    ARTIFACTS_RE,
    DEFAULT_METADATA,
    MODEL_HEADER_KEY,
    GEMINI_FLASH_QUOTA_PAYLOAD,
    GEMINI_ADVANCED_QUOTA_PAYLOAD,
)
from .exceptions import (
    APIError,
    AuthError,
    GeminiError,
    ModelInvalid,
    TemporarilyBlocked,
    TimeoutError,
    UsageLimitExceeded,
)
from .types import (
    AvailableModel,
    Candidate,
    ChatHistory,
    ChatInfo,
    DeepResearchPlan,
    Gem,
    GeneratedImage,
    GeneratedMedia,
    GeneratedVideo,
    ModelOutput,
    RPCData,
    WebImage,
)
from .utils import (
    extract_deep_research_plan,
    extract_json_from_response,
    get_access_token,
    get_delta_by_fp_len,
    get_nested_value,
    parse_file_name,
    parse_response_by_frame,
    rotate_1psidts,
    running,
    save_cookies,
    upload_file,
    logger,
)


class GeminiClient(ChatMixin, GemMixin, ResearchMixin):
    """
    Async requests client interface for gemini.google.com.

    `secure_1psid` must be provided unless the optional dependency `browser-cookie3` is installed, and
    you have logged in to google.com in your local browser.

    Parameters
    ----------
    secure_1psid: `str`, optional
        __Secure-1PSID cookie value.
    secure_1psidts: `str`, optional
        __Secure-1PSIDTS cookie value, some Google accounts don't require this value, provide only if it's in the cookie list.
    proxy: `str`, optional
        Proxy URL.
    kwargs: `dict`, optional
        Additional arguments which will be passed to the http client.
        Refer to `curl_cffi.requests.AsyncSession` for more information.

    Raises
    ------
    `ValueError`
        If `browser-cookie3` is installed but cookies for google.com are not found in your local browser storage.
    """

    __slots__ = [
        "proxy",
        "client",
        "access_token",
        "build_label",
        "session_id",
        "language",
        "push_id",
        "account_status",
        "timeout",
        "auto_close",
        "close_delay",
        "close_task",
        "auto_refresh",
        "refresh_interval",
        "refresh_task",
        "ping_task",
        "watchdog_timeout",
        "impersonate",
        "verbose",
        "last_activity_time",
        "activity_task",
        "_running",
        "_cookies",
        "_reqid",
        "_model_registry",
        "_lock",
        "_recent_chats",  # From ChatMixin
        "_gems",  # From GemMixin
        "_quotas",
        "_abuse_status",
        "kwargs",
    ]

    def __init__(
        self,
        secure_1psid: str | None = None,
        secure_1psidts: str | None = None,
        proxy: str | None = None,
        **kwargs,
    ):
        super().__init__()
        self.proxy = proxy
        self.client: AsyncSession | None = None
        self.access_token: str | None = None
        self.build_label: str | None = None
        self.session_id: str | None = None
        self.language: str | None = None
        self.push_id: str | None = None
        self.account_status: AccountStatus = AccountStatus.AVAILABLE
        self.timeout: float = 450
        self.auto_close: bool = False
        self.close_delay: float = 450
        self.close_task: Task | None = None
        self.auto_refresh: bool = True
        self.refresh_interval: float = 600
        self.refresh_task: Task | None = None
        self.ping_task: Task | None = None
        self.watchdog_timeout: float = 120  # seconds before declaring a zombie stream
        self.impersonate: str = "chrome"
        self.verbose: bool = False
        self._abuse_status: dict | None = None
        self.last_activity_time: float = 0
        self.activity_task: Task | None = None
        self._running: bool = False
        self._cookies = Cookies()
        self._reqid: int = random.randint(10000, 99999)
        self._model_registry: dict[str, AvailableModel] = {}
        self._lock = asyncio.Lock()
        self._quotas: dict[str, dict] = {}
        self.kwargs = kwargs

        if secure_1psid:
            self._cookies.set("__Secure-1PSID", secure_1psid, domain=".google.com")
            if secure_1psidts:
                self._cookies.set(
                    "__Secure-1PSIDTS", secure_1psidts, domain=".google.com"
                )

    @property
    def quotas(self) -> dict[str, dict]:
        """
        Get the current account quotas/limits.
        """
        return self._quotas

    @property
    def abuse_status(self) -> dict | None:
        """
        Get the current account abuse status and flags.
        """

        return self._abuse_status

    @property
    def cookies(self) -> Cookies:
        """
        Returns the cookies used for the current session.
        """

        return self.client.cookies if self.client else self._cookies

    @cookies.setter
    def cookies(self, value: Cookies | dict):
        """
        Set the cookies to use for the session.
        """

        if isinstance(value, Cookies):
            self._cookies.update(value)
        elif isinstance(value, dict):
            for k, v in value.items():
                self._cookies.set(k, v, domain=".google.com")

        if self.client:
            self.client.cookies.update(self._cookies)

    async def init(
        self,
        timeout: float = 450,
        auto_close: bool = False,
        close_delay: float = 450,
        auto_refresh: bool = True,
        refresh_interval: float = 600,
        watchdog_timeout: float = 120,
        impersonate: str = "chrome",
        verbose: bool = False,
    ) -> None:
        """
        Get SNlM0e value as access token. Without this token posting will fail with 400 bad request.

        Parameters
        ----------
        timeout: `float`, optional
            Request timeout of the client in seconds. Used to limit the max waiting time when sending a request.
        auto_close: `bool`, optional
            If `True`, the client will close connections and clear resource usage after a certain period
            of inactivity. Useful for always-on services.
        close_delay: `float`, optional
            Time to wait before auto-closing the client in seconds. Effective only if `auto_close` is `True`.
        auto_refresh: `bool`, optional
            If `True`, will schedule tasks to automatically refresh cookies and tokens and maintain connection.
        refresh_interval: `float`, optional
            Time interval for background cookie and access token refresh in seconds.
            Effective only if `auto_refresh` is `True`.
        watchdog_timeout: `float`, optional
            Timeout in seconds for shadow retry watchdog. If no data receives from stream but connection is active,
            client will retry automatically after this duration.
        impersonate: `str`, optional
            Allow to customize client, default to chrome.
        verbose: `bool`, optional
            If `True`, will print more infomation in logs.
        """

        async with self._lock:
            if self._running:
                return

            try:
                self.verbose = verbose
                self.watchdog_timeout = watchdog_timeout
                self.impersonate = impersonate
                (
                    access_token,
                    build_label,
                    session_id,
                    language,
                    push_id,
                    session,
                ) = await get_access_token(
                    base_cookies=self.cookies,
                    proxy=self.proxy,
                    verbose=self.verbose,
                    impersonate=impersonate,
                    verify=self.kwargs.get("verify", True),
                )

                session.timeout = timeout
                self.client = session
                self._cookies.update(self.client.cookies)
                self.access_token = access_token
                self.build_label = build_label
                self.session_id = session_id
                self.language = language or "en"
                self.push_id = push_id or "feeds/mcudyrk2a4khkz"
                self._running = True
                self._reqid = random.randint(10000, 99999)

                self.timeout = timeout
                self.auto_close = auto_close
                self.close_delay = close_delay
                if self.auto_close:
                    await self.reset_close_task()

                self.auto_refresh = auto_refresh
                self.refresh_interval = refresh_interval

                await self._init_rpc()

                if self.refresh_task:
                    self.refresh_task.cancel()
                    self.refresh_task = None

                if self.auto_refresh and self._check_account_status():
                    self.refresh_task = asyncio.create_task(self.start_auto_refresh())

                if self.activity_task:
                    self.activity_task.cancel()
                    self.activity_task = None

                if self.auto_refresh and self._check_account_status():
                    self.activity_task = asyncio.create_task(
                        self.start_activity_watchdog()
                    )

                if self.ping_task:
                    self.ping_task.cancel()
                    self.ping_task = None

                if self.auto_refresh:
                    self.ping_task = asyncio.create_task(self.start_http2_ping())

                logger.success("Gemini client initialized successfully.")
            except Exception:
                await self.close()
                raise

    async def close(self, delay: float = 0) -> None:
        """
        Close the client and save cookies.

        Parameters
        ----------
        delay: `float`, optional
            Time to wait before closing the client in seconds.
        """

        if delay:
            await asyncio.sleep(delay)

        self._running = False

        if self.close_task:
            self.close_task.cancel()
            self.close_task = None

        if self.refresh_task:
            self.refresh_task.cancel()
            self.refresh_task = None

        if self.activity_task:
            self.activity_task.cancel()
            self.activity_task = None

        if self.ping_task:
            self.ping_task.cancel()
            self.ping_task = None

        if self.client:
            self._cookies.update(self.client.cookies)
            await self.client.close()
            self.client = None

        try:
            save_cookies(self._cookies, self.verbose)
        except OSError as e:
            logger.warning(f"Failed to save cookies to cache file: {e}")

    async def reset_close_task(self) -> None:
        """
        Reset the timer for closing the client when a new request is made.
        """

        if self.close_task:
            self.close_task.cancel()
            self.close_task = None

        self.close_task = asyncio.create_task(self.close(self.close_delay))

    async def start_activity_watchdog(self) -> None:
        """
        Start the background task to ensure periodic activity calls.
        """

        while self._running:
            interval = random.uniform(60, 300)
            while self._running:
                elapsed = time.time() - self.last_activity_time
                remaining = interval - elapsed
                if remaining <= 0:
                    break
                await asyncio.sleep(min(remaining, 10))

            if not self._running:
                break

            try:
                logger.debug(
                    f"Heartbeat triggered. Time since last activity: {int(time.time() - self.last_activity_time)}s"
                )
                await self._sync_activity()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Unexpected error in activity watchdog: {e}")

    async def start_auto_refresh(self) -> None:
        """
        Start the background task to automatically refresh cookies with random jitter.

        Adds ±15 seconds of random jitter to the refresh interval to prevent synchronized
        background tasks. The final interval is clamped to a minimum of 60 seconds.
        """

        self.refresh_interval = max(self.refresh_interval, 60)

        while self._running:
            jitter = random.uniform(-15, 15)
            await asyncio.sleep(max(60, self.refresh_interval + jitter))

            if not self._running:
                break

            try:
                async with self._lock:
                    # Refresh all cookies in the background to keep the session alive.
                    new_1psidts = await rotate_1psidts(self.client, self.verbose)

                    if not new_1psidts:
                        logger.warning(
                            "Rotation response did not contain a __Secure-1PSIDTS. "
                            "The current cookies may have been invalidated by the server. "
                            "Retrying in next interval."
                        )
            except asyncio.CancelledError:
                raise
            except AuthError:
                logger.warning(
                    "AuthError: Failed to refresh cookies. "
                    "The current cookies may have been invalidated by the server. "
                    "Retrying in next interval."
                )
            except Exception as e:
                logger.warning(
                    f"Unexpected error while refreshing cookies: {e}. Retrying in next interval."
                )

    async def start_http2_ping(self) -> None:
        """
        Start the background task to periodically send HTTP/2 PING frames.

        Uses the native upkeep mechanism to maintain connection health.
        Iterates every 45 seconds with ±5 seconds of random jitter.
        """

        while self._running:
            interval = random.uniform(40, 50)
            await asyncio.sleep(interval)

            if not self._running:
                break

            try:
                if self.client:
                    if hasattr(self.client, "upkeep"):
                        self.client.upkeep()
                    else:
                        curl = await self.client.pop_curl()
                        try:
                            curl.upkeep()
                        finally:
                            self.client.push_curl(curl)

                    if self.verbose:
                        logger.debug("HTTP/2 PING frame (upkeep) sent.")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Unexpected error in HTTP/2 ping task: {e}")

    def _parse_rpc_results(self, response_text: str, target_id: str) -> Iterator[Any]:
        """
        Extract parts from a batch response and yield only those matching the target RPC ID.
        """
        try:
            response_json = extract_json_from_response(response_text)
            for part in response_json:
                if get_nested_value(part, [1]) != target_id:
                    continue

                # Check for server-side rejection (e.g., code 7 for permission denied)
                reject_code = get_nested_value(part, [5, 0])
                if reject_code == 7:
                    logger.warning(
                        f"RPC request {target_id} failed: Permission denied or unauthenticated."
                    )
                    continue

                part_body_str = get_nested_value(part, [2])
                if not part_body_str:
                    continue

                try:
                    yield json.loads(part_body_str)
                except (json.JSONDecodeError, TypeError):
                    continue
        except Exception as e:
            if self.verbose:
                logger.debug(f"Failed to extract JSON from response: {e}")

    async def _init_rpc(self) -> None:
        """
        Send initial RPC calls to set up the session.
        """

        await self._fetch_user_status()
        await self._fetch_preferences()
        await self._sync_activity()
        await self._fetch_recent_chats()
        await self._fetch_quota()
        await self._fetch_extra_quota()
        await self._fetch_abuse_status()

    async def _fetch_user_status(self) -> None:
        """
        Fetch user status and parse available models dynamically from the Gemini API.

        Builds :class:`AvailableModel` instances from the RPC response so that
        model headers are always up-to-date without hardcoded values.
        """

        response = await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.GET_USER_STATUS,
                    payload="[]",
                )
            ]
        )

        for part_body in self._parse_rpc_results(response.text, GRPC.GET_USER_STATUS):
            status_code = get_nested_value(part_body, [14])
            self.account_status = AccountStatus.from_status_code(status_code)

            if self.account_status == AccountStatus.AVAILABLE:
                if self.verbose:
                    logger.info(
                        f"Account status: {self.account_status.name} - {self.account_status.description}"
                    )
            else:
                logger.warning(
                    f"Account status: {self.account_status.name} - {self.account_status.description}"
                )
                if self.account_status in [
                    AccountStatus.LOCATION_REJECTED,
                    AccountStatus.ACCOUNT_REJECTED,
                    AccountStatus.ACCESS_TEMPORARILY_UNAVAILABLE,
                    AccountStatus.ACCOUNT_REJECTED_BY_GUARDIAN,
                    AccountStatus.GUARDIAN_APPROVAL_REQUIRED,
                ]:
                    logger.warning(
                        f"Hard block detected ({self.account_status.name}). Skipping model discovery."
                    )
                    continue

            models_list = get_nested_value(part_body, [15])
            if isinstance(models_list, list):
                tier_flags = get_nested_value(part_body, [16], [])
                tier_flags = tier_flags if isinstance(tier_flags, list) else []
                capability_flags = get_nested_value(part_body, [17], [])
                capability_flags = (
                    capability_flags if isinstance(capability_flags, list) else []
                )
                capacity, capacity_field = AvailableModel.compute_capacity(
                    tier_flags, capability_flags
                )

                id_name_mapping = AvailableModel.build_model_id_name_mapping()

                for model_data in models_list:
                    if isinstance(model_data, list):
                        model_id = get_nested_value(model_data, [0], "")
                        display_name = get_nested_value(model_data, [1], "")
                        description = get_nested_value(model_data, [2], "")

                        if model_id and display_name:
                            is_model_available = True
                            if self.account_status == AccountStatus.UNAUTHENTICATED:
                                if model_id != Model.BASIC_FLASH.model_id:
                                    is_model_available = False

                            model = AvailableModel(
                                model_id=model_id,
                                model_name=id_name_mapping.get(model_id, ""),
                                display_name=display_name,
                                description=description,
                                capacity=capacity,
                                capacity_field=capacity_field,
                                is_available=is_model_available,
                            )
                            self._model_registry[model_id] = model

                return

    async def _fetch_quota(
        self,
        flash: bool = False,
        advanced: bool = False,
    ) -> None:
        """
        Fetch quota limits for Gemini models.
        Supports semantic selection of quota tiers.

        Parameters
        ----------
        flash: `bool`, optional
            If True, fetches limits for Gemini Flash models.
        advanced: `bool`, optional
            If True, fetches limits for Gemini Pro and Flash Thinking models.
        """

        if not self._check_account_status():
            return

        if not any([flash, advanced]):
            flash = True
            advanced = True
        to_fetch: list[tuple[str, str]] = []
        if flash:
            to_fetch.append((GEMINI_FLASH_QUOTA_PAYLOAD, "Flash"))
        if advanced:
            to_fetch.append((GEMINI_ADVANCED_QUOTA_PAYLOAD, "Thinking/Pro"))

        for payload_str, category in to_fetch:
            try:
                response = await self._batch_execute(
                    [
                        RPCData(
                            rpcid=GRPC.CHECK_GEMINI_QUOTA,
                            payload=payload_str,
                        )
                    ]
                )

                for part_body in self._parse_rpc_results(
                    response.text, GRPC.CHECK_GEMINI_QUOTA
                ):
                    quota_items = get_nested_value(part_body, [0])

                    if not isinstance(quota_items, list):
                        continue

                    for item in quota_items:
                        quota_id_list = get_nested_value(item, [0], [])
                        action_id = get_nested_value(item, [0, 1])
                        usage_level = get_nested_value(item, [2])
                        reset_ts = get_nested_value(item, [3, 0])
                        total = get_nested_value(item, [4])
                        remaining = get_nested_value(item, [5])

                        quota_id = "-".join(map(str, quota_id_list))

                        action_labels = {
                            4: "Gemini Pro",
                            11: "Gemini Flash",
                            15: "Gemini Flash Thinking",
                        }
                        label = action_labels.get(action_id, f"Gemini {category}")
                        display_target = f"{label} [{quota_id}]"

                        quota_data = {
                            "usage_percentage": usage_level,
                            "reset_time": reset_ts,
                            "total": total,
                            "remaining": remaining,
                            "action_id": action_id,
                            "label": display_target,
                        }

                        self._quotas[quota_id] = quota_data

                        if isinstance(usage_level, (int, float)):
                            reset_str = ""
                            if reset_ts:
                                try:
                                    reset_dt = datetime.fromtimestamp(
                                        reset_ts, tz=timezone.utc
                                    ).astimezone()
                                    reset_str = f" (Resets: {reset_dt.strftime('%Y-%m-%d %H:%M:%S %Z')})"
                                except (ValueError, OSError, OverflowError):
                                    reset_str = f" (Resets at timestamp: {reset_ts})"

                            quota_display = (
                                "Unlimited"
                                if (total == 0 and remaining == 0)
                                else f"{remaining}/{total} remaining"
                            )
                            logger.info(
                                f"Account quota updated: {display_target} - {quota_display}{reset_str}"
                            )

                            if usage_percentage := usage_level:
                                if usage_percentage >= 100:
                                    logger.error(
                                        f"Account quota EXHAUSTED for {display_target}: {quota_display}.{reset_str}"
                                    )
                                elif usage_percentage >= 90:
                                    logger.warning(
                                        f"Account quota critical: Usage is at {usage_percentage:.1f}% for {display_target} ({quota_display}).{reset_str}"
                                    )
                                elif usage_percentage >= 75:
                                    logger.warning(
                                        f"Account quota warning: Usage is at {usage_percentage:.1f}% for {display_target} ({quota_display}).{reset_str}"
                                    )

            except Exception as e:
                logger.error(
                    f"Failed to fetch quota for payload {shorten(payload_str, width=60)}: {e}"
                )
                continue

    async def _fetch_abuse_status(self) -> None:
        """
        Check for account abuse markers and signals.
        """

        response = await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.GET_ABUSE_STATUS,
                    payload="[]",
                )
            ]
        )

        for part_body in self._parse_rpc_results(response.text, GRPC.GET_ABUSE_STATUS):
            abuse_info = get_nested_value(part_body, [1])

            if not abuse_info:
                self._abuse_status = {
                    "is_clean": True,
                    "status_code": None,
                    "signal": None,
                }
                logger.info("Account abuse status: Clean (No flags detected).")
                continue

            raw_status = get_nested_value(abuse_info, [1])
            signal = get_nested_value(abuse_info, [3, 1])

            status_code = (
                int(raw_status) // 1_000_000 if raw_status is not None else None
            )

            self._abuse_status = {
                "is_clean": False,
                "status_code": status_code,
                "signal": signal,
            }

            logger.warning(
                f"Potential account restriction or abnormal status detected: {self._abuse_status}"
            )

    async def _fetch_extra_quota(self) -> None:
        """
        Check additional feature quotas and capability caps.

        Note: This method does not pre-verify account status with _check_account_status
        and relies on internal rejection code handling (e.g., code 7).
        """

        response = await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.CHECK_QUOTA,
                    payload="[]",
                )
            ]
        )

        for part_body in self._parse_rpc_results(response.text, GRPC.CHECK_QUOTA):
            is_blocked = get_nested_value(part_body, [0])
            usage_level = get_nested_value(part_body, [1])
            reset_ts = get_nested_value(part_body, [2, 0])

            if "extra" not in self._quotas:
                self._quotas["extra"] = {}
            self._quotas["extra"]["default"] = {
                "is_blocked": is_blocked,
                "usage_percentage": usage_level * 100
                if isinstance(usage_level, (int, float))
                else None,
                "reset_time": reset_ts,
            }

            if is_blocked:
                reset_str = (
                    f" (Resets: {datetime.fromtimestamp(reset_ts).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')})"
                    if reset_ts
                    else ""
                )
                logger.error(
                    f"Extra feature quota exceeded: Hard block detected.{reset_str}"
                )
            elif isinstance(usage_level, (int, float)):
                usage_pc = usage_level * 100
                reset_str = (
                    f" (Resets: {datetime.fromtimestamp(reset_ts).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')})"
                    if reset_ts
                    else ""
                )
                if usage_pc >= 90:
                    logger.warning(
                        f"Extra feature quota critical: Usage is at {usage_pc:.1f}%.{reset_str}"
                    )
                elif usage_pc >= 75:
                    logger.warning(
                        f"Extra feature quota warning: Usage is at {usage_pc:.1f}%.{reset_str}"
                    )

            if self.verbose:
                logger.info(
                    f"Extra quota check: Blocked={is_blocked}, UsageLevel={usage_level}"
                )

    async def _fetch_preferences(self) -> None:
        """
        Fetch user preferences and data context flags.
        """

        await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.READ_USER_PREFERENCES,
                    payload='[[["adaptive_device_responses_enabled","advanced_mode_theme_override_triggered","advanced_zs_upsell_dismissal_count","advanced_zs_upsell_last_dismissed","ai_transparency_notice_dismissed","audio_overview_discovery_dismissal_count","audio_overview_discovery_last_dismissed","bard_in_chrome_link_sharing_enabled","bard_sticky_mode_disabled_count","canvas_create_discovery_tooltip_seen_count","combined_files_button_tag_seen_count","indigo_banner_explicit_dismissal_count","indigo_banner_impression_count","indigo_banner_last_seen_sec","current_popup_id","deep_research_has_seen_file_upload_tooltip","deep_research_model_update_disclaimer_display_count","default_bot_id","disabled_discovery_card_feature_ids","disabled_model_discovery_tooltip_feature_ids","disabled_mode_disclaimers","disabled_new_model_badge_mode_ids","disabled_settings_discovery_tooltip_feature_ids","disablement_disclaimer_last_dismissed_sec","disable_advanced_beta_dialog","disable_advanced_beta_non_en_banner","disable_advanced_resubscribe_ui","disable_at_mentions_discovery_tooltip","disable_autorun_fact_check_u18","disable_bot_create_tips_card","disable_bot_docs_in_gems_disclaimer","disable_bot_onboarding_dialog","disable_bot_save_reminder_tips_card","disable_bot_send_prompt_tips_card","disable_bot_shared_in_drive_disclaimer","disable_bot_try_create_tips_card","disable_colab_tooltip","disable_collapsed_tool_menu_tooltip","disable_continue_discovery_tooltip","disable_debug_info_moved_tooltip_v2","disable_enterprise_mode_dialog","disable_export_python_tooltip","disable_extensions_discovery_dialog","disable_extension_one_time_badge","disable_fact_check_tooltip_v2","disable_free_file_upload_tips_card","disable_generated_image_download_dialog","disable_get_app_banner","disable_get_app_desktop_dialog","disable_googler_in_enterprise_mode","disable_human_review_disclosure","disable_ice_open_vega_editor_tooltip","disable_image_upload_tooltip","disable_legal_concern_tooltip","disable_llm_history_import_disclaimer","disable_location_popup","disable_memory_discovery","disable_memory_extraction_discovery","disable_new_conversation_dialog","disable_onboarding_experience","disable_personal_context_tooltip","disable_photos_upload_disclaimer","disable_power_up_intro_tooltip","disable_scheduled_actions_mobile_notification_snackbar","disable_storybook_listen_button_tooltip","disable_streaming_settings_tooltip","disable_take_control_disclaimer","disable_teens_only_english_language_dialog","disable_tier1_rebranding_tooltip","disable_try_advanced_mode_dialog","enable_advanced_beta_mode","enable_advanced_mode","enable_googler_in_enterprise_mode","enable_memory","enable_memory_extraction","enable_personal_context","enable_personal_context_gemini","enable_personal_context_gemini_using_photos","enable_personal_context_gemini_using_workspace","enable_personal_context_search","enable_personal_context_youtube","enable_token_streaming","enforce_default_to_fast_version","mayo_discovery_banner_dismissal_count","mayo_discovery_banner_last_dismissed_sec","gempix_discovery_banner_dismissal_count","gempix_discovery_banner_last_dismissed","get_app_banner_ack_count","get_app_banner_seen_count","get_app_mobile_dialog_ack_count","guided_learning_banner_dismissal_count","guided_learning_banner_last_dismissed","has_accepted_agent_mode_fre_disclaimer","has_received_streaming_response","has_seen_agent_mode_tooltip","has_seen_bespoke_tooltip","has_seen_deepthink_mustard_tooltip","has_seen_deepthink_v2_tooltip","has_seen_deep_think_tooltip","has_seen_first_youtube_video_disclaimer","has_seen_ggo_tooltip","has_seen_image_grams_discovery_banner","has_seen_image_preview_in_input_area_tooltip","has_seen_kallo_discovery_banner","has_seen_kallo_tooltip","has_seen_model_picker_in_input_area_tooltip","has_seen_model_tooltip_in_input_area_for_gempix","has_seen_redo_with_gempix2_tooltip","has_seen_veograms_discovery_banner","has_seen_video_generation_discovery_banner","is_imported_chats_panel_open_by_default","jumpstart_onboarding_dismissal_count","last_dismissed_deep_research_implicit_invite","last_dismissed_discovery_feature_implicit_invites","last_dismissed_immersives_canvas_implicit_invite","last_dismissed_immersive_share_disclaimer_sec","last_dismissed_strike_timestamp_sec","last_dismissed_zs_student_aip_banner_sec","last_get_app_banner_ack_timestamp_sec","last_get_app_mobile_dialog_ack_timestamp_sec","last_human_review_disclosure_ack","last_selected_mode_id_in_embedded","last_selected_mode_id_on_web","last_two_up_activation_timestamp_sec","last_winter_olympics_interaction_timestamp_sec","memory_extracted_greeting_name","mini_gemini_tos_closed","mode_switcher_soft_badge_disabled_ids","mode_switcher_soft_badge_seen_count","personalization_first_party_onboarding_cross_surface_clicked","personalization_first_party_onboarding_cross_surface_seen_count","personalization_one_p_discovery_card_seen_count","personalization_one_p_discovery_last_consented","personalization_zero_state_card_last_interacted","personalization_zero_state_card_seen_count","popup_zs_visits_cooldown","require_reconsent_setting_for_personalization_banner_seen_count","show_debug_info","side_nav_open_by_default","student_verification_dismissal_count","student_verification_last_dismissed","task_viewer_cc_banner_dismissed_count","task_viewer_cc_banner_dismissed_time_sec","tool_menu_new_badge_disabled_ids","tool_menu_new_badge_impression_counts","tool_menu_soft_badge_disabled_ids","tool_menu_soft_badge_impression_counts","upload_disclaimer_last_consent_time_sec","viewed_student_aip_upsell_campaign_ids","voice_language","voice_name","web_and_app_activity_enabled","wellbeing_nudge_notice_last_dismissed_sec","zs_student_aip_banner_dismissal_count"]]]',
                )
            ]
        )

    async def _sync_activity(self) -> None:
        """
        Sync user activity status and maintain session heartbeat.
        """

        self.last_activity_time = time.time()

        if not self._check_account_status():
            return

        await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.READ_USER_PREFERENCES,
                    payload='[[["bard_activity_enabled"]]]',
                )
            ]
        )

    def list_models(self) -> list[AvailableModel] | None:
        """
        List all available models for the current account.
        Model list is only available after GeminiClient.init() is successfully called.

        Returns
        -------
        `list[gemini_webapi.types.AvailableModel] | None`
            List of models with their name and description.
            Returns `None` if the client holds no session cache.
        """

        return list(self._model_registry.values()) if self._model_registry else None

    def _resolve_model_by_name(self, name: str) -> Model | AvailableModel:
        """
        Resolve a model name string to an :class:`AvailableModel` (preferred)
        or fall back to the :class:`Model` enum.
        """

        if name in self._model_registry:
            return self._model_registry[name]

        for m in self._model_registry.values():
            if (
                m.model_name.lower() == name.lower()
                or m.display_name.lower() == name.lower()
            ):
                return m

        return Model.from_name(name)

    def _resolve_enum_model(self, model: Model) -> Model | AvailableModel:
        """
        Try to upgrade a :class:`Model` enum to an :class:`AvailableModel`
        from the dynamic registry.  Falls back to the enum itself if no match
        is found.
        """

        if model is Model.UNSPECIFIED:
            return model

        header_value = model.model_header.get(MODEL_HEADER_KEY, "")
        if not header_value:
            return model

        try:
            parsed = json.loads(header_value)
            model_id = get_nested_value(parsed, [4], "")
            if model_id and model_id in self._model_registry:
                return self._model_registry[model_id]
        except json.JSONDecodeError:
            pass

        return model

    @staticmethod
    def _get_quota_flags(
        model: Model | AvailableModel | str | dict,
    ) -> dict[str, bool]:
        """
        Determine the required quota fetch flags based on the model and task type.

        Parameters
        ----------
        model : `Model` | `AvailableModel` | `str` | `dict`
            The model used for generation.

        Returns
        -------
        `dict[str, bool]`
            A dictionary containing the required flags for _fetch_quota.
        """

        flags = {"flash": False, "advanced": False}

        model_name = ""
        if isinstance(model, (Model, AvailableModel)):
            model_name = model.model_name.lower()
        elif isinstance(model, str):
            model_name = model.lower()
        elif isinstance(model, dict):
            model_name = model.get("model_name", "").lower()

        if not model_name or model_name == "unspecified":
            return {"flash": True, "advanced": True}

        if "thinking" in model_name or "pro" in model_name:
            flags["advanced"] = True
        elif "flash" in model_name:
            flags["flash"] = True
        else:
            flags["flash"] = True
            flags["advanced"] = True

        return flags

    def _check_account_status(self, raise_error: bool = False) -> bool:
        """
        Check if the account is available for higher-level operations.

        Parameters
        ----------
        raise_error: `bool`, optional
            If `True`, raises `GeminiError` if the account is not available (defaults to `False`).
            If `False`, returns a boolean indicating availability.

        Returns
        -------
        `bool`
            `True` if account is AVAILABLE, `False` otherwise.

        Raises
        ------
        GeminiError
            If `raise_error` is `True` and account status is not AccountStatus.AVAILABLE.
        """

        is_available = self.account_status == AccountStatus.AVAILABLE
        if not is_available and raise_error:
            raise GeminiError(
                f"Permission denied. Account status: {self.account_status.name} - {self.account_status.description}"
            )
        return is_available

    async def generate_content(
        self,
        prompt: str,
        files: list[str | Path | bytes | io.BytesIO] | None = None,
        model: Model | AvailableModel | str | dict = Model.UNSPECIFIED,
        gem: Gem | str | None = None,
        chat: Optional["ChatSession"] = None,
        temporary: bool = False,
        deep_research: bool = False,
        **kwargs,
    ) -> ModelOutput:
        """
        Generates contents with prompt.

        Parameters
        ----------
        prompt: `str`
            Text prompt provided by user.
        files: `list[str | Path | bytes | io.BytesIO]`, optional
            List of file paths or byte streams to be attached.
        model: `Model | str | dict`, optional
            Specify the model to use for generation.
            Pass either a `gemini_webapi.constants.Model` enum or a model name string to use predefined models.
            Pass a dictionary to use custom model header strings ("model_name" and "model_header" keys must be provided).
        gem: `Gem | str`, optional
            Specify a gem to use as system prompt for the chat session.
            Pass either a `gemini_webapi.types.Gem` object or a gem id string.
        chat: `ChatSession`, optional
            Chat data to retrieve conversation history.
            If None, will automatically generate a new chat id when sending post request.
        temporary: `bool`, optional
            If set to `True`, the ongoing conversation will not show up in Gemini history.
        deep_research: `bool`, optional
            If set to `True`, will enable deep research mode and start creating a deep research plan.
        kwargs: `dict`, optional
            Additional arguments which will be passed to the post request.
            Refer to `curl_cffi.requests.AsyncSession.request` for more information.

        Returns
        -------
        :class:`ModelOutput`
            Output data from gemini.google.com.

        Raises
        ------
        `AssertionError`
            If prompt is empty.
        `gemini_webapi.TimeoutError`
            If request timed out.
        `gemini_webapi.GeminiError`
            If no reply candidate found in response.
        `gemini_webapi.APIError`
            - If request failed with status code other than 200.
            - If response structure is invalid and failed to parse.
        """

        if self.auto_close:
            await self.reset_close_task()

        if any([files, gem, deep_research]):
            self._check_account_status(raise_error=True)

        file_data = None
        if files:
            await self._sync_activity()

            uploaded_urls = await asyncio.gather(
                *(
                    upload_file(
                        file,
                        client=self.client,
                        push_id=self.push_id,
                        verbose=self.verbose,
                    )
                    for file in files
                )
            )
            file_data = [
                [[url], parse_file_name(file)]
                for url, file in zip(uploaded_urls, files)
            ]

        try:
            await self._sync_activity()

            session_state = {
                "last_texts": {},
                "last_thoughts": {},
                "last_progress_time": time.time(),
                "is_thinking": False,
                "is_queueing": False,
            }
            output = None
            async for output in self._generate(
                prompt=prompt,
                req_file_data=file_data,
                model=model,
                gem=gem,
                chat=chat,
                temporary=temporary,
                session_state=session_state,
                deep_research=deep_research,
                **kwargs,
            ):
                pass

            if output is None:
                raise GeminiError(
                    "Failed to generate contents. No output data found in response."
                )

            if isinstance(chat, ChatSession):
                output.metadata = chat.metadata
                chat.last_output = output

            return output

        finally:
            if files:
                for file in files:
                    if isinstance(file, io.BytesIO):
                        file.close()

    async def generate_content_stream(
        self,
        prompt: str,
        files: list[str | Path | bytes | io.BytesIO] | None = None,
        model: Model | AvailableModel | str | dict = Model.UNSPECIFIED,
        gem: Gem | str | None = None,
        chat: Optional["ChatSession"] = None,
        temporary: bool = False,
        deep_research: bool = False,
        **kwargs,
    ) -> AsyncGenerator[ModelOutput, None]:
        """
        Generates contents with prompt in streaming mode.

        This method sends a request to Gemini and yields partial responses as they arrive.
        It automatically calculates the text delta (new characters) to provide a smooth
        streaming experience. It also continuously updates chat metadata and candidate IDs.

        Parameters
        ----------
        prompt: `str`
            Text prompt provided by user.
        files: `list[str | Path | bytes | io.BytesIO]`, optional
            List of file paths or byte streams to be attached.
        model: `Model | str | dict`, optional
            Specify the model to use for generation.
        gem: `Gem | str`, optional
            Specify a gem to use as system prompt for the chat session.
        chat: `ChatSession`, optional
            Chat data to retrieve conversation history.
        temporary: `bool`, optional
            If set to `True`, the ongoing conversation will not show up in Gemini history.
        deep_research: `bool`, optional
            If set to `True`, will enable deep research mode and start creating a deep research plan.
        kwargs: `dict`, optional
            Additional arguments passed to `curl_cffi.requests.AsyncSession.stream`.

        Yields
        ------
        :class:`ModelOutput`
            Partial output data. The `text_delta` attribute contains only the NEW characters
            received since the last yield.

        Raises
        ------
        `gemini_webapi.APIError`
            If the request fails or response structure is invalid.
        `gemini_webapi.TimeoutError`
            If the stream request times out.
        """

        if self.auto_close:
            await self.reset_close_task()

        if any([files, gem, deep_research]):
            self._check_account_status(raise_error=True)

        file_data = None
        if files:
            await self._sync_activity()

            uploaded_urls = await asyncio.gather(
                *(
                    upload_file(
                        file,
                        client=self.client,
                        push_id=self.push_id,
                        verbose=self.verbose,
                    )
                    for file in files
                )
            )
            file_data = [
                [[url], parse_file_name(file)]
                for url, file in zip(uploaded_urls, files)
            ]

        try:
            await self._sync_activity()

            session_state = {
                "last_texts": {},
                "last_thoughts": {},
            }
            output = None
            async for output in self._generate(
                prompt=prompt,
                req_file_data=file_data,
                model=model,
                gem=gem,
                chat=chat,
                temporary=temporary,
                session_state=session_state,
                deep_research=deep_research,
                **kwargs,
            ):
                yield output

            if output and isinstance(chat, ChatSession):
                output.metadata = chat.metadata
                chat.last_output = output

        finally:
            if files:
                for file in files:
                    if isinstance(file, io.BytesIO):
                        file.close()

    @running(retry=5)
    async def _generate(
        self,
        prompt: str,
        req_file_data: list[Any] | None = None,
        model: Model | AvailableModel | str | dict = Model.UNSPECIFIED,
        gem: Gem | str | None = None,
        chat: Optional["ChatSession"] = None,
        temporary: bool = False,
        session_state: dict[str, Any] | None = None,
        deep_research: bool = False,
        **kwargs,
    ) -> AsyncGenerator[ModelOutput, None]:
        """
        Internal method which actually sends content generation requests.
        """

        assert prompt, "Prompt cannot be empty."

        if isinstance(model, AvailableModel):
            pass
        elif isinstance(model, str):
            model = self._resolve_model_by_name(model)
        elif isinstance(model, dict):
            model = Model.from_dict(model)
        elif isinstance(model, Model):
            model = self._resolve_enum_model(model)
        else:
            raise TypeError(
                f"'model' must be a `Model` enum, `AvailableModel`, "
                f"string, or dictionary; got `{type(model).__name__}`"
            )

        if model is not Model.UNSPECIFIED and not getattr(model, "is_available", True):
            raise GeminiError(
                f"{model.model_name} is not available for use. Account status: {self.account_status.name} - {self.account_status.description}"
            )

        _reqid = self._reqid
        self._reqid += 100000

        gem_id = gem.id if isinstance(gem, Gem) else gem

        chat_backup: dict[str, Any] | None = None
        if chat:
            chat_backup = {
                "metadata": (
                    chat.metadata
                    if getattr(chat, "metadata", None)
                    else DEFAULT_METADATA
                ),
                "cid": getattr(chat, "cid", ""),
                "rid": getattr(chat, "rid", ""),
                "rcid": getattr(chat, "rcid", ""),
            }

        if session_state is None:
            session_state = {
                "last_texts": {},
                "last_thoughts": {},
            }

        has_generated_text = False
        sleep_time = 10

        message_content = [
            prompt,
            0,
            None,
            req_file_data,
            None,
            None,
            0,
        ]

        params: dict[str, Any] = {"hl": self.language, "_reqid": _reqid, "rt": "c"}
        if self.build_label:
            params["bl"] = self.build_label
        if self.session_id:
            params["f.sid"] = self.session_id

        while True:
            try:
                inner_req_list: list[Any] = [None] * 69
                inner_req_list[0] = message_content
                inner_req_list[1] = [self.language]
                inner_req_list[2] = chat.metadata if chat else DEFAULT_METADATA
                if deep_research:
                    inner_req_list[3] = "!" + secrets.token_urlsafe(2600)
                    inner_req_list[4] = uuid.uuid4().hex
                inner_req_list[6] = [1]
                inner_req_list[STREAMING_FLAG_INDEX] = 1
                inner_req_list[10] = 1
                inner_req_list[11] = 0
                inner_req_list[17] = [[0]]
                inner_req_list[18] = 0
                if gem_id:
                    inner_req_list[GEM_FLAG_INDEX] = gem_id
                inner_req_list[27] = 1
                inner_req_list[30] = [4]
                inner_req_list[41] = [1]
                if temporary:
                    inner_req_list[TEMPORARY_CHAT_FLAG_INDEX] = 1
                if deep_research:
                    inner_req_list[49] = 1
                inner_req_list[53] = 0
                if deep_research:
                    inner_req_list[54] = [[[[[1]]]]]
                    inner_req_list[55] = [[1]]
                inner_req_list[61] = []
                inner_req_list[68] = 2

                uuid_val = str(uuid.uuid4()).upper()

                inner_req_list[59] = uuid_val

                request_headers = {
                    **Headers.GEMINI.value,
                    **model.model_header,
                    "x-goog-ext-525005358-jspb": f'["{uuid_val}",1]',
                    **Headers.SAME_DOMAIN.value,
                }

                request_data = {
                    "at": self.access_token,
                    "f.req": json.dumps(
                        [
                            None,
                            json.dumps(inner_req_list).decode("utf-8"),
                        ]
                    ).decode("utf-8"),
                }

                async with self.client.stream(
                    "POST",
                    Endpoint.GENERATE,
                    params=params,
                    headers=request_headers,
                    data=request_data,
                    **kwargs,
                ) as response:
                    if self.verbose:
                        logger.debug(
                            f"HTTP Request: POST {Endpoint.GENERATE} [{response.status_code}]"
                        )
                    if response.status_code != 200:
                        await self.close()
                        raise APIError(
                            f"Failed to generate contents. Status: {response.status_code}"
                        )

                    buffer = ""
                    _raw_response = ""  # Accumulates full raw response for debugging
                    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

                    last_texts: dict[str, str] = session_state["last_texts"]
                    last_thoughts: dict[str, str] = session_state["last_thoughts"]
                    last_progress_time: float = time.time()

                    is_thinking = False
                    is_queueing = False
                    has_candidates = False
                    is_completed = False  # Check if this conversation turn has been fully answered.
                    is_final_chunk = False  # Check if this turn is saved to history and marked complete or still pending (e.g., video generation).
                    cid = chat.cid if chat else ""
                    rid = chat.rid if chat else ""

                    async def _process_parts(
                        parts: list[Any],
                    ) -> AsyncGenerator[ModelOutput, None]:
                        nonlocal \
                            is_thinking, \
                            is_queueing, \
                            has_candidates, \
                            is_completed, \
                            is_final_chunk, \
                            cid, \
                            rid
                        for part in parts:
                            # Check for fatal error codes
                            error_code = get_nested_value(part, [5, 2, 0, 1, 0])
                            if error_code:
                                await self.close()
                                match error_code:
                                    case ErrorCode.USAGE_LIMIT_EXCEEDED:
                                        raise UsageLimitExceeded(
                                            f"Usage limit exceeded for model '{model.model_name}'. Please wait a few minutes, "
                                            "switch to a different model (e.g., Gemini Flash), or check your account limits on gemini.google.com."
                                        )
                                    case ErrorCode.MODEL_INCONSISTENT:
                                        raise ModelInvalid(
                                            "The specified model is inconsistent with the conversation history. "
                                            "Please ensure you are using the same 'model' parameter throughout the entire ChatSession."
                                        )
                                    case ErrorCode.MODEL_HEADER_INVALID:
                                        raise ModelInvalid(
                                            f"The model '{model.model_name}' is currently unavailable or the request structure is outdated. "
                                            "Please update 'gemini_webapi' to the latest version or report this on GitHub if the problem persists."
                                        )
                                    case ErrorCode.IP_TEMPORARILY_BLOCKED:
                                        raise TemporarilyBlocked(
                                            "Your IP address has been temporarily flagged or blocked by Google. "
                                            "Please try using a proxy, a different network, or wait for a while before retrying."
                                        )
                                    case ErrorCode.TEMPORARY_ERROR_1013:
                                        raise APIError(
                                            "Gemini encountered a temporary error (1013). Retrying..."
                                        )
                                    case _:
                                        raise APIError(
                                            f"Failed to generate contents (stream). Unknown API error code: {error_code}. "
                                            "This might be a temporary Google service issue."
                                        )

                            # Check for queueing status
                            status = get_nested_value(part, [5])
                            if isinstance(status, list) and status:
                                if not is_thinking:
                                    is_queueing = True
                                    if not has_candidates:
                                        logger.debug(
                                            "Model is in a waiting state (queueing)..."
                                        )

                            inner_json_str = get_nested_value(part, [2])
                            if inner_json_str:
                                try:
                                    part_json = json.loads(inner_json_str)
                                    m_data = get_nested_value(part_json, [1])
                                    if m_data:
                                        _new_cid = get_nested_value(m_data, [0])
                                        _new_rid = get_nested_value(m_data, [1])
                                        if _new_cid:
                                            cid = _new_cid
                                        if _new_rid:
                                            rid = _new_rid

                                        if isinstance(chat, ChatSession):
                                            chat.metadata = m_data

                                    # Check for busy analyzing data
                                    tool_name = get_nested_value(part_json, [6, 1, 0])
                                    if tool_name == "data_analysis_tool":
                                        is_thinking = True
                                        is_queueing = False
                                        if not has_candidates:
                                            logger.debug(
                                                "Model is active (thinking/analyzing)..."
                                            )

                                    context_str = get_nested_value(part_json, [25])
                                    if isinstance(context_str, str):
                                        is_final_chunk = True
                                        is_thinking = False
                                        is_queueing = False
                                        if isinstance(chat, ChatSession):
                                            chat.metadata = [None] * 9 + [context_str]

                                    timestamp_data = get_nested_value(
                                        part_json, [27, 0, 0, 3]
                                    )
                                    timestamp = time.time()
                                    if (
                                        isinstance(timestamp_data, list)
                                        and len(timestamp_data) >= 2
                                    ):
                                        seconds = timestamp_data[0]
                                        nanos = timestamp_data[1]
                                        timestamp = float(seconds) + (
                                            float(nanos) / 1e9
                                        )

                                    candidates_list = get_nested_value(
                                        part_json, [4], []
                                    )
                                    if candidates_list:
                                        output_candidates = []
                                        for i, candidate_data in enumerate(
                                            candidates_list
                                        ):
                                            rcid = get_nested_value(candidate_data, [0])
                                            if not rcid:
                                                continue
                                            if isinstance(chat, ChatSession):
                                                chat.rcid = rcid

                                            (
                                                text,
                                                thoughts,
                                                web_images,
                                                generated_images,
                                                generated_videos,
                                                generated_media,
                                            ) = self._parse_candidate(
                                                candidate_data, cid, rid, rcid
                                            )

                                            deep_research_plan = None
                                            if deep_research:
                                                plan_data = extract_deep_research_plan(
                                                    candidate_data,
                                                    fallback_text=text,
                                                )

                                                if plan_data:
                                                    deep_research_plan = (
                                                        DeepResearchPlan(
                                                            **plan_data,
                                                            cid=getattr(
                                                                chat, "cid", None
                                                            ),
                                                        )
                                                    )

                                            # Check if this frame represents the complete state of the message
                                            indicator = get_nested_value(
                                                candidate_data, [8, 0]
                                            )
                                            is_completed = indicator == 2

                                            # Save this conversation turn to recent chats whenever it is stored in history.
                                            if is_final_chunk:
                                                if cid and isinstance(
                                                    self._recent_chats, list
                                                ):
                                                    chat_title = f"Chat({cid})"
                                                    is_pinned = False
                                                    for c in self._recent_chats:
                                                        if c.cid == cid:
                                                            chat_title = c.title
                                                            is_pinned = c.is_pinned
                                                            break

                                                    expected_idx = (
                                                        0
                                                        if is_pinned
                                                        else sum(
                                                            1
                                                            for c in self._recent_chats
                                                            if c.cid != cid
                                                            and c.is_pinned
                                                        )
                                                    )

                                                    if not (
                                                        len(self._recent_chats)
                                                        > expected_idx
                                                        and self._recent_chats[
                                                            expected_idx
                                                        ].cid
                                                        == cid
                                                        and self._recent_chats[
                                                            expected_idx
                                                        ].title
                                                        == chat_title
                                                        and self._recent_chats[
                                                            expected_idx
                                                        ].timestamp
                                                        == timestamp
                                                    ):
                                                        self._recent_chats = [
                                                            c
                                                            for c in self._recent_chats
                                                            if c.cid != cid
                                                        ]
                                                        self._recent_chats.insert(
                                                            expected_idx,
                                                            ChatInfo(
                                                                cid=cid,
                                                                title=chat_title,
                                                                is_pinned=is_pinned,
                                                                timestamp=timestamp,
                                                            ),
                                                        )

                                            last_sent_text = last_texts.get(
                                                rcid
                                            ) or last_texts.get(f"idx_{i}", "")
                                            text_delta, new_full_text = (
                                                get_delta_by_fp_len(
                                                    text,
                                                    last_sent_text,
                                                    is_final=is_completed
                                                    or indicator is None,
                                                )
                                            )
                                            last_sent_thought = last_thoughts.get(
                                                rcid
                                            ) or last_thoughts.get(f"idx_{i}", "")
                                            if thoughts:
                                                thoughts_delta, new_full_thought = (
                                                    get_delta_by_fp_len(
                                                        thoughts,
                                                        last_sent_thought,
                                                        is_final=is_completed
                                                        or indicator is None,
                                                    )
                                                )
                                            else:
                                                thoughts_delta = ""
                                                new_full_thought = ""

                                            if (
                                                text_delta
                                                or thoughts_delta
                                                or web_images
                                                or generated_images
                                                or generated_videos
                                                or generated_media
                                                or deep_research_plan
                                            ):
                                                has_candidates = True

                                            # Update state with the provider's cleaned state to handle drift
                                            last_texts[rcid] = last_texts[
                                                f"idx_{i}"
                                            ] = new_full_text

                                            last_thoughts[rcid] = last_thoughts[
                                                f"idx_{i}"
                                            ] = new_full_thought

                                            output_candidates.append(
                                                Candidate(
                                                    rcid=rcid,
                                                    text=text,
                                                    text_delta=text_delta,
                                                    thoughts=thoughts or None,
                                                    thoughts_delta=thoughts_delta,
                                                    web_images=web_images,
                                                    generated_images=generated_images,
                                                    generated_videos=generated_videos,
                                                    generated_media=generated_media,
                                                    deep_research_plan=deep_research_plan,
                                                )
                                            )

                                        if output_candidates:
                                            is_thinking = False
                                            is_queueing = False
                                            yield ModelOutput(
                                                metadata=[cid, rid],
                                                candidates=output_candidates,
                                            )
                                except json.JSONDecodeError:
                                    continue

                    chunk_iterator = response.aiter_content().__aiter__()
                    while True:
                        try:
                            stall_threshold = (
                                self.timeout
                                if (is_thinking or is_queueing)
                                else min(self.timeout, self.watchdog_timeout)
                            )
                            chunk = await asyncio.wait_for(
                                chunk_iterator.__anext__(), timeout=stall_threshold + 5
                            )
                        except StopAsyncIteration:
                            break
                        except asyncio.TimeoutError:
                            logger.debug(
                                f"[Watchdog] Socket idle for {stall_threshold + 5}s. Refreshing connection..."
                            )
                            await self.close()
                            break

                        decoded_chunk = decoder.decode(chunk, final=False)
                        buffer += decoded_chunk
                        _raw_response += decoded_chunk
                        if buffer.startswith(")]}'"):
                            buffer = buffer[4:].lstrip()
                        parsed_parts, buffer = parse_response_by_frame(buffer)

                        got_update = False
                        async for out in _process_parts(parsed_parts):
                            has_generated_text = True
                            yield out
                            got_update = True

                        if got_update:
                            last_progress_time = time.time()
                        else:
                            stall_threshold = (
                                self.timeout
                                if (is_thinking or is_queueing)
                                else min(self.timeout, self.watchdog_timeout)
                            )
                            if (time.time() - last_progress_time) > stall_threshold:
                                if is_thinking:
                                    logger.debug(
                                        f"[Watchdog] Model is taking its time thinking ({int(time.time() - last_progress_time)}s). Reconnecting to poll..."
                                    )
                                    break
                                else:
                                    logger.debug(
                                        f"[Watchdog] Connection idle for {stall_threshold}s (queueing={is_queueing}). "
                                        "Attempting recovery..."
                                    )
                                    await self.close()
                                    break

                    # Final flush
                    final_decoded = decoder.decode(b"", final=True)
                    buffer += final_decoded
                    _raw_response += final_decoded
                    if buffer:
                        parsed_parts, _ = parse_response_by_frame(buffer)
                        async for out in _process_parts(parsed_parts):
                            has_generated_text = True
                            yield out

                    if not is_completed or is_thinking or is_queueing:
                        if (
                            cid and is_final_chunk
                        ):  # The conversation can only be recovered if Gemini has saved the context.
                            logger.debug(
                                f"Stream incomplete. Checking conversation history for {cid}..."
                            )

                            poll_start_time = time.time()

                            while True:
                                if (time.time() - poll_start_time) > self.timeout:
                                    logger.warning(
                                        f"[Recovery] Polling for {cid} timed out after {self.timeout}s."
                                    )
                                    await self.close()
                                    if has_generated_text:
                                        raise GeminiError(
                                            "The connection to Gemini was lost while generating the response, and recovery timed out. "
                                            "Please try sending your prompt again."
                                        )
                                    else:
                                        raise APIError(
                                            "read_chat polling timed out waiting for the model to finish. "
                                            "The original request may have been silently aborted by Google."
                                        )
                                await self._sync_activity()
                                recovered_history = await self.read_chat(cid)
                                if (
                                    recovered_history
                                    and recovered_history.turns
                                    and recovered_history.turns[0].role == "model"
                                ):
                                    recovered = recovered_history.turns[0].model_output
                                    if (
                                        recovered
                                        and recovered.candidates
                                        and (
                                            recovered.text
                                            or recovered.thoughts
                                            or recovered.images
                                            or recovered.videos
                                            or recovered.media
                                        )
                                    ):
                                        rec_rcid = recovered.rcid
                                        prev_rcid = (
                                            chat_backup["rcid"] if chat_backup else ""
                                        )
                                        current_expected_rcid = (
                                            getattr(chat, "rcid", "") if chat else ""
                                        )

                                        is_new_turn = rec_rcid != prev_rcid

                                        if is_new_turn:
                                            logger.debug(
                                                f"[Recovery] Successfully recovered response for CID: {cid} (RCID: {rec_rcid})"
                                            )
                                            if chat:
                                                recovered.metadata = chat.metadata
                                                chat.rcid = rec_rcid
                                            yield recovered
                                            break
                                        else:
                                            logger.debug(
                                                f"[Recovery] Recovered turn is not the target turn (target: {current_expected_rcid or 'NEW'}, got {rec_rcid}). Waiting..."
                                            )

                                logger.debug(
                                    f"[Recovery] Response not ready, waiting {sleep_time}s..."
                                )
                                await asyncio.sleep(sleep_time)
                            break
                        else:
                            logger.debug(
                                f"Stream suspended (completed={is_completed}, final_chunk={is_final_chunk}, thinking={is_thinking}, queueing={is_queueing}). "
                                f"No CID found to recover. (Request ID: {_reqid})"
                            )
                            raise APIError(
                                "The original request may have been silently aborted by Google."
                            )

                    # Full raw HTTP response text at completion
                    if self.verbose:
                        if _raw_response.startswith(")]}'"):
                            _raw_response = _raw_response[4:].lstrip()
                        _parsed_full, _ = parse_response_by_frame(_raw_response)
                        logger.debug(
                            f"[Debug] Full raw response received (parsed into {len(_parsed_full)} parts)"
                        )

                break

            except ReadTimeout:
                raise TimeoutError(
                    "The request timed out while waiting for Gemini to respond. This often happens with very long prompts "
                    "or complex file analysis. Try increasing the 'timeout' value when initializing GeminiClient."
                )
            except (UsageLimitExceeded, GeminiError, APIError):
                if not has_generated_text and chat and chat_backup:
                    chat.metadata = chat_backup["metadata"]
                    chat.cid = chat_backup["cid"]
                    chat.rid = chat_backup["rid"]
                    chat.rcid = chat_backup["rcid"]
                raise
            except Exception as e:
                if not has_generated_text and chat and chat_backup:
                    chat.metadata = chat_backup["metadata"]
                    chat.cid = chat_backup["cid"]
                    chat.rid = chat_backup["rid"]
                    chat.rcid = chat_backup["rcid"]
                logger.debug(
                    "Stream parsing interrupted. Attempting to recover conversation context..."
                )
                raise APIError(
                    f"Failed to parse response body from Google ({type(e).__name__}). This might be a temporary API change or invalid data."
                )

        # Update quotas after successful generation
        quota_flags = self._get_quota_flags(model)
        await self._fetch_quota(**quota_flags)

    def _parse_candidate(
        self, candidate_data: list[Any], cid: str, rid: str, rcid: str
    ) -> tuple[
        str,
        str,
        list[WebImage],
        list[GeneratedImage],
        list[GeneratedVideo],
        list[GeneratedMedia],
    ]:
        """
        Parses individual candidate data from the Gemini response.

        Parameters
        ----------
        candidate_data: `list[Any]`
            The raw candidate list from the API response.
        cid: `str`
            Chat ID.
        rid: `str`
            Reply ID.
        rcid: `str`
            Reply candidate ID.

        Returns
        -------
        `tuple[str, str, list[WebImage], list[GeneratedImage], list[GeneratedVideo], list[GeneratedMedia]]`
            By order, the returned tuple contains:
                - text: The main response text.
                - thoughts: The model's reasoning or internal thoughts.
                - web_images: List of images found on the web.
                - generated_images: List of images generated by the model.
                - generated_videos: List of videos generated by the model.
                - generated_media: List of media (music/audio) generated by the model.
        """

        text = get_nested_value(candidate_data, [1, 0], "")
        if CARD_CONTENT_RE.match(text):
            text = get_nested_value(candidate_data, [22, 0]) or text

        # Cleanup googleusercontent artifacts
        text = ARTIFACTS_RE.sub("", text)

        thoughts = get_nested_value(candidate_data, [37, 0, 0]) or ""

        # Image handling
        web_images = []
        for img_idx, web_img_data in enumerate(
            get_nested_value(candidate_data, [12, 1], [])
        ):
            url = get_nested_value(web_img_data, [0, 0, 0])
            if url:
                web_images.append(
                    WebImage(
                        url=url,
                        title=f"[Image {img_idx + 1}]",
                        alt=get_nested_value(web_img_data, [0, 4], ""),
                        proxy=self.proxy,
                        client=self.client,
                    )
                )

        generated_images = []
        for img_idx, gen_img_data in enumerate(
            get_nested_value(candidate_data, [12, 7, 0], [])  # Plain generation
            + get_nested_value(candidate_data, [12, 0, "8", 0], [])  # Image to image
        ):
            url = get_nested_value(gen_img_data, [0, 3, 3])
            if url:
                image_id = get_nested_value(gen_img_data, [1, 0])
                if not image_id:
                    image_id = f"http://googleusercontent.com/image_generation_content/{img_idx}"

                generated_images.append(
                    GeneratedImage(
                        url=url,
                        title=f"[Generated Image {img_idx}]",
                        alt=get_nested_value(gen_img_data, [0, 3, 2], ""),
                        proxy=self.proxy,
                        client=self.client,
                        client_ref=self,
                        cid=cid,
                        rid=rid,
                        rcid=rcid,
                        image_id=image_id,
                    )
                )

        # Video handling
        generated_videos = []
        video_info = get_nested_value(candidate_data, [12, 59, 0, 0, 0], [])
        if video_info:
            urls = get_nested_value(video_info, [0, 7], [])
            if len(urls) >= 2:
                generated_videos.append(
                    GeneratedVideo(
                        url=urls[1],
                        thumbnail=urls[0],
                        cid=cid,
                        rid=rid,
                        rcid=rcid,
                        client_ref=self,
                        proxy=self.proxy,
                    )
                )

        # Media (Music) handling
        generated_media = []
        media_data = get_nested_value(candidate_data, [12, 86], [])
        if media_data:
            mp3_url = ""
            mp3_thumb = ""
            mp3_list = get_nested_value(media_data, [0, 1, 7], [])
            if len(mp3_list) >= 2:
                mp3_thumb = mp3_list[0]
                mp3_url = mp3_list[1]

            mp4_url = ""
            mp4_thumb = ""
            mp4_list = get_nested_value(media_data, [1, 1, 7], [])
            if len(mp4_list) >= 2:
                mp4_thumb = mp4_list[0]
                mp4_url = mp4_list[1]

            if mp3_url or mp4_url:
                generated_media.append(
                    GeneratedMedia(
                        url=mp4_url,
                        thumbnail=mp4_thumb,
                        mp3_url=mp3_url,
                        mp3_thumbnail=mp3_thumb,
                        cid=cid,
                        rid=rid,
                        rcid=rcid,
                        client_ref=self,
                        proxy=self.proxy,
                    )
                )

        return (
            text,
            thoughts,
            web_images,
            generated_images,
            generated_videos,
            generated_media,
        )

    async def _get_full_size_image(
        self, cid: str, rid: str, rcid: str, image_id: str
    ) -> str | None:
        """
        Get the full size URL of an image.
        """

        try:
            payload = [
                [
                    [None, None, None, [None, None, None, None, None, ""]],
                    [image_id, 0],
                    None,
                    [19, ""],
                    None,
                    None,
                    None,
                    None,
                    None,
                    "",
                ],
                [rid, rcid, cid, None, ""],
                1,
                0,
                1,
            ]

            response = await self._batch_execute(
                [
                    RPCData(
                        rpcid=GRPC.DOWNLOAD_GENERATED_IMAGE,
                        payload=json.dumps(payload).decode("utf-8"),
                    ),
                ]
            )

            response_data = extract_json_from_response(response.text)
            return get_nested_value(
                json.loads(get_nested_value(response_data, [0, 2], "[]")), [0]
            )
        except Exception:
            logger.debug(
                "_get_full_size_image Could not retrieve full size URL via RPC."
            )
            return None

    @running(retry=2)
    async def _batch_execute(
        self,
        payloads: list[RPCData],
        source_path: str = "/app",
        close_on_error: bool = True,
        **kwargs,
    ) -> Response:
        """
        Execute a batch of requests to Gemini API.

        Parameters
        ----------
        payloads: `list[RPCData]`
            List of `gemini_webapi.types.RPCData` objects to be executed.
        kwargs: `dict`, optional
            Additional arguments which will be passed to the post request.
            Refer to `curl_cffi.requests.AsyncSession.request` for more information.

        Returns
        -------
        :class:`curl_cffi.requests.Response`
            Response object containing the result of the batch execution.
        """

        _reqid = self._reqid
        self._reqid += 100000

        try:
            params: dict[str, Any] = {
                "rpcids": ",".join([p.rpcid for p in payloads]),
                "hl": self.language,
                "_reqid": _reqid,
                "rt": "c",
                "source-path": source_path,
            }
            if self.build_label:
                params["bl"] = self.build_label
            if self.session_id:
                params["f.sid"] = self.session_id

            request_headers = {
                **Headers.GEMINI.value,
                **Headers.BATCH_EXEC.value,
                **Headers.SAME_DOMAIN.value,
            }

            response = await self.client.post(
                Endpoint.BATCH_EXEC,
                params=params,
                headers=request_headers,
                data={
                    "at": self.access_token,
                    "f.req": json.dumps(
                        [[payload.serialize() for payload in payloads]]
                    ).decode("utf-8"),
                },
                **kwargs,
            )

            if self.verbose:
                logger.debug(
                    f"HTTP Request: POST {Endpoint.BATCH_EXEC} [{response.status_code}]"
                )
        except ReadTimeout:
            raise TimeoutError(
                "The request timed out while waiting for Gemini to respond. This often happens with very long prompts "
                "or complex file analysis. Try increasing the 'timeout' value when initializing GeminiClient."
            )

        if response.status_code != 200:
            if close_on_error:
                await self.close()
            raise APIError(
                f"Batch execution failed with status code {response.status_code}"
            )

        return response

    def start_chat(self, **kwargs) -> "ChatSession":
        """
        Returns a `ChatSession` object attached to this client.

        Parameters
        ----------
        kwargs: `dict`, optional
            Additional arguments which will be passed to the chat session.
            Refer to `gemini_webapi.ChatSession` for more information.

        Returns
        -------
        :class:`ChatSession`
            Empty chat session object for retrieving conversation history.
        """

        return ChatSession(geminiclient=self, **kwargs)


class ChatSession:
    """
    Chat data to retrieve conversation history. Only if all 3 ids are provided will the conversation history be retrieved.

    Parameters
    ----------
    geminiclient: `GeminiClient`
        Async requests client interface for gemini.google.com.
    metadata: `list[str]`, optional
        List of chat metadata `[cid, rid, rcid]`, can be shorter than 3 elements, like `[cid, rid]` or `[cid]` only.
    cid: `str`, optional
        Chat ID, if provided together with metadata, will override the first value in it.
    rid: `str`, optional
        Reply ID, if provided together with metadata, will override the second value in it.
    rcid: `str`, optional
        Reply candidate ID, if provided together with metadata, will override the third value in it.
    model: `Model | str | dict`, optional
        Specify the model to use for generation.
        Pass either a `gemini_webapi.constants.Model` enum or a model name string to use predefined models.
        Pass a dictionary to use custom model header strings ("model_name" and "model_header" keys must be provided).
    gem: `Gem | str`, optional
        Specify a gem to use as system prompt for the chat session.
        Pass either a `gemini_webapi.types.Gem` object or a gem id string.
    """

    __slots__ = [
        "__metadata",
        "geminiclient",
        "last_output",
        "model",
        "gem",
    ]

    def __init__(
        self,
        geminiclient: GeminiClient,
        metadata: list[str | None] | None = None,
        cid: str = "",  # chat id
        rid: str = "",  # reply id
        rcid: str = "",  # reply candidate id
        model: Model | AvailableModel | str | dict = Model.UNSPECIFIED,
        gem: Gem | str | None = None,
    ):
        self.__metadata: list[Any] = DEFAULT_METADATA.copy()
        self.geminiclient: GeminiClient = geminiclient
        self.last_output: ModelOutput | None = None
        self.model: Model | AvailableModel | str | dict = model
        self.gem: Gem | str | None = gem

        if metadata:
            self.metadata = metadata
        if cid:
            self.cid = cid
        if rid:
            self.rid = rid
        if rcid:
            self.rcid = rcid

    def __str__(self):
        return f"ChatSession(cid={self.cid!r}, rid={self.rid!r}, rcid={self.rcid!r})"

    __repr__ = __str__

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        # update conversation history when last output is updated
        if name == "last_output" and isinstance(value, ModelOutput):
            self.metadata = value.metadata
            self.rcid = value.rcid

    async def send_message(
        self,
        prompt: str,
        files: list[str | Path | bytes | io.BytesIO] | None = None,
        temporary: bool = False,
        deep_research: bool = False,
        **kwargs,
    ) -> ModelOutput:
        """
        Generates contents with prompt.
        Use as a shortcut for `GeminiClient.generate_content(prompt, files, self)`.

        Parameters
        ----------
        prompt: `str`
            Text prompt provided by user.
        files: `list[str | Path | bytes | io.BytesIO]`, optional
            List of file paths or byte streams to be attached.
        temporary: `bool`, optional
            If set to `True`, the ongoing conversation will not show up in Gemini history.
            Switching temporary mode within a chat session will clear the previous context
            and create a new chat session under the hood.
        deep_research: `bool`, optional
            If set to `True`, will enable deep research mode and start creating a deep research plan.
        kwargs: `dict`, optional
            Additional arguments which will be passed to the post request.
            Refer to `curl_cffi.requests.AsyncSession.request` for more information.

        Returns
        -------
        :class:`ModelOutput`
            Output data from gemini.google.com.

        Raises
        ------
        `AssertionError`
            If prompt is empty.
        `gemini_webapi.TimeoutError`
            If request timed out.
        `gemini_webapi.GeminiError`
            If no reply candidate found in response.
        `gemini_webapi.APIError`
            - If request failed with status code other than 200.
            - If response structure is invalid and failed to parse.
        """

        return await self.geminiclient.generate_content(
            prompt=prompt,
            files=files,
            model=self.model,
            gem=self.gem,
            chat=self,
            temporary=temporary,
            deep_research=deep_research,
            **kwargs,
        )

    async def send_message_stream(
        self,
        prompt: str,
        files: list[str | Path | bytes | io.BytesIO] | None = None,
        temporary: bool = False,
        deep_research: bool = False,
        **kwargs,
    ) -> AsyncGenerator[ModelOutput, None]:
        """
        Generates contents with prompt in streaming mode within this chat session.

        This is a shortcut for `GeminiClient.generate_content_stream(prompt, files, self)`.
        The session's metadata and conversation history are automatically managed.

        Parameters
        ----------
        prompt: `str`
            Text prompt provided by user.
        files: `list[str | Path | bytes | io.BytesIO]`, optional
            List of file paths or byte streams to be attached.
        temporary: `bool`, optional
            If set to `True`, the ongoing conversation will not show up in Gemini history.
            Switching temporary mode within a chat session will clear the previous context
            and create a new chat session under the hood.
        deep_research: `bool`, optional
            If set to `True`, will enable deep research mode and start creating a deep research plan.
        kwargs: `dict`, optional
            Additional arguments passed to the streaming request.

        Yields
        ------
        :class:`ModelOutput`
            Partial output data containing text deltas.
        """

        async for output in self.geminiclient.generate_content_stream(
            prompt=prompt,
            files=files,
            model=self.model,
            gem=self.gem,
            chat=self,
            temporary=temporary,
            deep_research=deep_research,
            **kwargs,
        ):
            yield output

    def choose_candidate(self, index: int) -> ModelOutput:
        """
        Choose a candidate from the last `ModelOutput` to control the ongoing conversation flow.

        Parameters
        ----------
        index: `int`
            Index of the candidate to choose, starting from 0.

        Returns
        -------
        :class:`ModelOutput`
            Output data of the chosen candidate.

        Raises
        ------
        `ValueError`
            If no previous output data found in this chat session, or if index exceeds the number of candidates in last model output.
        """

        if not self.last_output:
            raise ValueError("No previous output data found in this chat session.")

        if index >= len(self.last_output.candidates):
            raise ValueError(
                f"Index {index} exceeds the number of candidates in last model output."
            )

        self.last_output.chosen = index
        self.rcid = self.last_output.rcid
        return self.last_output

    async def read_history(self, limit: int = 10) -> ChatHistory | None:
        """
        Fetch the conversation history for this session.

        Parameters
        ----------
        limit: `int`, optional
            The maximum number of turns to fetch, by default 10.

        Returns
        -------
        :class:`ChatHistory` | None
            The conversation history, or None if reading failed or cid is missing.
        """

        if not self.cid:
            return None

        return await self.geminiclient.read_chat(self.cid, limit=limit)

    @property
    def metadata(self):
        return self.__metadata

    @metadata.setter
    def metadata(self, value: list[str]):
        if not isinstance(value, list):
            return

        # Update only non-None elements to preserve existing CID/RID/RCID/Context
        for i, val in enumerate(value):
            if i < 10 and val is not None:
                self.__metadata[i] = val

    @property
    def cid(self):
        return self.__metadata[0]

    @cid.setter
    def cid(self, value: str):
        self.__metadata[0] = value

    @property
    def rid(self):
        return self.__metadata[1]

    @rid.setter
    def rid(self, value: str):
        self.__metadata[1] = value

    @property
    def rcid(self):
        return self.__metadata[2]

    @rcid.setter
    def rcid(self, value: str):
        self.__metadata[2] = value
