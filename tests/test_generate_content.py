import os
import unittest

from gemini import GeminiClient


class TestGenerateContent(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.geminiclient = GeminiClient(
            os.getenv("SECURE_1PSID") or "test_1psid",
            os.getenv("SECURE_1PSIDTS") or "test_ipsidts",
        )

    @unittest.skipIf(
        not (os.getenv("SECURE_1PSID") and os.getenv("SECURE_1PSIDTS")),
        "Skipping test_success...",
    )
    async def test_success(self):
        await self.geminiclient.init()
        self.assertTrue(self.geminiclient.running)

        response = await self.geminiclient.generate_content("Hello World!")
        self.assertTrue(response.text)


if __name__ == "__main__":
    unittest.main()
