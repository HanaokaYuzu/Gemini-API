import contextlib
import logging
import os
import unittest
from pathlib import Path

from gemini_webapi import Gem, GeminiClient, logger, set_log_level
from gemini_webapi.constants import AccountStatus, Model, warn_deprecated_model
from gemini_webapi.exceptions import AuthError, ModelInvalidError, UsageLimitExceededError
from gemini_webapi.types import AvailableModel

logging.getLogger("asyncio").setLevel(logging.ERROR)
set_log_level("DEBUG")


class TestGeminiClient(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.geminiclient = GeminiClient(
            os.getenv("SECURE_1PSID"), os.getenv("SECURE_1PSIDTS"), verify=False
        )

        try:
            await self.geminiclient.init(auto_refresh=False, verbose=True)
        except AuthError as e:
            self.skipTest(e)

        if self.geminiclient.account_status != AccountStatus.AVAILABLE:
            # Initialization no longer fails without usable cookies - it falls back to a guest
            # session, which has no history, no uploads and no model choice, so every test here
            # would fail for the wrong reason
            self.skipTest(
                f"No usable account: {self.geminiclient.account_status.name} - "
                f"{self.geminiclient.account_status.description}"
            )

    async def asyncTearDown(self):
        await self.geminiclient.close()

    def _pick_model(self, keyword: str = "") -> AvailableModel:
        """A model this account can actually use, chosen from what discovery found.

        Tests name a capability ("pro", "flash") rather than a fixed model, since which models
        exist and what they are called is decided by Google per account, not by this library.
        """
        available = [m for m in self.geminiclient.list_models() or [] if m.is_available]
        if not available:
            self.skipTest("No usable models were discovered for this account")

        if matches := [m for m in available if keyword in m.model_name.lower()]:
            # Shortest name wins, so "flash" prefers gemini-flash over gemini-flash-lite
            return min(matches, key=lambda m: len(m.model_name))

        logger.debug(f"No {keyword!r} model for this account; falling back to {available[0]}")
        return available[0]

    @logger.catch(reraise=True)
    async def test_successful_request(self):
        response = await self.geminiclient.generate_content(
            "Tell me a fact about today in history and illustrate it with a youtube video",
            model=self._pick_model("flash"),
        )
        logger.debug(response.text)

    @logger.catch(reraise=True)
    async def test_streaming_mode(self):
        chunk_count = 0

        async for chunk in self.geminiclient.generate_content_stream(
            "What's the difference between 'await' and 'async for'?"
        ):
            chunk_count += 1
            print(chunk.text_delta, end="", flush=True)
        print()

        logger.debug(f"Total chunks: {chunk_count}")

    @logger.catch(reraise=True)
    async def test_list_models(self):
        models = self.geminiclient.list_models()
        if models is None:
            self.skipTest("Models list is None")
        assert len(models) > 0
        for model in models:
            logger.debug(f"{model.display_name}: {model!r}")

    @logger.catch(reraise=True)
    async def test_resolve_model(self):
        model = self._pick_model()

        for name in (model.model_name, model.model_id, model.display_name.lower()):
            assert self.geminiclient.resolve_model(name) is model, f"{name} did not resolve"

        for alias in model.aliases:
            # An alias can be shared by several models, so only the kind is guaranteed
            assert isinstance(self.geminiclient.resolve_model(alias), AvailableModel)

        with contextlib.suppress(ValueError):
            self.geminiclient.resolve_model("gemini-not-a-real-model")
            raise AssertionError("an unknown model name should not resolve")

    @logger.catch(reraise=True)
    async def test_default_model(self):
        """No model argument leaves the choice to Google rather than to a hardcoded default."""
        response = await self.geminiclient.generate_content("1+1=? Reply with the number only.")
        assert response.text
        logger.debug(response.text)

    @logger.catch(reraise=True)
    async def test_deprecated_model_enum(self):
        """A `Model` member still works, mapped onto this account's models, and warns once."""
        warn_deprecated_model.cache_clear()
        messages: list[str] = []
        sink = logger.add(lambda m: messages.append(m.record["message"]), level="WARNING")
        try:
            response = await self.geminiclient.generate_content(
                "1+1=? Reply with the number only.",
                model=Model.BASIC_FLASH,
            )
        finally:
            logger.remove(sink)

        assert response.text
        assert any("deprecated `Model` enum" in message for message in messages), messages
        logger.debug(response.text)

    @logger.catch(reraise=True)
    async def test_switch_model(self):
        models = self.geminiclient.list_models()
        if not models:
            self.skipTest("Models list is None")

        for model in models:
            if not model.is_available:
                logger.debug(f"Model {model.model_name} is not available to this account")
                continue

            try:
                response = await self.geminiclient.generate_content(
                    "What's you language model version? Reply version number only.",
                    model=model,
                )
                logger.debug(f"Model version ({model.model_name}): {response.text}")
            except UsageLimitExceededError:
                logger.debug(f"Model {model.model_name} usage limit exceeded")
            except ModelInvalidError:
                logger.debug(f"Model {model.model_name} is not available anymore")

    @logger.catch(reraise=True)
    async def test_upload_files(self):
        response = await self.geminiclient.generate_content(
            "Introduce the contents of these two files. Is there any connection between them?",
            files=["assets/sample.pdf", Path("assets/banner.png")],
        )
        logger.debug(response.text)

    @logger.catch(reraise=True)
    async def test_continuous_conversation(self):
        chat = self.geminiclient.start_chat()
        response1 = await chat.send_message("Briefly introduce Europe")
        logger.debug(response1.text)
        response2 = await chat.send_message("What's the population there?")
        logger.debug(response2.text)

    @logger.catch(reraise=True)
    async def test_send_web_image(self):
        response = await self.geminiclient.generate_content("Send me some pictures of cats")
        assert response.images
        logger.debug(response.text)
        for image in response.images:
            logger.debug(image)

    @logger.catch(reraise=True)
    async def test_image_generation(self):
        response = await self.geminiclient.generate_content("Generate some pictures of cats")
        assert response.images
        logger.debug(response.text)
        for image in response.images:
            logger.debug(image)

    @logger.catch(reraise=True)
    async def test_video_generation(self):
        response = await self.geminiclient.generate_content(
            "Generate a short video of a sunset over the beach",
            model=self._pick_model("pro"),
        )
        assert response.videos
        logger.debug(response.text)
        for video in response.videos:
            logger.debug(video)
            paths = await video.save()
            video_path = paths.get("video")
            thumb_path = paths.get("video_thumbnail")
            assert video_path is not None
            assert os.path.exists(str(video_path))
            if thumb_path:
                assert os.path.exists(str(thumb_path))
                assert Path(str(video_path)).stem == Path(str(thumb_path)).stem
            logger.debug(f"Saved video to: {paths}")

    @logger.catch(reraise=True)
    async def test_music_generation(self):
        response = await self.geminiclient.generate_content(
            "Generate a 15-second pop music track",
            model=self._pick_model("pro"),
        )
        assert response.media
        logger.debug(response.text)
        for media in response.media:
            logger.debug(media)
            paths = await media.save()
            assert "audio" in paths
            assert "video" in paths
            assert os.path.exists(str(paths["audio"]))
            assert os.path.exists(str(paths["video"]))
            logger.debug(f"Saved media to: {paths}")

    @logger.catch(reraise=True)
    async def test_image_to_image(self):
        response = await self.geminiclient.generate_content(
            "Design an application icon based on the provided image. Make it simple and modern.",
            files=["assets/banner.png"],
        )
        assert response.images
        logger.debug(response.text)
        for image in response.images:
            logger.debug(image)

    @logger.catch(reraise=True)
    async def test_generation_with_gem(self):
        response = await self.geminiclient.generate_content(
            "What's your system prompt?",
            model=self._pick_model("flash"),
            gem=Gem(id="coding-partner", name="Coding partner", predefined=True),
        )
        logger.debug(response.text)

    @logger.catch(reraise=True)
    async def test_thinking_model(self):
        response = await self.geminiclient.generate_content(
            "1+1=?",
            model=self._pick_model("pro"),
        )
        logger.debug(response.thoughts)
        logger.debug(response.text)

    @logger.catch(reraise=True)
    async def test_retrieve_previous_conversation(self):
        chat = self.geminiclient.start_chat()
        await chat.send_message("Fine weather today")
        assert chat.cid
        assert chat.rid
        assert chat.rcid
        previous_session = chat.metadata
        logger.debug(previous_session)
        previous_chat = self.geminiclient.start_chat(metadata=previous_session)
        response = await previous_chat.send_message("What was my previous message?")
        logger.debug(response)

    @logger.catch(reraise=True)
    async def test_chatsession_with_image(self):
        chat = self.geminiclient.start_chat()
        response1 = await chat.send_message(
            "What's the difference between these two images?",
            files=["assets/banner.png", "assets/favicon.png"],
        )
        logger.debug(response1.text)
        response2 = await chat.send_message(
            "Use image generation tool to modify the banner with another font and design."
        )
        logger.debug(response2.text)
        logger.debug(response2.images)

    @logger.catch(reraise=True)
    async def test_list_chats(self):
        chats = self.geminiclient.list_chats()
        if chats is None:
            self.skipTest("Chats list is None")
        assert isinstance(chats, list)
        for chat_info in chats:
            logger.debug(f"Chat: {chat_info.title} [{chat_info.cid}]")

    @logger.catch(reraise=True)
    async def test_read_chat(self):
        chats = self.geminiclient.list_chats()
        if not chats:
            self.skipTest("No recent chats found to test read_chat.")

        chat_info = chats[0]
        history = await self.geminiclient.read_chat(chat_info.cid)
        if history is None:
            self.skipTest(f"Failed to read chat {chat_info.cid}. It might be still processing.")

        assert history is not None
        assert history.cid == chat_info.cid
        logger.debug(f"History turns: {len(history.turns)}")

    @logger.catch(reraise=True)
    async def test_read_history(self):
        chat = self.geminiclient.start_chat()
        await chat.send_message("Hello, what is the capital of Japan?")

        assert chat.cid is not None
        history = await chat.read_history()
        if history is None:
            self.skipTest("Failed to read history.")

        assert history.cid == chat.cid
        assert len(history.turns) >= 2
        logger.debug(f"History turns in chat session: {len(history.turns)}")

    @logger.catch(reraise=True)
    async def test_delete_chat(self):
        chat = self.geminiclient.start_chat()
        await chat.send_message("This is a temporary conversation.")
        assert chat.cid is not None
        await self.geminiclient.delete_chat(chat.cid)
        logger.debug(f"Chat deleted: {chat.cid}")

    @logger.catch(reraise=True)
    async def test_temporary_mode(self):
        chat = self.geminiclient.start_chat()
        await chat.send_message("Fine weather today", temporary=False)
        response = await chat.send_message("What's my last message?", temporary=True)
        logger.debug(response.text)

    @logger.catch(reraise=True)
    async def test_card_content(self):
        response = await self.geminiclient.generate_content("How is today's weather?")
        logger.debug(response.text)

    @logger.catch(reraise=True)
    async def test_extension_google_workspace(self):
        response = await self.geminiclient.generate_content(
            "@Gmail What's the latest message in my mailbox?"
        )
        logger.debug(response)

    @logger.catch(reraise=True)
    async def test_extension_youtube(self):
        response = await self.geminiclient.generate_content(
            "@Youtube What's the latest activity of Taylor Swift?"
        )
        logger.debug(response)

    @logger.catch(reraise=True)
    async def test_reply_candidates(self):
        chat = self.geminiclient.start_chat()
        response = await chat.send_message("Recommend a science fiction book for me.")

        if len(response.candidates) == 1:
            logger.debug(response.candidates[0])
            self.skipTest("Only one candidate was returned. Test skipped")

        for candidate in response.candidates:
            logger.debug(candidate)

        new_candidate = chat.choose_candidate(index=1)
        assert response.chosen == 1
        followup_response = await chat.send_message("Tell me more about it.")
        logger.warning(new_candidate.text)
        logger.warning(followup_response.text)


if __name__ == "__main__":
    unittest.main()
