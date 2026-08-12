import logging
import os
import unittest
from pathlib import Path

from gemini_webapi import Gem, GeminiClient, logger, set_log_level
from gemini_webapi.constants import Model
from gemini_webapi.exceptions import AuthError, ModelInvalidError, UsageLimitExceededError

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

    async def asyncTearDown(self):
        await self.geminiclient.close()

    @logger.catch(reraise=True)
    async def test_successful_request(self):
        response = await self.geminiclient.generate_content(
            "Tell me a fact about today in history and illustrate it with a youtube video",
            model=Model.BASIC_FLASH,
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
    async def test_switch_model(self):
        for model in Model:
            if model.advanced_only:
                logger.debug(f"Model {model.model_name} requires an advanced account")
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
            model=Model.ADVANCED_PRO,
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
            model=Model.ADVANCED_PRO,
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
            model=Model.BASIC_FLASH,
            gem=Gem(id="coding-partner", name="Coding partner", predefined=True),
        )
        logger.debug(response.text)

    @logger.catch(reraise=True)
    async def test_thinking_model(self):
        response = await self.geminiclient.generate_content(
            "1+1=?",
            model=Model.BASIC_PRO,
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
