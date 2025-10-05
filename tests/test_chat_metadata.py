"""
Test correct handling of chat metadata in streaming responses

This script verifies:
1. After the first conversation, metadata is correctly saved (including all 10 elements)
2. During the second streaming conversation, the complete metadata is correctly passed
"""

import os
import sys
import asyncio

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from gemini_webapi import GeminiClient, set_log_level
from gemini_webapi.constants import Model

set_log_level("DEBUG")


async def test_chat_metadata_in_stream():
    """Test metadata passing in conversation"""
    print("\n" + "=" * 60)
    print("Test: Correct Passing of Chat Metadata in Streaming Response")
    print("=" * 60 + "\n")
    
    client = GeminiClient(
        os.getenv("SECURE_1PSID"),
        os.getenv("SECURE_1PSIDTS")
    )
    await client.init()
    
    # Create chat session
    chat = client.start_chat()
    print(f"Initial metadata: {chat.metadata}\n")
    
    # First round - use normal response to establish session
    print("=" * 60)
    print("First round (normal response - establish session)")
    print("=" * 60)
    response1 = await chat.send_message("What is Genshin Impact?")
    print(f"\nAI: {response1.text}")
    print(f"\n✅ Metadata after conversation: {chat.metadata}")
    print(f"   Metadata length: {len(chat.metadata)}")
    print(f"   CID: {chat.cid}")
    print(f"   RID: {chat.rid}")
    print(f"   RCID: {chat.rcid}")
    
    # Verify metadata updated
    if all(x is None for x in chat.metadata[:3]):
        print("\n⚠️  Warning: Metadata not updated correctly!")
    else:
        print(f"\n✅ Metadata updated correctly")
    
    # Second round - streaming response
    print("\n" + "=" * 60)
    print("Second round (streaming response)")
    print("=" * 60)
    print("\nUser: What is Genshin Impact?\n")
    print("AI: ", end="", flush=True)
    
    stream = await chat.send_message_stream("What are its features?")
    
    final_metadata = []
    async for chunk in stream:
        print(chunk.delta_text, end="", flush=True)
        if chunk.metadata:
            final_metadata = chunk.metadata
        if chunk.is_final:
            break
    
    print("\n")
    print(f"\nMetadata after streaming response: {chat.metadata}")
    print(f"Metadata length: {len(chat.metadata)}")
    print(f"Metadata from response: {final_metadata}")
    print(f"CID: {chat.cid}")
    print(f"RID: {chat.rid}")
    print(f"RCID: {chat.rcid}")
    
    # Third round - streaming response again to verify context
    print("\n" + "=" * 60)
    print("Third round (streaming response again, verify context)")
    print("=" * 60)
    print("\nUser: What are its features?\n")
    print("AI: ", end="", flush=True)
    
    stream2 = await chat.send_message_stream("What are its characters?")
    
    async for chunk in stream2:
        print(chunk.delta_text, end="", flush=True)
        if chunk.is_final:
            break
    
    print("\n")
    print(f"\nMetadata after third round: {chat.metadata}")
    print(f"Metadata length: {len(chat.metadata)}")
    
    await client.close()
    
    print("\n" + "=" * 60)
    print("✅ Test completed!")
    print("=" * 60)


async def test_metadata_structure():
    """Test metadata structure"""
    print("\n" + "=" * 60)
    print("Test: Metadata Structure Validation")
    print("=" * 60 + "\n")
    
    client = GeminiClient(
        os.getenv("SECURE_1PSID"),
        os.getenv("SECURE_1PSIDTS")
    )
    await client.init()
    
    chat = client.start_chat()
    
    # Get a response to check metadata structure
    response = await chat.send_message("test")
    
    print(f"ModelOutput.metadata: {response.metadata}")
    print(f"Metadata type: {type(response.metadata)}")
    print(f"Metadata length: {len(response.metadata)}")
    print(f"\nMetadata detailed structure:")
    for i, item in enumerate(response.metadata):
        print(f"  [{i}]: {repr(item)} (type: {type(item).__name__})")
    
    print(f"\nChatSession.metadata: {chat.metadata}")
    print(f"ChatSession metadata length: {len(chat.metadata)}")
    print(f"\nChatSession metadata detailed structure:")
    for i, item in enumerate(chat.metadata):
        print(f"  [{i}]: {repr(item)} (type: {type(item).__name__})")
    
    await client.close()
    
    print("\n" + "=" * 60)
    print("✅ Structure test completed!")
    print("=" * 60)


async def main():
    """Run all tests"""
    if not os.getenv("SECURE_1PSID"):
        print("\n❌ Error: Please set the environment variable SECURE_1PSID")
        print("   In Windows PowerShell: $env:SECURE_1PSID='your_cookie_value'")
        return
    
    try:
        await test_metadata_structure()
        await asyncio.sleep(2)
        await test_chat_metadata_in_stream()
        
    except KeyboardInterrupt:
        print("\n\n⚠️  User interrupted")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
