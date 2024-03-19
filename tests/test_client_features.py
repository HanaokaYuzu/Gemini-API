import os
import unittest
import logging

from loguru import logger

from gemini_webapi import GeminiClient, AuthError, set_log_level

logging.getLogger("asyncio").setLevel(logging.ERROR)
set_log_level("DEBUG")


class TestGeminiClient(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.geminiclient = GeminiClient(
            os.getenv("SECURE_1PSID"), os.getenv("SECURE_1PSIDTS")
        )

        try:
            await self.geminiclient.init()
        except AuthError:
            self.skipTest("Test was skipped due to invalid cookies")

    @logger.catch(reraise=True)
    async def test_successful_request(self):
        response = await self.geminiclient.generate_content("Hello World!")
        self.assertTrue(response.text)

    @logger.catch(reraise=True)
    async def test_upload_image(self):
        response = await self.geminiclient.generate_content(
            "Describe the image", image="assets/banner.png"
        )
        self.assertTrue(response.text)
        logger.debug(response.text)

    @logger.catch(reraise=True)
    async def test_continuous_conversation(self):
        chat = self.geminiclient.start_chat()
        response1 = await chat.send_message("Briefly introduce Europe")
        self.assertTrue(response1.text)
        logger.debug(response1.text)
        response2 = await chat.send_message("What's the population there?")
        self.assertTrue(response2.text)
        logger.debug(response2.text)

    @logger.catch(reraise=True)
    async def test_chatsession_with_image(self):
        chat = self.geminiclient.start_chat()
        response1 = await chat.send_message(
            "Describe the image", image="assets/banner.png"
        )
        self.assertTrue(response1.text)
        logger.debug(response1.text)
        response2 = await chat.send_message("Tell me more about it.")
        self.assertTrue(response2.text)
        logger.debug(response2.text)

    @logger.catch(reraise=True)
    async def test_send_web_image(self):
        response = await self.geminiclient.generate_content(
            "Send me some pictures of cats"
        )
        self.assertTrue(response.images)
        for image in response.images:
            self.assertTrue(image.url)
            logger.debug(image)

    @logger.catch(reraise=True)
    async def test_ai_image_generation(self):
        response = await self.geminiclient.generate_content(
            "Generate some pictures of cats"
        )
        self.assertTrue(response.images)
        for image in response.images:
            self.assertTrue(image.url)
            logger.debug(image)

    @logger.catch(reraise=True)
    async def test_extension_google_workspace(self):
        response = await self.geminiclient.generate_content(
            "@Gmail What's the latest message in my mailbox?"
        )
        self.assertTrue(response.text)
        logger.debug(response)

    @logger.catch(reraise=True)
    async def test_extension_youtube(self):
        response = await self.geminiclient.generate_content(
            "@Youtube What's the lastest activity of Taylor Swift?"
        )
        self.assertTrue(response.text)
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
