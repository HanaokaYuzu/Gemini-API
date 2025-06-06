import asyncio
import os
from pathlib import Path
from gemini_webapi import GeminiChatAsync
from gemini_webapi.exceptions import AuthError, TransientError, ParseError
from gemini_webapi.constants import Model

async def main():
    '''Advanced usage example for Gemini API'''
    try:
        # Initialize the client with specific settings
        client = GeminiChatAsync(
            model=Model.GEMINI_PRO,
            timeout=60,
            enable_logging=True
        )

        # Start a new conversation
        chat = await client.start_chat()

        # Send a message with an image
        image_path = Path("assets/sample.pdf")
        if image_path.exists():
            try:
                response = await chat.send_message(
                    "What's in this document?",
                    files=[str(image_path)]
                )
                print(f"Gemini: {response.text}")
            except ParseError as e:
                print(f"Failed to process document: {e}")

        # Try image generation (if supported)
        try:
            image_response = await chat.send_message("Generate an image of a mountain landscape")
            if image_response.images:
                print(f"Generated {len(image_response.images)} images")
                for i, img in enumerate(image_response.images):
                    await img.save(path="output", filename=f"generated_{i}.png")
            else:
                print("No images were generated")
        except ParseError as e:
            print(f"Failed to parse image response: {e}")

    except TransientError as e:
        print(f"Temporary error occurred: {e}. Please try again later.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Clean up
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
