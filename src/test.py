import asyncio
from gemini_webapi import GeminiClient, set_log_level, TemporaryChatNotSupported


async def main():
    set_log_level("INFO")
    client = GeminiClient()
    await client.init(auto_refresh=False, verbose=True)

    resp = await client.generate_content("告诉我今天温州的天气如何", temporary=True)
    print("TEMP RESPONSE:", resp.text[:200])

    try:
        chat = client.start_chat()
        await chat.send_message("Should fail", temporary=True)
    except TemporaryChatNotSupported as e:
        print("CHAT TEMP NOT SUPPORTED:", e)

    await client.close()

asyncio.run(main())
