import os
import unittest
import logging
from pathlib import Path

from loguru import logger

from gemini_webapi import GeminiClient, AuthError, set_log_level
from gemini_webapi.constants import Model
from gemini_webapi.exceptions import UsageLimitExceeded, ModelInvalid

logging.getLogger("asyncio").setLevel(logging.ERROR)
set_log_level("DEBUG")


class TestGeminiClient(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.geminiclient = GeminiClient(
            os.getenv("SECURE_1PSID"), os.getenv("SECURE_1PSIDTS")
        )

        try:
            await self.geminiclient.init(timeout=60)
        except AuthError as e:
            self.skipTest(e)

    @logger.catch(reraise=True)
    async def test_successful_request(self):
        response = await self.geminiclient.generate_content(
            "Tell me a fact about today in history and illustrate it with a youtube video",
            model=Model.G_2_5_FLASH,
        )
        logger.debug(response.text)

    @logger.catch(reraise=True)
    async def test_thinking_model(self):
        response = await self.geminiclient.generate_content(
            "1+1=?",
            model=Model.G_2_5_FLASH,
        )
        logger.debug(response.thoughts)
        logger.debug(response.text)

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
            except UsageLimitExceeded:
                logger.debug(f"Model {model.model_name} usage limit exceeded")
            except ModelInvalid:
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
    async def test_retrieve_previous_conversation(self):
        chat = self.geminiclient.start_chat()
        await chat.send_message("Fine weather today")
        self.assertTrue(len(chat.metadata) == 3)
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
    async def test_send_web_image(self):
        response = await self.geminiclient.generate_content(
            "Send me some pictures of cats"
        )
        self.assertTrue(response.images)
        logger.debug(response.text)
        for image in response.images:
            self.assertTrue(image.url)
            logger.debug(image)

    @logger.catch(reraise=True)
    async def test_image_generation(self):
        response = await self.geminiclient.generate_content(
            "Generate some pictures of cats"
        )
        self.assertTrue(response.images)
        logger.debug(response.text)
        for image in response.images:
            self.assertTrue(image.url)
            logger.debug(image)

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
        self.assertEqual(response.chosen, 1)
        followup_response = await chat.send_message("Tell me more about it.")
        logger.warning(new_candidate.text)
        logger.warning(followup_response.text)


if __name__ == "__main__":
    unittest.main()
