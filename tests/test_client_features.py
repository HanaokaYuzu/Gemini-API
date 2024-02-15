import os
import unittest

from loguru import logger

from gemini import GeminiClient, AuthError


class TestGeminiClient(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.geminiclient = GeminiClient(
            os.getenv("SECURE_1PSID"), os.getenv("SECURE_1PSIDTS")
        )

        try:
            await self.geminiclient.init()
        except AuthError:
            self.skipTest("Test was skipped due to invalid cookies")

    async def test_successful_request(self):
        response = await self.geminiclient.generate_content("Hello World!")
        self.assertTrue(response.text)

    async def test_continuous_conversation(self):
        chat = self.geminiclient.start_chat()
        response1 = await chat.send_message("Briefly introduce Europe")
        self.assertTrue(response1.text)
        logger.debug(response1.text)
        response2 = await chat.send_message("What's the population there?")
        self.assertTrue(response2.text)
        logger.debug(response2.text)

    async def test_send_web_image(self):
        response = await self.geminiclient.generate_content(
            "Send me some pictures of cats"
        )
        self.assertTrue(response.images)
        for image in response.images:
            self.assertTrue(image.url)
            logger.debug(image)

    async def test_ai_image_generation(self):
        response = await self.geminiclient.generate_content(
            "Generate some pictures of cats"
        )
        self.assertTrue(response.images)
        for image in response.images:
            self.assertTrue(image.url)
            logger.debug(image)

    async def test_reply_candidates(self):
        chat = self.geminiclient.start_chat()
        response = await chat.send_message(
            "What's the best Japanese dish? Recommend one only."
        )
        self.assertTrue(len(response.candidates) > 1)
        for candidate in response.candidates:
            logger.debug(candidate)

        new_candidate = chat.choose_candidate(index=1)
        self.assertEqual(response.chosen, 1)
        followup_response = await chat.send_message("Tell me more about it.")
        logger.warning(new_candidate.text)
        logger.warning(followup_response.text)


if __name__ == "__main__":
    unittest.main()
