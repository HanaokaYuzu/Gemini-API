import asyncio
import codecs
import io
import random
import re
import time
from asyncio import Task
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

import orjson as json
from curl_cffi.requests import AsyncSession, Cookies, Response
from curl_cffi.requests.exceptions import ReadTimeout

from .components import GemMixin
from .constants import Endpoint, ErrorCode, GRPC, Model
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
    Candidate,
    Gem,
    GeneratedImage,
    ModelOutput,
    RPCData,
    WebImage,
)
from .utils import (
    get_access_token,
    get_delta_by_fp_len,
    get_nested_value,
    logger,
    parse_file_name,
    parse_response_by_frame,
    rotate_1psidts,
    running,
    upload_file,
)

DEFAULT_METADATA: list[Any] = ["", "", "", None, None, None, None, None, None, ""]


class GeminiClient(GemMixin):
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
        "cookies",
        "proxy",
        "_running",
        "client",
        "access_token",
        "build_label",
        "session_id",
        "timeout",
        "auto_close",
        "close_delay",
        "close_task",
        "auto_refresh",
        "refresh_interval",
        "refresh_task",
        "verbose",
        "watchdog_timeout",
        "_lock",
        "_reqid",
        "_gems",  # From GemMixin
        "kwargs",
    ]

    def __init__(
        self,
        secure_1psid: str | None = None,
        secure_1psidts: str | None = None,
        cookies: dict | Cookies | None = None,
        proxy: str | None = None,
        **kwargs,
    ):
        super().__init__()
        self.cookies = Cookies()
        self.proxy = proxy
        self._running: bool = False
        self.client: AsyncSession | None = None
        self.access_token: str | None = None
        self.build_label: str | None = None
        self.session_id: str | None = None
        self.timeout: float = 300
        self.auto_close: bool = False
        self.close_delay: float = 300
        self.close_task: Task | None = None
        self.auto_refresh: bool = True
        self.refresh_interval: float = 540
        self.refresh_task: Task | None = None
        self.verbose: bool = True
        self.watchdog_timeout: float = 60  # ≤ DELAY_FACTOR × retry × (retry + 1) / 2
        self._lock = asyncio.Lock()
        self._reqid: int = random.randint(10000, 99999)
        self.kwargs = kwargs

        if isinstance(cookies, dict):
            for k, v in cookies.items():
                self.cookies.set(k, v, domain=".google.com")
        elif isinstance(cookies, Cookies):
            self.cookies.update(cookies)

        if secure_1psid:
            self.cookies.set("__Secure-1PSID", secure_1psid, domain=".google.com")
            if secure_1psidts:
                self.cookies.set(
                    "__Secure-1PSIDTS", secure_1psidts, domain=".google.com"
                )

    async def init(
        self,
        timeout: float = 300,
        auto_close: bool = False,
        close_delay: float = 300,
        auto_refresh: bool = True,
        refresh_interval: float = 540,
        verbose: bool = True,
        watchdog_timeout: float = 60,  # ≤ DELAY_FACTOR × retry × (retry + 1) / 2
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
            If `True`, will schedule a task to automatically refresh cookies and access token in the background.
        refresh_interval: `float`, optional
            Time interval for background cookie and access token refresh in seconds. Effective only if `auto_refresh` is `True`.
        verbose: `bool`, optional
            If `True`, will print more infomation in logs.
        watchdog_timeout: `float`, optional
            Timeout in seconds for shadow retry watchdog. If no data receives from stream but connection is active,
            client will retry automatically after this duration.
        """

        async with self._lock:
            if self._running:
                return

            try:
                self.verbose = verbose
                self.watchdog_timeout = watchdog_timeout
                access_token, build_label, session_id, session = await get_access_token(
                    base_cookies=self.cookies,
                    proxy=self.proxy,
                    verbose=self.verbose,
                    verify=self.kwargs.get("verify", True),
                )

                session.timeout = timeout
                self.client = session
                self.cookies = self.client.cookies
                self.access_token = access_token
                self.build_label = build_label
                self.session_id = session_id
                self._running = True
                self._reqid = random.randint(10000, 99999)

                self.timeout = timeout
                self.auto_close = auto_close
                self.close_delay = close_delay
                if self.auto_close:
                    await self.reset_close_task()

                self.auto_refresh = auto_refresh
                self.refresh_interval = refresh_interval

                if self.refresh_task:
                    self.refresh_task.cancel()
                    self.refresh_task = None

                if self.auto_refresh:
                    self.refresh_task = asyncio.create_task(self.start_auto_refresh())

                await self._batch_execute(
                    [
                        RPCData(
                            rpcid=GRPC.BARD_ACTIVITY,
                            payload='[[["adaptive_device_responses_enabled","advanced_mode_theme_override_triggered","advanced_zs_upsell_dismissal_count","advanced_zs_upsell_last_dismissed","ai_transparency_notice_dismissed","audio_overview_discovery_dismissal_count","audio_overview_discovery_last_dismissed","bard_in_chrome_link_sharing_enabled","bard_sticky_mode_disabled_count","canvas_create_discovery_tooltip_seen_count","combined_files_button_tag_seen_count","indigo_banner_explicit_dismissal_count","indigo_banner_impression_count","indigo_banner_last_seen_sec","current_popup_id","deep_research_has_seen_file_upload_tooltip","deep_research_model_update_disclaimer_display_count","default_bot_id","disabled_discovery_card_feature_ids","disabled_model_discovery_tooltip_feature_ids","disabled_mode_disclaimers","disabled_new_model_badge_mode_ids","disabled_settings_discovery_tooltip_feature_ids","disablement_disclaimer_last_dismissed_sec","disable_advanced_beta_dialog","disable_advanced_beta_non_en_banner","disable_advanced_resubscribe_ui","disable_at_mentions_discovery_tooltip","disable_autorun_fact_check_u18","disable_bot_create_tips_card","disable_bot_docs_in_gems_disclaimer","disable_bot_onboarding_dialog","disable_bot_save_reminder_tips_card","disable_bot_send_prompt_tips_card","disable_bot_shared_in_drive_disclaimer","disable_bot_try_create_tips_card","disable_colab_tooltip","disable_collapsed_tool_menu_tooltip","disable_continue_discovery_tooltip","disable_debug_info_moved_tooltip_v2","disable_enterprise_mode_dialog","disable_export_python_tooltip","disable_extensions_discovery_dialog","disable_extension_one_time_badge","disable_fact_check_tooltip_v2","disable_free_file_upload_tips_card","disable_generated_image_download_dialog","disable_get_app_banner","disable_get_app_desktop_dialog","disable_googler_in_enterprise_mode","disable_human_review_disclosure","disable_ice_open_vega_editor_tooltip","disable_image_upload_tooltip","disable_legal_concern_tooltip","disable_llm_history_import_disclaimer","disable_location_popup","disable_memory_discovery","disable_memory_extraction_discovery","disable_new_conversation_dialog","disable_onboarding_experience","disable_personal_context_tooltip","disable_photos_upload_disclaimer","disable_power_up_intro_tooltip","disable_scheduled_actions_mobile_notification_snackbar","disable_storybook_listen_button_tooltip","disable_streaming_settings_tooltip","disable_take_control_disclaimer","disable_teens_only_english_language_dialog","disable_tier1_rebranding_tooltip","disable_try_advanced_mode_dialog","enable_advanced_beta_mode","enable_advanced_mode","enable_googler_in_enterprise_mode","enable_memory","enable_memory_extraction","enable_personal_context","enable_personal_context_gemini","enable_personal_context_gemini_using_photos","enable_personal_context_gemini_using_workspace","enable_personal_context_search","enable_personal_context_youtube","enable_token_streaming","enforce_default_to_fast_version","mayo_discovery_banner_dismissal_count","mayo_discovery_banner_last_dismissed_sec","gempix_discovery_banner_dismissal_count","gempix_discovery_banner_last_dismissed","get_app_banner_ack_count","get_app_banner_seen_count","get_app_mobile_dialog_ack_count","guided_learning_banner_dismissal_count","guided_learning_banner_last_dismissed","has_accepted_agent_mode_fre_disclaimer","has_received_streaming_response","has_seen_agent_mode_tooltip","has_seen_bespoke_tooltip","has_seen_deepthink_mustard_tooltip","has_seen_deepthink_v2_tooltip","has_seen_deep_think_tooltip","has_seen_first_youtube_video_disclaimer","has_seen_ggo_tooltip","has_seen_image_grams_discovery_banner","has_seen_image_preview_in_input_area_tooltip","has_seen_kallo_discovery_banner","has_seen_kallo_tooltip","has_seen_model_picker_in_input_area_tooltip","has_seen_model_tooltip_in_input_area_for_gempix","has_seen_redo_with_gempix2_tooltip","has_seen_veograms_discovery_banner","has_seen_video_generation_discovery_banner","is_imported_chats_panel_open_by_default","jumpstart_onboarding_dismissal_count","last_dismissed_deep_research_implicit_invite","last_dismissed_discovery_feature_implicit_invites","last_dismissed_immersives_canvas_implicit_invite","last_dismissed_immersive_share_disclaimer_sec","last_dismissed_strike_timestamp_sec","last_dismissed_zs_student_aip_banner_sec","last_get_app_banner_ack_timestamp_sec","last_get_app_mobile_dialog_ack_timestamp_sec","last_human_review_disclosure_ack","last_selected_mode_id_in_embedded","last_selected_mode_id_on_web","last_two_up_activation_timestamp_sec","last_winter_olympics_interaction_timestamp_sec","memory_extracted_greeting_name","mini_gemini_tos_closed","mode_switcher_soft_badge_disabled_ids","mode_switcher_soft_badge_seen_count","personalization_first_party_onboarding_cross_surface_clicked","personalization_first_party_onboarding_cross_surface_seen_count","personalization_one_p_discovery_card_seen_count","personalization_one_p_discovery_last_consented","personalization_zero_state_card_last_interacted","personalization_zero_state_card_seen_count","popup_zs_visits_cooldown","require_reconsent_setting_for_personalization_banner_seen_count","show_debug_info","side_nav_open_by_default","student_verification_dismissal_count","student_verification_last_dismissed","task_viewer_cc_banner_dismissed_count","task_viewer_cc_banner_dismissed_time_sec","tool_menu_new_badge_disabled_ids","tool_menu_new_badge_impression_counts","tool_menu_soft_badge_disabled_ids","tool_menu_soft_badge_impression_counts","upload_disclaimer_last_consent_time_sec","viewed_student_aip_upsell_campaign_ids","voice_language","voice_name","web_and_app_activity_enabled","wellbeing_nudge_notice_last_dismissed_sec","zs_student_aip_banner_dismissal_count"]]]',
                        )
                    ]
                )

                await self._batch_execute(
                    [
                        RPCData(
                            rpcid=GRPC.BARD_ACTIVITY,
                            payload='[[["bard_activity_enabled"]]]',
                        )
                    ]
                )

                if self.verbose:
                    logger.success("Gemini client initialized successfully.")
            except Exception:
                await self.close()
                raise

    async def close(self, delay: float = 0) -> None:
        """
        Close the client after a certain period of inactivity, or call manually to close immediately.

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

        if self.client:
            await self.client.close()

    async def reset_close_task(self) -> None:
        """
        Reset the timer for closing the client when a new request is made.
        """

        if self.close_task:
            self.close_task.cancel()
            self.close_task = None

        self.close_task = asyncio.create_task(self.close(self.close_delay))

    async def start_auto_refresh(self) -> None:
        """
        Start the background task to automatically refresh cookies.
        """
        if self.refresh_interval < 60:
            self.refresh_interval = 60

        while self._running:
            await asyncio.sleep(self.refresh_interval)

            if not self._running:
                break

            try:
                async with self._lock:
                    # Refresh all cookies in the background to keep the session alive.
                    new_1psidts, rotated_cookies = await rotate_1psidts(
                        self.cookies, self.proxy, self.verbose
                    )
                    if rotated_cookies:
                        self.cookies.update(rotated_cookies)
                        if self.client:
                            self.client.cookies.update(rotated_cookies)

                    if new_1psidts:
                        if rotated_cookies:
                            logger.debug("Cookies refreshed (network update).")
                        else:
                            logger.debug("Cookies are up to date (cached).")
                    else:
                        logger.warning(
                            "Rotation response did not contain a new __Secure-1PSIDTS. "
                            "Session might expire soon if this persists."
                        )
            except asyncio.CancelledError:
                raise
            except AuthError:
                logger.warning(
                    "AuthError: Failed to refresh cookies. Retrying in next interval."
                )
            except Exception as e:
                logger.warning(f"Unexpected error while refreshing cookies: {e}")

    async def generate_content(
        self,
        prompt: str,
        files: list[str | Path | bytes | io.BytesIO] | None = None,
        model: Model | str | dict = Model.UNSPECIFIED,
        gem: Gem | str | None = None,
        chat: Optional["ChatSession"] = None,
        **kwargs,
    ) -> ModelOutput:
        """
        Generates contents with prompt.

        Parameters
        ----------
        prompt: `str`
            Prompt provided by user.
        files: `list[str | Path]`, optional
            List of file paths to be attached.
        model: `Model | str | dict`, optional
            Specify the model to use for generation.
            Pass either a `gemini_webapi.constants.Model` enum or a model name string to use predefined models.
            Pass a dictionary to use custom model header strings ("model_name" and "model_header" keys must be provided).
        gem: `Gem | str`, optional
            Specify a gem to use as system prompt for the chat session.
            Pass either a `gemini_webapi.types.Gem` object or a gem id string.
        chat: `ChatSession`, optional
            Chat data to retrieve conversation history. If None, will automatically generate a new chat id when sending post request.
        kwargs: `dict`, optional
            Additional arguments which will be passed to the post request.
            Refer to `curl_cffi.requests.AsyncSession.request` for more information.

        Returns
        -------
        :class:`ModelOutput`
            Output data from gemini.google.com, use `ModelOutput.text` to get the default text reply, `ModelOutput.images` to get a list
            of images in the default reply, `ModelOutput.candidates` to get a list of all answer candidates in the output.

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

        file_data = None
        if files:
            await self._batch_execute(
                [
                    RPCData(
                        rpcid=GRPC.BARD_ACTIVITY,
                        payload='[[["bard_activity_enabled"]]]',
                    )
                ]
            )

            uploaded_urls = await asyncio.gather(
                *(
                    upload_file(file, proxy=self.proxy, verbose=self.verbose)
                    for file in files
                )
            )
            file_data = [
                [[url], parse_file_name(file)]
                for url, file in zip(uploaded_urls, files)
            ]

        try:
            await self._batch_execute(
                [
                    RPCData(
                        rpcid=GRPC.BARD_ACTIVITY,
                        payload='[[["bard_activity_enabled"]]]',
                    )
                ]
            )

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
                session_state=session_state,
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
        model: Model | str | dict = Model.UNSPECIFIED,
        gem: Gem | str | None = None,
        chat: Optional["ChatSession"] = None,
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
            Prompt provided by user.
        files: `list[str | Path | bytes | io.BytesIO]`, optional
            List of file paths or byte streams to be attached.
        model: `Model | str | dict`, optional
            Specify the model to use for generation.
        gem: `Gem | str`, optional
            Specify a gem to use as system prompt for the chat session.
        chat: `ChatSession`, optional
            Chat data to retrieve conversation history.
        kwargs: `dict`, optional
            Additional arguments passed to `curl_cffi.requests.AsyncSession.stream`.

        Yields
        ------
        :class:`ModelOutput`
            Partial output data. The `text` attribute contains only the NEW characters
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

        file_data = None
        if files:
            await self._batch_execute(
                [
                    RPCData(
                        rpcid=GRPC.BARD_ACTIVITY,
                        payload='[[["bard_activity_enabled"]]]',
                    )
                ]
            )

            uploaded_urls = await asyncio.gather(
                *(
                    upload_file(file, proxy=self.proxy, verbose=self.verbose)
                    for file in files
                )
            )
            file_data = [
                [[url], parse_file_name(file)]
                for url, file in zip(uploaded_urls, files)
            ]

        try:
            await self._batch_execute(
                [
                    RPCData(
                        rpcid=GRPC.BARD_ACTIVITY,
                        payload='[[["bard_activity_enabled"]]]',
                    )
                ]
            )

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
                session_state=session_state,
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
        model: Model | str | dict = Model.UNSPECIFIED,
        gem: Gem | str | None = None,
        chat: Optional["ChatSession"] = None,
        session_state: dict[str, Any] | None = None,
        **kwargs,
    ) -> AsyncGenerator[ModelOutput, None]:
        """
        Internal method which actually sends content generation requests.
        """

        assert prompt, "Prompt cannot be empty."

        if isinstance(model, str):
            model = Model.from_name(model)
        elif isinstance(model, dict):
            model = Model.from_dict(model)
        elif not isinstance(model, Model):
            raise TypeError(
                f"'model' must be a `gemini_webapi.constants.Model` instance, "
                f"string, or dictionary; got `{type(model).__name__}`"
            )

        _reqid = self._reqid
        self._reqid += 100000

        gem_id = gem.id if isinstance(gem, Gem) else gem

        chat_backup = None
        if chat:
            chat_backup = {
                "metadata": (
                    list(chat.metadata)
                    if getattr(chat, "metadata", None)
                    else list(DEFAULT_METADATA)
                ),
                "cid": getattr(chat, "cid", ""),
                "rid": getattr(chat, "rid", ""),
                "rcid": getattr(chat, "rcid", ""),
            }

        if session_state is None:
            session_state = {
                "last_texts": {},
                "last_thoughts": {},
                "last_progress_time": time.time(),
                "is_thinking": False,
                "is_queueing": False,
            }

        has_generated_text = False
        poll_count = 0

        message_content = [
            prompt,
            0,
            None,
            req_file_data,
            None,
            None,
            0,
        ]

        params: dict[str, Any] = {"_reqid": _reqid, "rt": "c"}
        if self.build_label:
            params["bl"] = self.build_label
        if self.session_id:
            params["f.sid"] = self.session_id

        while True:
            try:
                if not has_generated_text and chat and chat_backup:
                    chat.metadata = list(chat_backup["metadata"])
                    chat.cid = chat_backup["cid"]
                    chat.rid = chat_backup["rid"]
                    chat.rcid = chat_backup["rcid"]

                inner_req_list: list[Any] = [None] * 69
                inner_req_list[0] = message_content
                inner_req_list[2] = chat.metadata if chat else list(DEFAULT_METADATA)
                inner_req_list[7] = 1  # Enable Snapshot Streaming
                if gem_id:
                    inner_req_list[19] = gem_id

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
                    headers=model.model_header,
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

                    if self.client:
                        self.cookies.update(self.client.cookies)

                    buffer = ""
                    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

                    last_texts: dict[str, str] = session_state["last_texts"]
                    last_thoughts: dict[str, str] = session_state["last_thoughts"]
                    last_progress_time = session_state["last_progress_time"]

                    is_thinking = session_state["is_thinking"]
                    is_queueing = session_state["is_queueing"]
                    has_candidates = False
                    is_completed = False
                    is_final_chunk = False

                    async def _process_parts(
                        parts: list[Any],
                    ) -> AsyncGenerator[ModelOutput, None]:
                        nonlocal is_thinking, is_queueing, has_candidates, is_completed, is_final_chunk
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
                                    session_state["is_queueing"] = True
                                    if not has_candidates:
                                        logger.debug(
                                            "Model is in a waiting state (queueing)..."
                                        )

                            inner_json_str = get_nested_value(part, [2])
                            if inner_json_str:
                                try:
                                    part_json = json.loads(inner_json_str)
                                    m_data = get_nested_value(part_json, [1])
                                    if m_data and isinstance(chat, ChatSession):
                                        chat.metadata = m_data

                                    # Check for busy analyzing data
                                    tool_name = get_nested_value(part_json, [6, 1, 0])
                                    if tool_name == "data_analysis_tool":
                                        is_thinking = True
                                        session_state["is_thinking"] = True
                                        is_queueing = False
                                        session_state["is_queueing"] = False
                                        if not has_candidates:
                                            logger.debug(
                                                "Model is active (thinking/analyzing)..."
                                            )

                                    context_str = get_nested_value(part_json, [25])
                                    if isinstance(context_str, str):
                                        is_completed = True
                                        is_thinking = False
                                        session_state["is_thinking"] = False
                                        is_queueing = False
                                        session_state["is_queueing"] = False
                                        if isinstance(chat, ChatSession):
                                            chat.metadata = [None] * 9 + [context_str]

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

                                            # Text output and thoughts
                                            text = get_nested_value(
                                                candidate_data, [1, 0], ""
                                            )
                                            if re.match(
                                                r"^http://googleusercontent\.com/card_content/\d+",
                                                text,
                                            ):
                                                text = (
                                                    get_nested_value(
                                                        candidate_data, [22, 0]
                                                    )
                                                    or text
                                                )

                                            # Cleanup googleusercontent artifacts
                                            text = re.sub(
                                                r"http://googleusercontent\.com/\w+/\d+\n*",
                                                "",
                                                text,
                                            )

                                            thoughts = (
                                                get_nested_value(
                                                    candidate_data, [37, 0, 0]
                                                )
                                                or ""
                                            )
                                            # Image handling
                                            web_images = []
                                            for web_img_data in get_nested_value(
                                                candidate_data, [12, 1], []
                                            ):
                                                url = get_nested_value(
                                                    web_img_data, [0, 0, 0]
                                                )
                                                if url:
                                                    web_images.append(
                                                        WebImage(
                                                            url=url,
                                                            title=get_nested_value(
                                                                web_img_data, [7, 0], ""
                                                            ),
                                                            alt=get_nested_value(
                                                                web_img_data, [0, 4], ""
                                                            ),
                                                            proxy=self.proxy,
                                                        )
                                                    )

                                            generated_images = []
                                            for gen_img_data in get_nested_value(
                                                candidate_data, [12, 7, 0], []
                                            ):
                                                url = get_nested_value(
                                                    gen_img_data, [0, 3, 3]
                                                )
                                                if url:
                                                    img_num = get_nested_value(
                                                        gen_img_data, [3, 6]
                                                    )
                                                    generated_images.append(
                                                        GeneratedImage(
                                                            url=url,
                                                            title=(
                                                                f"[Generated Image {img_num}]"
                                                                if img_num
                                                                else "[Generated Image]"
                                                            ),
                                                            alt=get_nested_value(
                                                                gen_img_data,
                                                                [3, 5, 0],
                                                                "",
                                                            ),
                                                            proxy=self.proxy,
                                                            cookies=self.cookies,
                                                        )
                                                    )

                                            # Determine if this frame represents the final state of the message
                                            is_final_chunk = (
                                                isinstance(
                                                    get_nested_value(
                                                        candidate_data, [2]
                                                    ),
                                                    list,
                                                )
                                                or get_nested_value(
                                                    candidate_data, [8, 0], 1
                                                )
                                                == 2
                                            )

                                            last_sent_text = last_texts.get(
                                                rcid
                                            ) or last_texts.get(f"idx_{i}", "")
                                            text_delta, new_full_text = (
                                                get_delta_by_fp_len(
                                                    text,
                                                    last_sent_text,
                                                    is_final=is_final_chunk,
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
                                                        is_final=is_final_chunk,
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
                                                )
                                            )

                                        if output_candidates:
                                            is_thinking = False
                                            session_state["is_thinking"] = False
                                            is_queueing = False
                                            session_state["is_queueing"] = False
                                            yield ModelOutput(
                                                metadata=get_nested_value(
                                                    part_json, [1], []
                                                ),
                                                candidates=output_candidates,
                                            )
                                except json.JSONDecodeError:
                                    continue

                    async for chunk in response.aiter_content():
                        buffer += decoder.decode(chunk, final=False)
                        if buffer.startswith(")]}'"):
                            buffer = buffer[4:].lstrip()
                        parsed_parts, buffer = parse_response_by_frame(buffer)

                        got_update = False
                        async for out in _process_parts(parsed_parts):
                            has_generated_text = True
                            yield out
                            got_update = True

                        if got_update or (
                            parsed_parts and is_thinking and not is_queueing
                        ):
                            last_progress_time = time.time()
                            session_state["last_progress_time"] = last_progress_time
                        else:
                            stall_threshold = min(self.timeout, self.watchdog_timeout)
                            if (time.time() - last_progress_time) > stall_threshold:
                                if is_thinking:
                                    logger.debug(
                                        f"[Watchdog] Model is taking its time thinking ({int(time.time() - last_progress_time)}s). Waiting patiently..."
                                    )
                                else:
                                    logger.warning(
                                        f"Stream stalled (no progress for {stall_threshold}s, queueing={is_queueing}). "
                                        "Refreshing connection..."
                                    )
                                    await self.close()
                                    raise APIError("Response stalled (zombie stream).")

                    # Final flush
                    buffer += decoder.decode(b"", final=True)
                    if buffer:
                        parsed_parts, _ = parse_response_by_frame(buffer)
                        async for out in _process_parts(parsed_parts):
                            yield out

                    if (
                        not (is_completed or is_final_chunk)
                        or is_thinking
                        or is_queueing
                    ):
                        stall_threshold = min(self.timeout, self.watchdog_timeout)
                        if (time.time() - last_progress_time) > stall_threshold:
                            if not is_thinking:
                                logger.warning(
                                    f"Connection timed out after {stall_threshold}s. Reconnecting..."
                                )
                                raise APIError("Response stalled (zombie stream).")
                            else:
                                logger.debug(
                                    "[Watchdog] Stream finished but model is still thinking. Polling..."
                                )

                        poll_count += 1
                        sleep_time = min(2 * poll_count, 10)
                        logger.debug(
                            f"Stream suspended (completed={is_completed}, thinking={is_thinking}, queueing={is_queueing}). "
                            f"Polling for tool results in {sleep_time}s... (ReqID: {_reqid})"
                        )
                        await asyncio.sleep(sleep_time)
                        continue

                break

            except ReadTimeout:
                raise TimeoutError(
                    "The request timed out while waiting for Gemini to respond. This often happens with very long prompts "
                    "or complex file analysis. Try increasing the 'timeout' value when initializing GeminiClient."
                )
            except (GeminiError, APIError):
                if not has_generated_text and chat and chat_backup:
                    chat.metadata = list(chat_backup["metadata"])
                    chat.cid = chat_backup["cid"]
                    chat.rid = chat_backup["rid"]
                    chat.rcid = chat_backup["rcid"]
                raise
            except Exception as e:
                if not has_generated_text and chat and chat_backup:
                    chat.metadata = list(chat_backup["metadata"])
                    chat.cid = chat_backup["cid"]
                    chat.rid = chat_backup["rid"]
                    chat.rcid = chat_backup["rcid"]
                logger.debug(f"{type(e).__name__}: {e}; Unexpected parsing error.")
                raise APIError(f"Failed to parse response body: {e}")

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

    async def delete_chat(self, cid: str) -> None:
        """
        Delete a specific conversation by chat id.

        Parameters
        ----------
        cid: `str`
            The ID of the chat requiring deletion (e.g. "c_...").
        """

        await self._batch_execute(
            [
                RPCData(
                    rpcid=GRPC.DELETE_CHAT,
                    payload=json.dumps([cid]).decode("utf-8"),
                ),
            ]
        )

    @running(retry=2)
    async def _batch_execute(self, payloads: list[RPCData], **kwargs) -> Response:
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
                "_reqid": _reqid,
                "rt": "c",
                "source-path": "/app",
            }
            if self.build_label:
                params["bl"] = self.build_label
            if self.session_id:
                params["f.sid"] = self.session_id

            response = await self.client.post(
                Endpoint.BATCH_EXEC,
                params=params,
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
            await self.close()
            raise APIError(
                f"Batch execution failed with status code {response.status_code}"
            )

        if self.client:
            self.cookies.update(self.client.cookies)

        return response


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
        Chat id, if provided together with metadata, will override the first value in it.
    rid: `str`, optional
        Reply id, if provided together with metadata, will override the second value in it.
    rcid: `str`, optional
        Reply candidate id, if provided together with metadata, will override the third value in it.
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
        model: Model | str | dict = Model.UNSPECIFIED,
        gem: Gem | str | None = None,
    ):
        self.__metadata: list[Any] = list(DEFAULT_METADATA)
        self.geminiclient: GeminiClient = geminiclient
        self.last_output: ModelOutput | None = None
        self.model: Model | str | dict = model
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
        return f"ChatSession(cid='{self.cid}', rid='{self.rid}', rcid='{self.rcid}')"

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
        files: list[str | Path] | None = None,
        **kwargs,
    ) -> ModelOutput:
        """
        Generates contents with prompt.
        Use as a shortcut for `GeminiClient.generate_content(prompt, image, self)`.

        Parameters
        ----------
        prompt: `str`
            Prompt provided by user.
        files: `list[str | Path]`, optional
            List of file paths to be attached.
        kwargs: `dict`, optional
            Additional arguments which will be passed to the post request.
            Refer to `curl_cffi.requests.AsyncSession.request` for more information.

        Returns
        -------
        :class:`ModelOutput`
            Output data from gemini.google.com, use `ModelOutput.text` to get the default text reply, `ModelOutput.images` to get a list
            of images in the default reply, `ModelOutput.candidates` to get a list of all answer candidates in the output.

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
            **kwargs,
        )

    async def send_message_stream(
        self,
        prompt: str,
        files: list[str | Path] | None = None,
        **kwargs,
    ) -> AsyncGenerator[ModelOutput, None]:
        """
        Generates contents with prompt in streaming mode within this chat session.

        This is a shortcut for `GeminiClient.generate_content_stream(prompt, files, self)`.
        The session's metadata and conversation history are automatically managed.

        Parameters
        ----------
        prompt: `str`
            Prompt provided by user.
        files: `list[str | Path]`, optional
            List of file paths to be attached.
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
    def rcid(self):
        return self.__metadata[2]

    @rcid.setter
    def rcid(self, value: str):
        self.__metadata[2] = value

    @property
    def rid(self):
        return self.__metadata[1]

    @rid.setter
    def rid(self, value: str):
        self.__metadata[1] = value
