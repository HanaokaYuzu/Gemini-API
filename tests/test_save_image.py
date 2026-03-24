import os
import unittest
import logging
from unittest.mock import patch, AsyncMock

from curl_cffi.requests.exceptions import HTTPError

from gemini_webapi import GeminiClient, AuthError, set_log_level, logger, GeneratedImage

logging.getLogger("asyncio").setLevel(logging.ERROR)
set_log_level("DEBUG")


class TestGeminiClient(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.geminiclient = GeminiClient(
            os.getenv("SECURE_1PSID"), os.getenv("SECURE_1PSIDTS"), verify=False
        )

        try:
            await self.geminiclient.init(auto_refresh=False)
        except AuthError:
            self.skipTest("Test was skipped due to invalid cookies")

    async def asyncTearDown(self):
        await self.geminiclient.close()

    async def test_save_web_image(self):
        response = await self.geminiclient.generate_content(
            "Show me some pictures of random subjects"
        )
        self.assertTrue(response.images)
        for image in response.images:
            try:
                await image.save(verbose=True)
            except HTTPError as e:
                logger.warning(e)

    async def test_save_generated_image(self):
        response = await self.geminiclient.generate_content(
            "Generate a picture of random subjects"
        )
        self.assertTrue(response.images)

        image = response.images[0]
        if isinstance(image, GeneratedImage):
            original_url = image.url

            await image.save(verbose=True, full_size=False)
            await image.save(verbose=True, full_size=True)
            self.assertFalse(
                "=s2048-rj" in image.url,
                "Test failed: Fallback occurred despite expecting RPC success.",
            )

            image.url = original_url

            with patch.object(
                self.geminiclient, "_get_full_size_image", new_callable=AsyncMock
            ) as mock_rpc:
                mock_rpc.side_effect = Exception("Simulated RPC failure for testing")
                await image.save(verbose=True, full_size=True)
                self.assertTrue(
                    "=s2048-rj" in image.url,
                    "Test failed: Expected fallback to =s2048-rj but did not happen.",
                )

    async def test_save_image_to_image(self):
        response = await self.geminiclient.generate_content(
            "Design an application icon based on the provided image. Make it simple and modern.",
            files=["assets/banner.png"],
        )
        self.assertTrue(response.images)
        for image in response.images:
            if isinstance(image, GeneratedImage):
                await image.save(verbose=True, full_size=True)
            else:
                await image.save(verbose=True)


if __name__ == "__main__":
    unittest.main()
