<p align="center">
    <img src="https://raw.githubusercontent.com/HanaokaYuzu/Gemini-API/master/assets/banner.png" width="55%" alt="Gemini Banner" align="center">
</p>
<p align="center">
    <a href="https://pypi.org/project/gemini-webapi">
        <img src="https://img.shields.io/pypi/v/gemini-webapi" alt="PyPI"></a>
    <a href="https://pepy.tech/project/gemini-webapi">
        <img src="https://static.pepy.tech/badge/gemini-webapi" alt="Downloads"></a>
    <a href="https://github.com/HanaokaYuzu/Gemini-API/network/dependencies">
        <img src="https://img.shields.io/librariesio/github/HanaokaYuzu/Gemini-API" alt="Dependencies"></a>
    <a href="https://github.com/HanaokaYuzu/Gemini-API/blob/master/LICENSE">
        <img src="https://img.shields.io/github/license/HanaokaYuzu/Gemini-API" alt="License"></a>
    <a href="https://github.com/psf/black">
        <img src="https://img.shields.io/badge/code%20style-black-000000.svg" alt="Code style"></a>
</p>
<p align="center">
    <a href="https://star-history.com/#HanaokaYuzu/Gemini-API">
        <img src="https://img.shields.io/github/stars/HanaokaYuzu/Gemini-API?style=social" alt="GitHub stars"></a>
    <a href="https://github.com/HanaokaYuzu/Gemini-API/issues">
        <img src="https://img.shields.io/github/issues/HanaokaYuzu/Gemini-API?style=social&logo=github" alt="GitHub issues"></a>
    <a href="https://github.com/HanaokaYuzu/Gemini-API/actions/workflows/pypi-publish.yml">
        <img src="https://github.com/HanaokaYuzu/Gemini-API/actions/workflows/pypi-publish.yml/badge.svg" alt="CI"></a>
</p>

# <img src="https://raw.githubusercontent.com/HanaokaYuzu/Gemini-API/master/assets/logo.svg" width="35px" alt="Gemini Icon" /> Gemini-API

A reverse-engineered asynchronous python wrapper for [Google Gemini](https://gemini.google.com) web app (formerly Bard).

## Features

- **Persistent Cookies** - Automatically refreshes cookies in background. Optimized for always-on services.
- **Image Generation** - Natively supports generating and modifying images with natural language.
- **System Prompt** - Supports customizing model's system prompt with [Gemini Gems](https://gemini.google.com/gems/view).
- **Extension Support** - Supports generating contents with [Gemini extensions](https://gemini.google.com/extensions) on, like YouTube and Gmail.
- **Classified Outputs** - Categorizes texts, thoughts, web images and AI generated images in the response.
- **Official Flavor** - Provides a simple and elegant interface inspired by [Google Generative AI](https://ai.google.dev/tutorials/python_quickstart)'s official API.
- **Asynchronous** - Utilizes `asyncio` to run generating tasks and return outputs efficiently.

## Table of Contents

- [Features](#features)
- [Table of Contents](#table-of-contents)
- [Installation](#installation)
- [Authentication](#authentication)
- [Usage](#usage)
  - [Initialization](#initialization)
  - [Generate contents](#generate-contents)
  - [Generate contents with files](#generate-contents-with-files)
  - [Stream contents in real-time](#stream-contents-in-real-time)
    - [Basic streaming](#basic-streaming)
    - [Streaming with chat sessions](#streaming-with-chat-sessions)
    - [Advanced streaming usage](#advanced-streaming-usage)
    - [Streaming with thinking models](#streaming-with-thinking-models)
  - [Conversations across multiple turns](#conversations-across-multiple-turns)
  - [Continue previous conversations](#continue-previous-conversations)
  - [Select language model](#select-language-model)
  - [Apply system prompt with Gemini Gems](#apply-system-prompt-with-gemini-gems)
  - [Manage Custom Gems](#manage-custom-gems)
    - [Create a custom gem](#create-a-custom-gem)
    - [Update an existing gem](#update-an-existing-gem)
    - [Delete a custom gem](#delete-a-custom-gem)
  - [Retrieve model's thought process](#retrieve-models-thought-process)
  - [Retrieve images in response](#retrieve-images-in-response)
  - [Generate images with Imagen4](#generate-images-with-imagen4)
  - [Generate contents with Gemini extensions](#generate-contents-with-gemini-extensions)
  - [Check and switch to other reply candidates](#check-and-switch-to-other-reply-candidates)
  - [Logging Configuration](#logging-configuration)
- [References](#references)
- [Stargazers](#stargazers)

## Installation

> [!NOTE]
>
> This package requires Python 3.10 or higher.

Install/update the package with pip.

```sh
pip install -U gemini_webapi
```

Optionally, package offers a way to automatically import cookies from your local browser. To enable this feature, install `browser-cookie3` as well. Supported platforms and browsers can be found [here](https://github.com/borisbabic/browser_cookie3?tab=readme-ov-file#contribute).

```sh
pip install -U browser-cookie3
```

## Authentication

> [!TIP]
>
> If `browser-cookie3` is installed, you can skip this step and go directly to [usage](#usage) section. Just make sure you have logged in to <https://gemini.google.com> in your browser.

- Go to <https://gemini.google.com> and login with your Google account
- Press F12 for web inspector, go to `Network` tab and refresh the page
- Click any request and copy cookie values of `__Secure-1PSID` and `__Secure-1PSIDTS`

> [!NOTE]
>
> If your application is deployed in a containerized environment (e.g. Docker), you may want to persist the cookies with a volume to avoid re-authentication every time the container rebuilds.
>
> Here's part of a sample `docker-compose.yml` file:

```yaml
services:
    main:
        volumes:
            - ./gemini_cookies:/usr/local/lib/python3.12/site-packages/gemini_webapi/utils/temp
```

> [!NOTE]
>
> API's auto cookie refreshing feature doesn't require `browser-cookie3`, and by default is enabled. It allows you to keep the API service running without worrying about cookie expiration.
>
> This feature may cause that you need to re-login to your Google account in the browser. This is an expected behavior and won't affect the API's functionality.
>
> To avoid such result, it's recommended to get cookies from a separate browser session and close it as asap for best utilization (e.g. a fresh login in browser's private mode). More details can be found [here](https://github.com/HanaokaYuzu/Gemini-API/issues/6).

## Usage

### Initialization

Import required packages and initialize a client with your cookies obtained from the previous step. After a successful initialization, the API will automatically refresh `__Secure-1PSIDTS` in background as long as the process is alive.

```python
import asyncio
from gemini_webapi import GeminiClient

# Replace "COOKIE VALUE HERE" with your actual cookie values.
# Leave Secure_1PSIDTS empty if it's not available for your account.
Secure_1PSID = "COOKIE VALUE HERE"
Secure_1PSIDTS = "COOKIE VALUE HERE"

async def main():
    # If browser-cookie3 is installed, simply use `client = GeminiClient()`
    client = GeminiClient(Secure_1PSID, Secure_1PSIDTS, proxy=None)
    await client.init(timeout=30, auto_close=False, close_delay=300, auto_refresh=True)

asyncio.run(main())
```

> [!TIP]
>
> `auto_close` and `close_delay` are optional arguments for automatically closing the client after a certain period of inactivity. This feature is disabled by default. In an always-on service like chatbot, it's recommended to set `auto_close` to `True` combined with reasonable seconds of `close_delay` for better resource management.

### Generate contents

Ask a single-turn question by calling `GeminiClient.generate_content`, which returns a `gemini_webapi.ModelOutput` object containing the generated text, images, thoughts, and conversation metadata.

```python
async def main():
    response = await client.generate_content("Hello World!")
    print(response.text)

asyncio.run(main())
```

> [!TIP]
>
> Simply use `print(response)` to get the same output if you just want to see the response text

### Generate contents with files

Gemini supports file input, including images and documents. Optionally, you can pass files as a list of paths in `str` or `pathlib.Path` to `GeminiClient.generate_content` together with text prompt.

```python
async def main():
    response = await client.generate_content(
            "Introduce the contents of these two files. Is there any connection between them?",
            files=["assets/sample.pdf", Path("assets/banner.png")],
        )
    print(response.text)

asyncio.run(main())
```

### Stream contents in real-time

For applications that need real-time response updates (like chatbots or live interfaces), you can use streaming to receive partial responses as they are generated. This provides a more responsive user experience.

#### Basic streaming

Use `GeminiClient.generate_content_stream` to get a streaming response that yields chunks as they arrive:

```python
async def main():
    # Generate content with streaming
    stream = await client.generate_content_stream("Write a long story about a brave knight")
    
    # Iterate through chunks as they arrive
    async for chunk in stream:
        if chunk.delta_text:  # Only print new text
            print(chunk.delta_text, end="", flush=True)
        
        if chunk.is_final:
            print("\n\n[Stream completed]")
            break

asyncio.run(main())
```

#### Streaming with chat sessions

You can also use streaming within chat sessions for continuous conversations:

```python
async def main():
    chat = client.start_chat()
    
    # Send a message with streaming
    stream = await chat.send_message_stream("Tell me about artificial intelligence")
    
    full_response = ""
    async for chunk in stream:
        if chunk.delta_text:
            print(chunk.delta_text, end="", flush=True)
            full_response += chunk.delta_text
        
        if chunk.is_final:
            print(f"\n\nComplete response: {full_response}")
            break
    
    # Continue the conversation normally
    response = await chat.send_message("Can you summarize what you just told me?")
    print(f"Summary: {response.text}")

asyncio.run(main())
```

#### Advanced streaming usage

For more control, you can collect the full response while still processing chunks:

```python
async def main():
    stream = await client.generate_content_stream(
        "Explain quantum computing in simple terms",
        model="gemini-2.5-flash"
    )
    
    # Process chunks and collect full response
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
        
        # Show real-time progress
        if chunk.delta_text:
            print(f"[{len(chunk.text)} chars] {chunk.delta_text}", end="")
        
        if chunk.is_final:
            break
    
    # Convert stream to ModelOutput for compatibility
    final_output = await stream.collect()
    print(f"\n\nFinal output: {final_output.text}")
    print(f"Metadata: {final_output.metadata}")

asyncio.run(main())
```

> [!TIP]
>
> - Use `chunk.delta_text` to get only the new text added in the current chunk
> - Use `chunk.text` to get the accumulated text so far
> - Use `chunk.is_final` to detect when the stream is complete
> - Call `stream.collect()` to get a complete `ModelOutput` from the stream

#### Streaming with thinking models

When using models with thinking capabilities (like Gemini 2.5 Pro), you can access the model's thought process in real-time through `chunk.delta_thoughts`:

```python
async def main():
    stream = await client.generate_content_stream(
        "Solve this physics problem: A block with mass 10kg slides onto a conveyor belt...",
        model="gemini-2.5-pro"
    )
    
    async for chunk in stream:
        # Display new thoughts as they arrive
        if chunk.delta_thoughts:
            print(f"\n[Thinking]: {chunk.delta_thoughts}", end="", flush=True)
        
        # Display new text content
        if chunk.delta_text:
            print(chunk.delta_text, end="", flush=True)
        
        if chunk.is_final:
            break
    
    print("\n\n[Completed]")

asyncio.run(main())
```

**StreamChunk Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `text` | `str` | Accumulated text content from the start |
| `delta_text` | `str` | New text added in this chunk only |
| `thoughts` | `str \| None` | Accumulated thought process from the start |
| `delta_thoughts` | `str` | New thought process added in this chunk only |
| `is_final` | `bool` | Whether this is the final chunk |
| `metadata` | `list[str \| None]` | Chat metadata (10-element array: `[cid, rid, rcid, None*6, token]`) |
| `candidates` | `list[Candidate]` | Response candidates if available |

> [!NOTE]
>
> - Only Gemini 2.5 Pro (`Model.G_2_5_PRO`) currently supports thought process output
> - Use `delta_thoughts` for incremental updates to avoid repeating content
> - Thoughts and text may arrive in interleaved chunks

### Conversations across multiple turns

If you want to keep conversation continuous, please use `GeminiClient.start_chat` to create a `gemini_webapi.ChatSession` object and send messages through it. The conversation history will be automatically handled and get updated after each turn.

```python
async def main():
    chat = client.start_chat()
    response1 = await chat.send_message(
        "Introduce the contents of these two files. Is there any connection between them?",
        files=["assets/sample.pdf", Path("assets/banner.png")],
    )
    print(response1.text)
    response2 = await chat.send_message(
        "Use image generation tool to modify the banner with another font and design."
    )
    print(response2.text, response2.images, sep="\n\n----------------------------------\n\n")

asyncio.run(main())
```

> [!TIP]
>
> Same as `GeminiClient.generate_content`, `ChatSession.send_message` also accepts `image` as an optional argument.

### Continue previous conversations

To manually retrieve previous conversations, you can pass previous `ChatSession`'s metadata to `GeminiClient.start_chat` when creating a new `ChatSession`. Alternatively, you can persist previous metadata to a file or db if you need to access them after the current Python process has exited.

```python
async def main():
    # Start a new chat session
    chat = client.start_chat()
    response = await chat.send_message("Fine weather today")

    # Save chat's metadata
    previous_session = chat.metadata

    # Load the previous conversation
    previous_chat = client.start_chat(metadata=previous_session)
    response = await previous_chat.send_message("What was my previous message?")
    print(response)

asyncio.run(main())
```

### Select language model

You can specify which language model to use by passing `model` argument to `GeminiClient.generate_content` or `GeminiClient.start_chat`. The default value is `unspecified`.

Currently available models (as of June 12, 2025):

- `unspecified` - Default model
- `gemini-2.5-flash` - Gemini 2.5 Flash
- `gemini-2.5-pro` - Gemini 2.5 Pro (daily usage limit imposed)

Deprecated models (yet still working):

- `gemini-2.0-flash` - Gemini 2.0 Flash
- `gemini-2.0-flash-thinking` - Gemini 2.0 Flash Thinking

```python
from gemini_webapi.constants import Model

async def main():
    response1 = await client.generate_content(
        "What's you language model version? Reply version number only.",
        model=Model.G_2_5_FLASH,
    )
    print(f"Model version ({Model.G_2_5_FLASH.model_name}): {response1.text}")

    chat = client.start_chat(model="gemini-2.5-pro")
    response2 = await chat.send_message("What's you language model version? Reply version number only.")
    print(f"Model version (gemini-2.5-pro): {response2.text}")

asyncio.run(main())
```

### Apply system prompt with Gemini Gems

System prompt can be applied to conversations via [Gemini Gems](https://gemini.google.com/gems/view). To use a gem, you can pass `gem` argument to `GeminiClient.generate_content` or `GeminiClient.start_chat`. `gem` can be either a string of gem id or a `gemini_webapi.Gem` object. Only one gem can be applied to a single conversation.

> [!TIP]
>
> There are some system predefined gems that by default are not shown to users (and therefore may not work properly). Use `client.fetch_gems(include_hidden=True)` to include them in the fetch result.

```python
async def main():
    # Fetch all gems for the current account, including both predefined and user-created ones
    await client.fetch_gems(include_hidden=False)

    # Once fetched, gems will be cached in `GeminiClient.gems`
    gems = client.gems

    # Get the gem you want to use
    system_gems = gems.filter(predefined=True)
    coding_partner = system_gems.get(id="coding-partner")

    response1 = await client.generate_content(
        "what's your system prompt?",
        model=Model.G_2_5_FLASH,
        gem=coding_partner,
    )
    print(response1.text)

    # Another example with a user-created custom gem
    # Gem ids are consistent strings. Store them somewhere to avoid fetching gems every time
    your_gem = gems.get(name="Your Gem Name")
    your_gem_id = your_gem.id
    chat = client.start_chat(gem=your_gem_id)
    response2 = await chat.send_message("what's your system prompt?")
    print(response2)
```

### Manage Custom Gems

You can create, update, and delete your custom gems programmatically with the API. Note that predefined system gems cannot be modified or deleted.

#### Create a custom gem

Create a new custom gem with a name, system prompt (instructions), and optional description:

```python
async def main():
    # Create a new custom gem
    new_gem = await client.create_gem(
        name="Python Tutor",
        prompt="You are a helpful Python programming tutor.",
        description="A specialized gem for Python programming"
    )

    print(f"Custom gem created: {new_gem}")

    # Use the newly created gem in a conversation
    response = await client.generate_content(
        "Explain how list comprehensions work in Python",
        gem=new_gem
    )
    print(response.text)

asyncio.run(main())
```

#### Update an existing gem

> [!NOTE]
>
> When updating a gem, you must provide all parameters (name, prompt, description) even if you only want to change one of them.

```python
async def main():
    # Get a custom gem (assuming you have one named "Python Tutor")
    await client.fetch_gems()
    python_tutor = client.gems.get(name="Python Tutor")

    # Update the gem with new instructions
    updated_gem = await client.update_gem(
        gem=python_tutor,  # Can also pass gem ID string
        name="Advanced Python Tutor",
        prompt="You are an expert Python programming tutor.",
        description="An advanced Python programming assistant"
    )

    print(f"Custom gem updated: {updated_gem}")

asyncio.run(main())
```

#### Delete a custom gem

```python
async def main():
    # Get the gem to delete
    await client.fetch_gems()
    gem_to_delete = client.gems.get(name="Advanced Python Tutor")

    # Delete the gem
    await client.delete_gem(gem_to_delete)  # Can also pass gem ID string
    print(f"Custom gem deleted: {gem_to_delete.name}")

asyncio.run(main())
```

### Retrieve model's thought process

When using models with thinking capabilities, the model's thought process will be populated in `ModelOutput.thoughts`.

```python
async def main():
    response = await client.generate_content(
            "What's 1+1?", model="gemini-2.5-pro"
        )
    print(response.thoughts)
    print(response.text)

asyncio.run(main())
```

### Retrieve images in response

Images in the API's output are stored as a list of `gemini_webapi.Image` objects. You can access the image title, URL, and description by calling `Image.title`, `Image.url` and `Image.alt` respectively.

```python
async def main():
    response = await client.generate_content("Send me some pictures of cats")
    for image in response.images:
        print(image, "\n\n----------------------------------\n")

asyncio.run(main())
```

### Generate images with Imagen4

You can ask Gemini to generate and modify images with Imagen4, Google's latest AI image generator, simply by natural language.

> [!IMPORTANT]
>
> Google has some limitations on the image generation feature in Gemini, so its availability could be different per region/account. Here's a summary copied from [official documentation](https://support.google.com/gemini/answer/14286560) (as of March 19th, 2025):
>
> > This feature’s availability in any specific Gemini app is also limited to the supported languages and countries of that app.
> >
> > For now, this feature isn’t available to users under 18.
> >
> > To use this feature, you must be signed in to Gemini Apps.

You can save images returned from Gemini to local by calling `Image.save()`. Optionally, you can specify the file path and file name by passing `path` and `filename` arguments to the function and skip images with invalid file names by passing `skip_invalid_filename=True`. Works for both `WebImage` and `GeneratedImage`.

```python
async def main():
    response = await client.generate_content("Generate some pictures of cats")
    for i, image in enumerate(response.images):
        await image.save(path="temp/", filename=f"cat_{i}.png", verbose=True)
        print(image, "\n\n----------------------------------\n")

asyncio.run(main())
```

> [!NOTE]
>
> by default, when asked to send images (like the previous example), Gemini will send images fetched from web instead of generating images with AI model, unless you specifically require to "generate" images in your prompt. In this package, web images and generated images are treated differently as `WebImage` and `GeneratedImage`, and will be automatically categorized in the output.

### Generate contents with Gemini extensions

> [!IMPORTANT]
>
> To access Gemini extensions in API, you must activate them on the [Gemini website](https://gemini.google.com/extensions) first. Same as image generation, Google also has limitations on the availability of Gemini extensions. Here's a summary copied from [official documentation](https://support.google.com/gemini/answer/13695044) (as of March 19th, 2025):
>
> > To connect apps to Gemini, you must have​​​​ Gemini Apps Activity on.
> >
> > To use this feature, you must be signed in to Gemini Apps.
> >
> > Important: If you’re under 18, Google Workspace and Maps apps currently only work with English prompts in Gemini.

After activating extensions for your account, you can access them in your prompts either by natural language or by starting your prompt with "@" followed by the extension keyword.

```python
async def main():
    response1 = await client.generate_content("@Gmail What's the latest message in my mailbox?")
    print(response1, "\n\n----------------------------------\n")

    response2 = await client.generate_content("@Youtube What's the latest activity of Taylor Swift?")
    print(response2, "\n\n----------------------------------\n")

asyncio.run(main())
```

> [!NOTE]
>
> For the available regions limitation, it actually only requires your Google account's **preferred language** to be set to one of the three supported languages listed above. You can change your language settings [here](https://myaccount.google.com/language).

### Check and switch to other reply candidates

A response from Gemini sometimes contains multiple reply candidates with different generated contents. You can check all candidates and choose one to continue the conversation. By default, the first candidate will be chosen.

```python
async def main():
    # Start a conversation and list all reply candidates
    chat = client.start_chat()
    response = await chat.send_message("Recommend a science fiction book for me.")
    for candidate in response.candidates:
        print(candidate, "\n\n----------------------------------\n")

    if len(response.candidates) > 1:
        # Control the ongoing conversation flow by choosing candidate manually
        new_candidate = chat.choose_candidate(index=1)  # Choose the second candidate here
        followup_response = await chat.send_message("Tell me more about it.")  # Will generate contents based on the chosen candidate
        print(new_candidate, followup_response, sep="\n\n----------------------------------\n\n")
    else:
        print("Only one candidate available.")

asyncio.run(main())
```

### Logging Configuration

This package uses [loguru](https://loguru.readthedocs.io/en/stable/) for logging, and exposes a function `set_log_level` to control log level. You can set log level to one of the following values: `DEBUG`, `INFO`, `WARNING`, `ERROR` and `CRITICAL`. The default value is `INFO`.

```python
from gemini_webapi import set_log_level

set_log_level("DEBUG")
```

> [!NOTE]
>
> Calling `set_log_level` for the first time will **globally** remove all existing loguru handlers. You may want to configure logging directly with loguru to avoid this issue and have more advanced control over logging behaviors.

## References

[Google AI Studio](https://ai.google.dev/tutorials/ai-studio_quickstart)

[acheong08/Bard](https://github.com/acheong08/Bard)

## Stargazers

<p align="center">
    <a href="https://star-history.com/#HanaokaYuzu/Gemini-API">
        <img src="https://api.star-history.com/svg?repos=HanaokaYuzu/Gemini-API&type=Date" width="75%" alt="Star History Chart"></a>
</p>