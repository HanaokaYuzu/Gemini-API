# Streaming API Reference# Streaming API Reference



Comprehensive documentation for Gemini-API streaming functionality with full image support.Complete API reference for the Gemini-API streaming functionality.



## Table of Contents## Table of Contents



- [Overview](#overview)- [Overview](#overview)

- [Quick Start](#quick-start)- [Classes](#classes)

- [API Reference](#api-reference)  - [StreamedResponse](#streamedresponse)

- [Image Support](#image-support)  - [StreamChunk](#streamchunk)

- [Best Practices](#best-practices)- [Methods](#methods)

- [Examples](#examples)  - [GeminiClient.generate_content_stream()](#geminiclientgenerate_content_stream)

  - [ChatSession.send_message_stream()](#chatsessionsend_message_stream)

---  - [StreamedResponse.collect()](#streamedresponsecollect)

- [Properties](#properties)

## Overview- [Usage Examples](#usage-examples)

- [Best Practices](#best-practices)

The streaming API delivers real-time partial responses with support for:

## Overview

✅ **Text streaming** - Receive tokens as they're generated  

✅ **Thought process** - Access model reasoning (Pro model)  The streaming API allows you to receive partial responses as they are generated, providing a better user experience for real-time applications. The API uses async iterators to yield chunks of data as they arrive.

✅ **Image upload** - Send images with prompts  

✅ **Web images** - Parse search result images  ## Classes

✅ **Generated images** - Create and save AI images (Pro model)  

✅ **Chat sessions** - Multi-turn streaming conversations  ### StreamedResponse



---An async iterator that yields `StreamChunk` objects as they arrive from the API.



## Quick Start**Usage:**



### Basic Streaming```python

stream = await client.generate_content_stream("Your prompt")

```pythonasync for chunk in stream:

stream = await client.generate_content_stream("Tell me a story")    process_chunk(chunk)

```

async for chunk in stream:

    print(chunk.delta_text, end="", flush=True)**Methods:**

    if chunk.is_final:

        break#### `__aiter__()`

```

Returns the async iterator itself.

### With Images

**Returns:** `AsyncIterator[StreamChunk]`

```python

# Upload and analyze#### `collect()`

stream = await client.generate_content_stream(

    "Describe this image",Collects all chunks and returns a complete `ModelOutput` object.

    files=["photo.jpg"],

    model=Model.G_2_5_FLASH**Returns:** `ModelOutput`

)

**Example:**

# Generate images (Pro only)

stream = await client.generate_content_stream(```python

    "Generate an image of a red rose",stream = await client.generate_content_stream("Tell me a story")

    model=Model.G_2_5_PROmodel_output = await stream.collect()

)print(model_output.text)

```

async for chunk in stream:

    if chunk.generated_images:---

        for img in chunk.generated_images:

            await img.save(filename="rose.png")### StreamChunk

```

Represents a single chunk of streaming data.

### Using collect()

**Attributes:**

```python

stream = await client.generate_content_stream("Explain AI")| Name | Type | Description |

output = await stream.collect()  # Returns ModelOutput|------|------|-------------|

| `text` | `str` | Accumulated text content from the beginning to current chunk |

print(output.text)| `delta_text` | `str` | New text content added in this chunk only |

print(f"Images: {len(output.candidates[0].generated_images)}")| `thoughts` | `str \| None` | Accumulated thought process from the beginning (thinking models only) |

```| `delta_thoughts` | `str` | New thought process content added in this chunk only |

| `is_final` | `bool` | Whether this is the final chunk in the stream |

---| `metadata` | `list[str \| None]` | Chat metadata in format `[cid, rid, rcid, None*6, token]` |

| `candidates` | `list[Candidate]` | List of response candidates if available |

## API Reference

**Methods:**

### Classes

#### `__str__()`

#### **StreamedResponse**

Returns the accumulated text content.

Async iterator that yields `StreamChunk` objects.

**Returns:** `str`

**Methods:**

- `__aiter__()` → `AsyncIterator[StreamChunk]` - Iterate through chunks#### `__repr__()`

- `collect()` → `ModelOutput` - Collect all chunks into complete output

Returns a string representation of the chunk with truncated text and delta information.

#### **StreamChunk**

**Returns:** `str`

Single chunk of streaming data.

**Example:**

**Properties:**

```python

| Property | Type | Description |async for chunk in stream:

|----------|------|-------------|    print(f"Type: {type(chunk)}")

| `text` | `str` | Accumulated text from start |    print(f"Text length: {len(chunk.text)}")

| `delta_text` | `str` | New text in this chunk only |    print(f"Delta length: {len(chunk.delta_text)}")

| `thoughts` | `str \| None` | Accumulated thoughts (Pro model) |    print(f"Has thoughts: {chunk.thoughts is not None}")

| `delta_thoughts` | `str` | New thoughts in this chunk |    print(f"Is final: {chunk.is_final}")

| `web_images` | `list[WebImage]` | Web search result images |```

| `generated_images` | `list[GeneratedImage]` | AI-generated images |

| `metadata` | `list[str \| None]` | `[cid, rid, rcid, ...]` |---

| `candidates` | `list[Candidate]` | Response candidates |

| `is_final` | `bool` | Whether this is the last chunk |## Methods



### Methods### GeminiClient.generate_content_stream()



#### **client.generate_content_stream()**Generates content in streaming mode.



```python**Signature:**

async def generate_content_stream(

    prompt: str,```python

    files: list[str | Path] | None = None,async def generate_content_stream(

    model: Model | str = Model.UNSPECIFIED,    self,

    gem: Gem | str | None = None,    prompt: str,

    **kwargs    files: list[str | Path] | None = None,

) -> StreamedResponse    model: Model | str = Model.UNSPECIFIED,

```    gem: Gem | str | None = None,

    chat: Optional["ChatSession"] = None,

**Parameters:**    **kwargs,

- `prompt` - Text prompt (required)) -> StreamedResponse

- `files` - List of file paths to upload```

- `model` - Model to use (Flash/Pro)

- `gem` - System prompt/persona**Parameters:**



**Returns:** `StreamedResponse` iterator| Name | Type | Default | Description |

|------|------|---------|-------------|

#### **chat.send_message_stream()**| `prompt` | `str` | Required | The text prompt to send to the model |

| `files` | `list[str \| Path] \| None` | `None` | List of file paths to include with the prompt |

```python| `model` | `Model \| str` | `Model.UNSPECIFIED` | The model to use for generation |

async def send_message_stream(| `gem` | `Gem \| str \| None` | `None` | Gem ID or Gem object to use as system prompt |

    prompt: str,| `chat` | `ChatSession \| None` | `None` | Chat session for retrieving conversation history |

    files: list[str | Path] | None = None,| `**kwargs` | | | Additional parameters passed to the POST request |

    **kwargs

) -> StreamedResponse**Returns:** `StreamedResponse`

```

**Raises:**

Send message in chat session with streaming.

- `AssertionError` - If prompt is empty

---- `TimeoutError` - If the request times out

- `APIError` - If the API request fails

## Image Support

**Example:**

### Upload Images

```python

```pythonstream = await client.generate_content_stream(

stream = await client.generate_content_stream(    "Explain quantum entanglement",

    "What's in this image?",    model=Model.G_2_5_FLASH,

    files=["photo.jpg", "diagram.png"],    files=["diagram.png"]

    model=Model.G_2_5_FLASH)

)

```async for chunk in stream:

    if chunk.delta_text:

### Parse Web Images        print(chunk.delta_text, end="", flush=True)

```

```python

stream = await client.generate_content_stream("Show me Eiffel Tower")---



async for chunk in stream:### ChatSession.send_message_stream()

    if chunk.web_images:

        for img in chunk.web_images:Sends a message in a chat session with streaming response.

            print(f"{img.title}: {img.url}")

```**Signature:**



### Generate Images```python

async def send_message_stream(

**Requires Gemini 2.5 Pro model.**    self,

    prompt: str,

```python    files: list[str | Path] | None = None,

stream = await client.generate_content_stream(    **kwargs,

    "Generate a sunset over mountains",) -> StreamedResponse

    model=Model.G_2_5_PRO```

)

**Parameters:**

async for chunk in stream:

    if chunk.is_final and chunk.generated_images:| Name | Type | Default | Description |

        for img in chunk.generated_images:|------|------|---------|-------------|

            saved_path = await img.save(filename="sunset.png")| `prompt` | `str` | Required | The text prompt to send in the conversation |

            print(f"Saved to: {saved_path}")| `files` | `list[str \| Path] \| None` | `None` | List of file paths to include with the message |

```| `**kwargs` | | | Additional parameters passed to the underlying generate_content_stream |



### Image Classes**Returns:** `StreamedResponse`



**WebImage:****Raises:**

```python

class WebImage:- `AssertionError` - If prompt is empty

    url: str      # Image URL- `TimeoutError` - If the request times out

    title: str    # Title- `APIError` - If the API request fails

    alt: str      # Alt text

```**Example:**



**GeneratedImage:**```python

```pythonchat = client.start_chat()

class GeneratedImage:stream = await chat.send_message_stream("Hello!")

    url: str                          # Image URL

    title: str                        # Titleasync for chunk in stream:

    alt: str                          # Description    print(chunk.delta_text, end="", flush=True)

    async def save(filename: str)     # Save to disk```

```

---

---

### StreamedResponse.collect()

## Best Practices

Collects all streaming chunks and returns a complete `ModelOutput` object.

### 1. Use Delta for Display

**Signature:**

```python

# ✅ Good - Shows only new content```python

async for chunk in stream:async def collect(self) -> ModelOutput

    if chunk.delta_text:```

        print(chunk.delta_text, end="", flush=True)

**Returns:** `ModelOutput` - Complete response with all accumulated data

# ❌ Bad - Repeats all previous content

async for chunk in stream:**Example:**

    print(chunk.text)

``````python

stream = await client.generate_content_stream("Write a haiku")

### 2. Always flush Outputmodel_output = await stream.collect()



```pythonprint(f"Text: {model_output.text}")

print(chunk.delta_text, end="", flush=True)  # Real-time outputprint(f"Metadata: {model_output.metadata}")

```print(f"Candidates: {len(model_output.candidates)}")

```

### 3. Check Before Access

---

```python

if chunk.web_images:## Properties

    process_images(chunk.web_images)

### Delta vs Accumulated Properties

if chunk.delta_thoughts:

    display_thoughts(chunk.delta_thoughts)Understanding the difference between delta and accumulated properties is crucial for proper streaming usage:

```

| Property | Type | Purpose | Use Case |

### 4. Use Pro for Image Generation|----------|------|---------|----------|

| `text` | Accumulated | Full text from start | Display complete response, save to file |

```python| `delta_text` | Incremental | Only new text in this chunk | Real-time display, progress tracking |

# Only Pro can generate images| `thoughts` | Accumulated | Full thought process from start | Display complete reasoning, analysis |

stream = await client.generate_content_stream(| `delta_thoughts` | Incremental | Only new thoughts in this chunk | Real-time thought display, streaming UI |

    "Generate...",

    model=Model.G_2_5_PRO  # Not Flash!**Key Points:**

)

```- **Use delta properties** for real-time streaming display to avoid repeating content

- **Use accumulated properties** when you need the complete content at any point

### 5. Wait for Final Chunk- Delta properties may be empty if there's no new content in a chunk

- Both text and thoughts can update independently

```python

async for chunk in stream:---

    # Process...

    ## Usage Examples

    if chunk.is_final:

        # All images are available now### Basic Text Streaming

        all_images = chunk.web_images + chunk.generated_images

        break```python

```async def basic_stream():

    stream = await client.generate_content_stream("Count from 1 to 10")

### 6. Error Handling    

    async for chunk in stream:

```python        if chunk.delta_text:

try:            print(chunk.delta_text, end="", flush=True)

    stream = await client.generate_content_stream(prompt)        

    async for chunk in stream:        if chunk.is_final:

        if chunk.delta_text:            print("\n[Done]")

            print(chunk.delta_text, end="", flush=True)            break

except TimeoutError:```

    print("Request timed out")

except Exception as e:### Streaming with Progress Tracking

    print(f"Error: {e}")

``````python

async def stream_with_progress():

---    stream = await client.generate_content_stream("Explain machine learning")

    

## Examples    char_count = 0

    chunk_count = 0

### Example 1: Real-time Streaming    

    async for chunk in stream:

```python        if chunk.delta_text:

async def stream_response():            print(chunk.delta_text, end="", flush=True)

    stream = await client.generate_content_stream(            char_count = len(chunk.text)

        "Write a poem about coding",            chunk_count += 1

        model=Model.G_2_5_FLASH        

    )        if chunk.is_final:

                print(f"\n\nReceived {chunk_count} chunks, {char_count} characters total")

    print("Response: ", end="", flush=True)            break

    async for chunk in stream:```

        print(chunk.delta_text, end="", flush=True)

        if chunk.is_final:### Streaming with Thinking Models

            print("\n✅ Done")

            break```python

```async def stream_with_thinking():

    stream = await client.generate_content_stream(

### Example 2: Progress Tracking        "Solve this problem: What is 15% of 240?",

        model=Model.G_2_5_PRO

```python    )

async def track_progress():    

    stream = await client.generate_content_stream("Explain quantum physics")    print("Response:")

        async for chunk in stream:

    chars = 0        # Display thoughts in a different format

    chunks = 0        if chunk.delta_thoughts:

                print(f"\n💭 {chunk.delta_thoughts}", end="", flush=True)

    async for chunk in stream:        

        if chunk.delta_text:        # Display text content

            print(chunk.delta_text, end="", flush=True)        if chunk.delta_text:

            chars = len(chunk.text)            print(f"\n📝 {chunk.delta_text}", end="", flush=True)

            chunks += 1        

                if chunk.is_final:

        if chunk.is_final:            break

            print(f"\n\nReceived {chunks} chunks, {chars} characters")```

            break

```### Collecting Metadata



### Example 3: Thinking Model```python

async def stream_with_metadata():

```python    stream = await client.generate_content_stream("Hello")

async def show_thoughts():    

    stream = await client.generate_content_stream(    final_metadata = None

        "Calculate 15% of 240",    async for chunk in stream:

        model=Model.G_2_5_PRO        if chunk.delta_text:

    )            print(chunk.delta_text, end="", flush=True)

            

    async for chunk in stream:        if chunk.metadata:

        if chunk.delta_thoughts:            final_metadata = chunk.metadata

            print(f"💭 {chunk.delta_thoughts}", end="", flush=True)        

        if chunk.delta_text:        if chunk.is_final:

            print(f"\n📝 {chunk.delta_text}", end="", flush=True)            break

        if chunk.is_final:    

            break    if final_metadata:

```        cid, rid, rcid = final_metadata[:3]

        print(f"\n\nConversation ID: {cid}")

### Example 4: Image Analysis        print(f"Reply ID: {rid}")

        print(f"Candidate ID: {rcid}")

```python```

async def analyze_image():

    stream = await client.generate_content_stream(### Error Handling in Streams

        "Describe this image in detail",

        files=["photo.jpg"],```python

        model=Model.G_2_5_FLASHasync def stream_with_error_handling():

    )    try:

            stream = await client.generate_content_stream(

    output = await stream.collect()            "Your prompt",

    print(output.text)            model=Model.G_2_5_FLASH

```        )

        

### Example 5: Generate and Save Images        async for chunk in stream:

            if chunk.delta_text:

```python                print(chunk.delta_text, end="", flush=True)

async def generate_images():            

    stream = await client.generate_content_stream(            if chunk.is_final:

        "Generate 3 images: apple, bird, flower",                break

        model=Model.G_2_5_PRO    

    )    except TimeoutError:

            print("\n[Error] Request timed out")

    async for chunk in stream:    except APIError as e:

        print(chunk.delta_text, end="", flush=True)        print(f"\n[Error] API error: {e}")

            except Exception as e:

        if chunk.is_final and chunk.generated_images:        print(f"\n[Error] Unexpected error: {e}")

            print(f"\n\n✅ Generated {len(chunk.generated_images)} images")```

            

            for i, img in enumerate(chunk.generated_images):### Conditional Chunk Processing

                filename = f"image_{i+1}.png"

                await img.save(filename=filename)```python

                print(f"   Saved: {filename}")async def conditional_stream():

            break    stream = await client.generate_content_stream("Generate a list of 100 items")

```    

    item_count = 0

### Example 6: Chat Session    async for chunk in stream:

        if chunk.delta_text:

```python            print(chunk.delta_text, end="", flush=True)

async def chat_conversation():            

    chat = client.start_chat(model=Model.G_2_5_PRO)            # Count items (assuming numbered list)

                item_count += chunk.delta_text.count('\n')

    # Turn 1            

    stream = await chat.send_message_stream("Generate a cat image")            # Stop after 10 items

    async for chunk in stream:            if item_count >= 10:

        print(chunk.delta_text, end="", flush=True)                print("\n\n[Stopped after 10 items]")

        if chunk.is_final and chunk.generated_images:                break

            await chunk.generated_images[0].save(filename="cat.png")```

    

    print("\n")---

    

    # Turn 2## Best Practices

    stream = await chat.send_message_stream("Make it orange")

    async for chunk in stream:### 1. Always Use Delta Properties for Display

        print(chunk.delta_text, end="", flush=True)

        if chunk.is_final and chunk.generated_images:❌ **Don't:**

            await chunk.generated_images[0].save(filename="orange_cat.png")

``````python

async for chunk in stream:

### Example 7: Conditional Stop    print(chunk.text)  # Repeats all previous content each time

```

```python

async def limited_stream():✅ **Do:**

    stream = await client.generate_content_stream("List 100 items")

    ```python

    count = 0async for chunk in stream:

    async for chunk in stream:    if chunk.delta_text:

        print(chunk.delta_text, end="", flush=True)        print(chunk.delta_text, end="", flush=True)

        count += chunk.delta_text.count('\n')```

        

        if count >= 10:  # Stop after 10 items### 2. Check for Empty Deltas

            print("\n[Stopped early]")

            breakNot every chunk will have new content:

```

```python

---async for chunk in stream:

    if chunk.delta_text:  # Check before processing

## Model Support        process_text(chunk.delta_text)

    

| Model | Streaming | Thoughts | Image Gen | Image Upload |    if chunk.delta_thoughts:  # Thoughts are independent of text

|-------|-----------|----------|-----------|--------------|        process_thoughts(chunk.delta_thoughts)

| G_2_5_PRO | ✅ | ✅ | ✅ | ✅ |```

| G_2_5_FLASH | ✅ | ❌ | ❌ | ✅ |

| G_2_0_FLASH | ✅ | ❌ | ❌ | ✅ |### 3. Always Use flush=True for Real-time Output



---```python

# Ensures immediate output without buffering

## Limitationsprint(chunk.delta_text, end="", flush=True)

```

- Generated images require **Gemini 2.5 Pro** model

- Web images depend on Google's search integration### 4. Handle Both Text and Thoughts

- Thought process only available with Pro model

- Very long responses may use significant memoryWhen using thinking models, both can arrive in the same or different chunks:



---```python

async for chunk in stream:

## Related    # Process both independently

    if chunk.delta_thoughts:

- [Main README](../README.md)        handle_thoughts(chunk.delta_thoughts)

- [Source Code](../src/gemini_webapi/)    if chunk.delta_text:

        handle_text(chunk.delta_text)

---```



## Changelog### 5. Properly Close Streams



**2025-10-05**While the async iterator handles cleanup automatically, be aware of context:

- Added full image support (web & generated)

- Added `web_images` and `generated_images` to `StreamChunk````python

- Fixed metadata validation for `ModelOutput`try:

- Added `delta_thoughts` for incremental thinking    stream = await client.generate_content_stream("prompt")

- Improved thought process extraction    async for chunk in stream:

        # Process chunks

---        if chunk.is_final:

            break

**Need help?** Open an issue on [GitHub](https://github.com/HanaokaYuzu/Gemini-API/issues).except Exception as e:

    # Stream is automatically cleaned up
    logger.error(f"Stream error: {e}")
```

### 6. Use is_final for Completion

```python
async for chunk in stream:
    # Process chunk...
    
    if chunk.is_final:
        # Perform final actions
        save_complete_response(chunk.text)
        break
```

### 7. Consider Memory Usage

For very long responses, accumulating all chunks can use significant memory:

```python
# If you only need to process incrementally
async for chunk in stream:
    process_and_discard(chunk.delta_text)  # Don't store everything
    
    if chunk.is_final:
        break

# Or use collect() which is optimized
model_output = await stream.collect()
```

---

## Model Support

### Models with Thought Process

Only certain models support thought process output:

| Model | Supports Thoughts | Model String |
|-------|-------------------|--------------|
| Gemini 2.5 Pro | ✅ Yes | `Model.G_2_5_PRO` or `"gemini-2.5-pro"` |
| Gemini 2.5 Flash | ❌ No | `Model.G_2_5_FLASH` or `"gemini-2.5-flash"` |
| Gemini 2.0 Flash | ❌ No | `Model.G_2_0_FLASH` or `"gemini-2.0-flash"` |

For models without thought support, `chunk.thoughts` and `chunk.delta_thoughts` will be empty.

---

## Related Documentation

- [Main README](../README.md)
- [Streaming API Guide](STREAMING_API.md) - User guide with examples
- [API Documentation](../src/gemini_webapi/) - Full package reference

---

## Changelog

### Recent Updates

- **2025-10-05**: Added `delta_thoughts` property to `StreamChunk` for incremental thought process streaming
- **2025-10-05**: Fixed initialization issues with thought process extraction
- **2025-10-05**: Improved chunk output logic to handle independent text and thought updates

---

## Contributing

Found an issue or have a suggestion? Please open an issue on [GitHub](https://github.com/HanaokaYuzu/Gemini-API/issues).
