import os
import unittest

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

    async def test_save_web_image(self):
        response = await self.geminiclient.generate_content(
            "Send me 10 pictures of random subjects"
        )
        self.assertTrue(response.images)
        for i, image in enumerate(response.images):
            self.assertTrue(image.url)
            await image.save()

    async def test_save_generated_image(self):
        response = await self.geminiclient.generate_content(
            "Generate some pictures of random subjects"
        )
        self.assertTrue(response.images)
        for i, image in enumerate(response.images):
            self.assertTrue(image.url)
            await image.save()


if __name__ == "__main__":
    unittest.main()
