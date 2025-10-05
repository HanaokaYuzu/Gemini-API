"""
Simple Streaming Response Usage Example

This script demonstrates how to use the streaming response feature of Gemini-API.
Please set the environment variables SECURE_1PSID and SECURE_1PSIDTS before running.
"""

# 添加 src 目录到路径
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import asyncio
from gemini_webapi import GeminiClient, set_log_level
from gemini_webapi.constants import Model

async def basic_streaming_example():
    """Basic streaming response example"""
    print("\n" + "=" * 60)
    print("Example 1: Basic Streaming Response")
    print("=" * 60 + "\n")
    
    client = GeminiClient(
        os.getenv("SECURE_1PSID"),
        os.getenv("SECURE_1PSIDTS")
    )
    await client.init()
    
    prompt = "Introduce the development history of artificial intelligence in a paragraph."
    print(f"Prompt: {prompt}\n")
    print("AI Response: ", end="", flush=True)
    
    stream = await client.generate_content_stream(
        prompt,
        model=Model.G_2_5_FLASH
    )
    
    async for chunk in stream:
        print(chunk.delta_text, end="", flush=True)
        if chunk.is_final:
            break
    
    print("\n")
    await client.close()


async def streaming_with_progress():
    """Streaming response with progress display"""
    print("\n" + "=" * 60)
    print("Example 2: Streaming Response with Progress Display")
    print("=" * 60 + "\n")
    
    client = GeminiClient(
        os.getenv("SECURE_1PSID"),
        os.getenv("SECURE_1PSIDTS")
    )
    await client.init()
    
    prompt = "Explain the basic principles of machine learning."
    print(f"Prompt: {prompt}\n")
    print("AI Response:\n")
    
    stream = await client.generate_content_stream(
        prompt,
        model=Model.G_2_5_FLASH
    )
    
    char_count = 0
    chunk_count = 0
    
    async for chunk in stream:
        print(chunk.delta_text, end="", flush=True)
        char_count = len(chunk.text)
        chunk_count += 1
        
        if chunk.is_final:
            break
    
    print(f"\n\n[Stats] Received {chunk_count} chunks, {char_count} characters in total")
    await client.close()


async def conversation_streaming():
    """Streaming response in conversation"""
    print("\n" + "=" * 60)
    print("Example 3: Streaming Response in Conversation")
    print("=" * 60 + "\n")
    
    client = GeminiClient(
        os.getenv("SECURE_1PSID"),
        os.getenv("SECURE_1PSIDTS")
    )
    await client.init()
    
    chat = client.start_chat()
    
    # First round
    print("User: What is quantum computing?\n")
    print("AI: ", end="", flush=True)
    stream1 = await chat.send_message_stream("What is quantum computing?")
    async for chunk in stream1:
        print(chunk.delta_text, end="", flush=True)
        # chat.metadata = chunk.metadata or chat.metadata  # Update metadata

        # if chunk.is_final:
        #     break
    print("\n")
    # print(f"[Updated metadata]: {chat.metadata}\n")
    
    # Second round (keep context)
    await asyncio.sleep(1)
    print("User: What are its practical applications?\n")
    print("AI: ", end="", flush=True)
    stream2 = await chat.send_message_stream("What are its practical applications?")
    async for chunk in stream2:
        print(chunk.delta_text, end="", flush=True)
        if chunk.is_final:
            break
    print("\n")
    
    await client.close()


async def streaming_with_files():
    """Streaming response with files"""
    print("\n" + "=" * 60)
    print("Example 4: Streaming Response with Files")
    print("=" * 60 + "\n")
    
    client = GeminiClient(
        os.getenv("SECURE_1PSID"),
        os.getenv("SECURE_1PSIDTS")
    )
    await client.init()
    
    # Check if file exists
    test_file = "assets/banner.png"
    if not os.path.exists(test_file):
        print(f"⚠️  File {test_file} does not exist, skipping this example")
        await client.close()
        return
    
    print(f"Uploading file: {test_file}\n")
    print("AI Response: ", end="", flush=True)
    
    stream = await client.generate_content_stream(
        "Briefly describe the content of this image.",
        files=[test_file],
        model=Model.G_2_5_FLASH
    )
    
    async for chunk in stream:
        print(chunk.delta_text, end="", flush=True)
        if chunk.is_final:
            break
    
    print("\n")
    await client.close()


async def streaming_comparison():
    """Comparison between streaming and normal response"""
    print("\n" + "=" * 60)
    print("Example 5: Streaming Response vs Normal Response Comparison")
    print("=" * 60 + "\n")
    
    client = GeminiClient(
        os.getenv("SECURE_1PSID"),
        os.getenv("SECURE_1PSIDTS")
    )
    await client.init()
    
    prompt = "Summarize deep learning in one sentence."
    
    # Streaming response
    print("📡 Streaming Response:")
    print("AI: ", end="", flush=True)
    start_time = asyncio.get_event_loop().time()
    
    stream = await client.generate_content_stream(
        prompt,
        model=Model.G_2_5_FLASH
    )
    
    first_chunk_time = None
    async for chunk in stream:
        if first_chunk_time is None:
            first_chunk_time = asyncio.get_event_loop().time()
        print(chunk.delta_text, end="", flush=True)
        if chunk.is_final:
            break
    
    stream_total_time = asyncio.get_event_loop().time() - start_time
    time_to_first_chunk = first_chunk_time - start_time if first_chunk_time else 0
    
    print(f"\n   Time to first chunk: {time_to_first_chunk:.2f}s")
    print(f"   Total time: {stream_total_time:.2f}s\n")
    
    # Normal response
    await asyncio.sleep(1)
    print("📦 Normal Response:")
    print("AI: ", end="", flush=True)
    start_time = asyncio.get_event_loop().time()
    
    response = await client.generate_content(
        prompt,
        model=Model.G_2_5_FLASH
    )
    
    normal_total_time = asyncio.get_event_loop().time() - start_time
    print(response.text)
    print(f"   Total time: {normal_total_time:.2f}s\n")
    
    print(f"💡 User perceived latency reduction: {(normal_total_time - time_to_first_chunk):.2f}s")
    
    await client.close()


async def test_streaming_long():
    """Test streaming generation (long text)"""
    print("\n\n[Test] Streaming response (long text)...")
    print("=" * 60)
    
    client = GeminiClient(
        os.getenv("SECURE_1PSID"),
        os.getenv("SECURE_1PSIDTS")
    )
    await client.init()
    
    try:
        print("test: Math problem")
        print("-" * 60)
        
        stream = await client.generate_content_stream(
            "A block with a mass of m = 10 kg slides onto a horizontal conveyor belt with an initial velocity of v₀ = 5 m/s. The conveyor belt has a length of L = 11.5 m and is initially moving at a constant speed of v_belt = 6 m/s in the same direction as the block. The coefficient of kinetic friction between the block and the belt is μ = 0.1. After the block has been on the belt for t = 13/12 s, the belt comes to a complete stop.Calculate the total impulse exerted by the conveyor belt on the block during the entire process, from the moment it lands on the belt until it slides off the end.Assume the acceleration due to gravity is g = 10 m/s².",
            model=Model.G_2_5_PRO
        )
        
        print("Real-time output:")
        full_text = ""
        chunk_count = 0
        
        async for chunk in stream:
            chunk_count += 1
            if chunk.delta_thoughts:
                print(f"[Thoughts]: {chunk.delta_thoughts}", end="", flush=True)
            if chunk.delta_text:
                print(chunk.delta_text, end="", flush=True)
                full_text += chunk.delta_text
                
        print("\n" + "-" * 60)
        print(f"[OK] Full output (total {chunk_count} chunks):")
        print(full_text)
        print("-" * 60)
        
    except Exception as e:
        print(f"[FAIL] Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()


async def main():
    """Run all examples"""
    # Set log level (optional)
    # set_log_level("DEBUG")
    
    print("\n" + "=" * 60)
    print("Gemini-API Streaming Response Examples")
    print("=" * 60)
    
    # Check environment variables
    if not os.getenv("SECURE_1PSID"):
        print("\n❌ Error: Please set the environment variable SECURE_1PSID")
        print("   In Windows PowerShell: $env:SECURE_1PSID='your_cookie_value'")
        print("   In Linux/Mac: export SECURE_1PSID='your_cookie_value'")
        return
    
    try:
        # Run examples
        await basic_streaming_example()
        await test_streaming_long()
        await streaming_with_progress()
        await conversation_streaming()
        await streaming_with_files()
        await streaming_comparison()
        
        print("\n" + "=" * 60)
        print("[OK] All examples completed!")
        print("=" * 60 + "\n")
        
    except KeyboardInterrupt:
        print("\n\n[WARNING] User interrupted")
    except Exception as e:
        print(f"\n\n[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
