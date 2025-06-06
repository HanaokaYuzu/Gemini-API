import asyncio
from gemini_webapi import GeminiChatAsync
from gemini_webapi.exceptions import AuthError, TransientError

async def main():
    '''Basic usage example for Gemini API'''
    try:
        # Initialize the client
        client = GeminiChatAsync()

        # Start a new conversation
        chat = await client.start_chat()

        # Send a message and get a response
        response = await chat.send_message("Hello, how are you today?")
        print(f"Gemini: {response.text}")

        # Continue the conversation
        follow_up = await chat.send_message("Tell me a short story about AI")
        print(f"Gemini: {follow_up.text}")

    except AuthError as e:
        print(f"Authentication failed: {e}")
    except TransientError as e:
        print(f"Temporary error occurred: {e}. Please try again later.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Always close the client
        if 'client' in locals():
            await client.close()

if __name__ == "__main__":
    asyncio.run(main())
