"""
Streaming API Image Tests

Comprehensive tests for streaming responses with image support:
- Upload images with streaming
- Generate AI images (Pro model)
- Use collect() method
- Images in chat sessions
"""

import os
import sys
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from gemini_webapi import GeminiClient
from gemini_webapi.constants import Model


async def test_upload_images():
    """Test 1: Upload images with streaming"""
    print("\n" + "="*60)
    print("Test 1: Upload Images with Streaming")
    print("="*60 + "\n")
    
    client = GeminiClient(os.getenv("SECURE_1PSID"), os.getenv("SECURE_1PSIDTS"))
    await client.init()
    
    test_file = "assets/banner.png"
    if not os.path.exists(test_file):
        print(f"⚠️  {test_file} not found")
        await client.close()
        return
    
    stream = await client.generate_content_stream(
        "Describe this image briefly.",
        files=[test_file],
        model=Model.G_2_5_FLASH
    )
    
    print("Response: ", end="", flush=True)
    async for chunk in stream:
        print(chunk.delta_text, end="", flush=True)
        if chunk.is_final:
            print(f"\n\n✅ Text: {len(chunk.text)} chars | "
                  f"Web: {len(chunk.web_images)} | "
                  f"Generated: {len(chunk.generated_images)}")
            break
    
    await client.close()
    print("="*60)


async def test_generate_images():
    """Test 2: Generate AI images with streaming"""
    print("\n" + "="*60)
    print("Test 2: Generate AI Images")
    print("="*60 + "\n")
    
    client = GeminiClient(os.getenv("SECURE_1PSID"), os.getenv("SECURE_1PSIDTS"))
    await client.init()
    
    prompt = "Generate an image of a red rose"
    print(f"Prompt: {prompt}\n")
    
    stream = await client.generate_content_stream(
        prompt,
        model=Model.G_2_5_PRO  # Pro model required for image generation
    )
    
    print("Response: ", end="", flush=True)
    async for chunk in stream:
        print(chunk.delta_text, end="", flush=True)
        if chunk.is_final:
            print("\n")
            if chunk.generated_images:
                img = chunk.generated_images[0]
                print(f"✅ Generated: {img.title}")
                print(f"   URL: {img.url[:60]}...")
                
                # Test saving
                saved = await img.save(filename="test_rose.png")
                if saved and os.path.exists(saved):
                    size = os.path.getsize(saved)
                    print(f"   Saved: {size:,} bytes")
                    os.remove(saved)  # Cleanup
            else:
                print("⚠️  No images generated")
            break
    
    await client.close()
    print("="*60)


async def test_collect_method():
    """Test 3: Use collect() method with images"""
    print("\n" + "="*60)
    print("Test 3: collect() Method")
    print("="*60 + "\n")
    
    client = GeminiClient(os.getenv("SECURE_1PSID"), os.getenv("SECURE_1PSIDTS"))
    await client.init()
    
    test_file = "assets/banner.png"
    if not os.path.exists(test_file):
        print(f"⚠️  {test_file} not found")
        await client.close()
        return
    
    stream = await client.generate_content_stream(
        "What's in this image?",
        files=[test_file],
        model=Model.G_2_5_FLASH
    )
    
    output = await stream.collect()
    
    print(f"Text: {output.text[:100]}...")
    print(f"\n✅ Collected: {len(output.text)} chars | "
          f"Candidates: {len(output.candidates)} | "
          f"Images: {len(output.images)}")
    
    if output.candidates:
        c = output.candidates[0]
        print(f"   RCID: {c.rcid} | "
              f"Web: {len(c.web_images)} | "
              f"Generated: {len(c.generated_images)}")
    
    await client.close()
    print("="*60)


async def test_chat_with_images():
    """Test 4: Images in chat sessions"""
    print("\n" + "="*60)
    print("Test 4: Chat Session with Images")
    print("="*60 + "\n")
    
    client = GeminiClient(os.getenv("SECURE_1PSID"), os.getenv("SECURE_1PSIDTS"))
    await client.init()
    
    chat = client.start_chat(model=Model.G_2_5_PRO)
    
    print("Turn 1: Generate a cat image")
    stream = await chat.send_message_stream("Generate an image of a cute cat")
    
    async for chunk in stream:
        print(chunk.delta_text, end="", flush=True)
        if chunk.is_final:
            print("\n")
            if chunk.generated_images:
                print(f"✅ Generated {len(chunk.generated_images)} image(s)")
            break
    
    print("\nTurn 2: Follow-up message")
    stream = await chat.send_message_stream("Make it orange colored")
    
    async for chunk in stream:
        print(chunk.delta_text, end="", flush=True)
        if chunk.is_final:
            print("\n")
            if chunk.generated_images:
                print(f"✅ Generated {len(chunk.generated_images)} image(s)")
            break
    
    await client.close()
    print("="*60)


async def main():
    """Run all tests"""
    if not os.getenv("SECURE_1PSID"):
        print("\n❌ Set SECURE_1PSID environment variable")
        print("   PowerShell: $env:SECURE_1PSID='value'")
        return
    
    try:
        await test_upload_images()
        await asyncio.sleep(1)
        
        await test_generate_images()
        await asyncio.sleep(1)
        
        await test_collect_method()
        await asyncio.sleep(1)
        
        await test_chat_with_images()
        
        print("\n" + "="*60)
        print("✅ All tests completed!")
        print("="*60 + "\n")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
