# Streaming API Reference

Complete API reference for the Gemini-API streaming functionality.

## Table of Contents

- [Overview](#overview)
- [Classes](#classes)
  - [StreamedResponse](#streamedresponse)
  - [StreamChunk](#streamchunk)
- [Methods](#methods)
  - [GeminiClient.generate_content_stream()](#geminiclientgenerate_content_stream)
  - [ChatSession.send_message_stream()](#chatsessionsend_message_stream)
  - [StreamedResponse.collect()](#streamedresponsecollect)
- [Properties](#properties)
- [Usage Examples](#usage-examples)
- [Best Practices](#best-practices)

## Overview

The streaming API allows you to receive partial responses as they are generated, providing a better user experience for real-time applications. The API uses async iterators to yield chunks of data as they arrive.

## Classes

### StreamedResponse

An async iterator that yields `StreamChunk` objects as they arrive from the API.

**Usage:**

```python
stream = await client.generate_content_stream("Your prompt")
async for chunk in stream:
    process_chunk(chunk)
```

**Methods:**

#### `__aiter__()`

Returns the async iterator itself.

**Returns:** `AsyncIterator[StreamChunk]`

#### `collect()`

Collects all chunks and returns a complete `ModelOutput` object.

**Returns:** `ModelOutput`

**Example:**

```python
stream = await client.generate_content_stream("Tell me a story")
model_output = await stream.collect()
print(model_output.text)
```

---

### StreamChunk

Represents a single chunk of streaming data.

**Attributes:**

| Name | Type | Description |
|------|------|-------------|
| `text` | `str` | Accumulated text content from the beginning to current chunk |
| `delta_text` | `str` | New text content added in this chunk only |
| `thoughts` | `str \| None` | Accumulated thought process from the beginning (thinking models only) |
| `delta_thoughts` | `str` | New thought process content added in this chunk only |
| `is_final` | `bool` | Whether this is the final chunk in the stream |
| `metadata` | `list[str \| None]` | Chat metadata in format `[cid, rid, rcid, None*6, token]` |
| `candidates` | `list[Candidate]` | List of response candidates if available |

**Methods:**

#### `__str__()`

Returns the accumulated text content.

**Returns:** `str`

#### `__repr__()`

Returns a string representation of the chunk with truncated text and delta information.

**Returns:** `str`

**Example:**

```python
async for chunk in stream:
    print(f"Type: {type(chunk)}")
    print(f"Text length: {len(chunk.text)}")
    print(f"Delta length: {len(chunk.delta_text)}")
    print(f"Has thoughts: {chunk.thoughts is not None}")
    print(f"Is final: {chunk.is_final}")
```

---

## Methods

### GeminiClient.generate_content_stream()

Generates content in streaming mode.

**Signature:**

```python
async def generate_content_stream(
    self,
    prompt: str,
    files: list[str | Path] | None = None,
    model: Model | str = Model.UNSPECIFIED,
    gem: Gem | str | None = None,
    chat: Optional["ChatSession"] = None,
    **kwargs,
) -> StreamedResponse
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `prompt` | `str` | Required | The text prompt to send to the model |
| `files` | `list[str \| Path] \| None` | `None` | List of file paths to include with the prompt |
| `model` | `Model \| str` | `Model.UNSPECIFIED` | The model to use for generation |
| `gem` | `Gem \| str \| None` | `None` | Gem ID or Gem object to use as system prompt |
| `chat` | `ChatSession \| None` | `None` | Chat session for retrieving conversation history |
| `**kwargs` | | | Additional parameters passed to the POST request |

**Returns:** `StreamedResponse`

**Raises:**

- `AssertionError` - If prompt is empty
- `TimeoutError` - If the request times out
- `APIError` - If the API request fails

**Example:**

```python
stream = await client.generate_content_stream(
    "Explain quantum entanglement",
    model=Model.G_2_5_FLASH,
    files=["diagram.png"]
)

async for chunk in stream:
    if chunk.delta_text:
        print(chunk.delta_text, end="", flush=True)
```

---

### ChatSession.send_message_stream()

Sends a message in a chat session with streaming response.

**Signature:**

```python
async def send_message_stream(
    self,
    prompt: str,
    files: list[str | Path] | None = None,
    **kwargs,
) -> StreamedResponse
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `prompt` | `str` | Required | The text prompt to send in the conversation |
| `files` | `list[str \| Path] \| None` | `None` | List of file paths to include with the message |
| `**kwargs` | | | Additional parameters passed to the underlying generate_content_stream |

**Returns:** `StreamedResponse`

**Raises:**

- `AssertionError` - If prompt is empty
- `TimeoutError` - If the request times out
- `APIError` - If the API request fails

**Example:**

```python
chat = client.start_chat()
stream = await chat.send_message_stream("Hello!")

async for chunk in stream:
    print(chunk.delta_text, end="", flush=True)
```

---

### StreamedResponse.collect()

Collects all streaming chunks and returns a complete `ModelOutput` object.

**Signature:**

```python
async def collect(self) -> ModelOutput
```

**Returns:** `ModelOutput` - Complete response with all accumulated data

**Example:**

```python
stream = await client.generate_content_stream("Write a haiku")
model_output = await stream.collect()

print(f"Text: {model_output.text}")
print(f"Metadata: {model_output.metadata}")
print(f"Candidates: {len(model_output.candidates)}")
```

---

## Properties

### Delta vs Accumulated Properties

Understanding the difference between delta and accumulated properties is crucial for proper streaming usage:

| Property | Type | Purpose | Use Case |
|----------|------|---------|----------|
| `text` | Accumulated | Full text from start | Display complete response, save to file |
| `delta_text` | Incremental | Only new text in this chunk | Real-time display, progress tracking |
| `thoughts` | Accumulated | Full thought process from start | Display complete reasoning, analysis |
| `delta_thoughts` | Incremental | Only new thoughts in this chunk | Real-time thought display, streaming UI |

**Key Points:**

- **Use delta properties** for real-time streaming display to avoid repeating content
- **Use accumulated properties** when you need the complete content at any point
- Delta properties may be empty if there's no new content in a chunk
- Both text and thoughts can update independently

---

## Usage Examples

### Basic Text Streaming

```python
async def basic_stream():
    stream = await client.generate_content_stream("Count from 1 to 10")
    
    async for chunk in stream:
        if chunk.delta_text:
            print(chunk.delta_text, end="", flush=True)
        
        if chunk.is_final:
            print("\n[Done]")
            break
```

### Streaming with Progress Tracking

```python
async def stream_with_progress():
    stream = await client.generate_content_stream("Explain machine learning")
    
    char_count = 0
    chunk_count = 0
    
    async for chunk in stream:
        if chunk.delta_text:
            print(chunk.delta_text, end="", flush=True)
            char_count = len(chunk.text)
            chunk_count += 1
        
        if chunk.is_final:
            print(f"\n\nReceived {chunk_count} chunks, {char_count} characters total")
            break
```

### Streaming with Thinking Models

```python
async def stream_with_thinking():
    stream = await client.generate_content_stream(
        "Solve this problem: What is 15% of 240?",
        model=Model.G_2_5_PRO
    )
    
    print("Response:")
    async for chunk in stream:
        # Display thoughts in a different format
        if chunk.delta_thoughts:
            print(f"\n💭 {chunk.delta_thoughts}", end="", flush=True)
        
        # Display text content
        if chunk.delta_text:
            print(f"\n📝 {chunk.delta_text}", end="", flush=True)
        
        if chunk.is_final:
            break
```

### Collecting Metadata

```python
async def stream_with_metadata():
    stream = await client.generate_content_stream("Hello")
    
    final_metadata = None
    async for chunk in stream:
        if chunk.delta_text:
            print(chunk.delta_text, end="", flush=True)
        
        if chunk.metadata:
            final_metadata = chunk.metadata
        
        if chunk.is_final:
            break
    
    if final_metadata:
        cid, rid, rcid = final_metadata[:3]
        print(f"\n\nConversation ID: {cid}")
        print(f"Reply ID: {rid}")
        print(f"Candidate ID: {rcid}")
```

### Error Handling in Streams

```python
async def stream_with_error_handling():
    try:
        stream = await client.generate_content_stream(
            "Your prompt",
            model=Model.G_2_5_FLASH
        )
        
        async for chunk in stream:
            if chunk.delta_text:
                print(chunk.delta_text, end="", flush=True)
            
            if chunk.is_final:
                break
    
    except TimeoutError:
        print("\n[Error] Request timed out")
    except APIError as e:
        print(f"\n[Error] API error: {e}")
    except Exception as e:
        print(f"\n[Error] Unexpected error: {e}")
```

### Conditional Chunk Processing

```python
async def conditional_stream():
    stream = await client.generate_content_stream("Generate a list of 100 items")
    
    item_count = 0
    async for chunk in stream:
        if chunk.delta_text:
            print(chunk.delta_text, end="", flush=True)
            
            # Count items (assuming numbered list)
            item_count += chunk.delta_text.count('\n')
            
            # Stop after 10 items
            if item_count >= 10:
                print("\n\n[Stopped after 10 items]")
                break
```

---

## Best Practices

### 1. Always Use Delta Properties for Display

❌ **Don't:**

```python
async for chunk in stream:
    print(chunk.text)  # Repeats all previous content each time
```

✅ **Do:**

```python
async for chunk in stream:
    if chunk.delta_text:
        print(chunk.delta_text, end="", flush=True)
```

### 2. Check for Empty Deltas

Not every chunk will have new content:

```python
async for chunk in stream:
    if chunk.delta_text:  # Check before processing
        process_text(chunk.delta_text)
    
    if chunk.delta_thoughts:  # Thoughts are independent of text
        process_thoughts(chunk.delta_thoughts)
```

### 3. Always Use flush=True for Real-time Output

```python
# Ensures immediate output without buffering
print(chunk.delta_text, end="", flush=True)
```

### 4. Handle Both Text and Thoughts

When using thinking models, both can arrive in the same or different chunks:

```python
async for chunk in stream:
    # Process both independently
    if chunk.delta_thoughts:
        handle_thoughts(chunk.delta_thoughts)
    if chunk.delta_text:
        handle_text(chunk.delta_text)
```

### 5. Properly Close Streams

While the async iterator handles cleanup automatically, be aware of context:

```python
try:
    stream = await client.generate_content_stream("prompt")
    async for chunk in stream:
        # Process chunks
        if chunk.is_final:
            break
except Exception as e:
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
