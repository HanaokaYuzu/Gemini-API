# <img src="https://www.gstatic.com/lamda/images/favicon_v1_150160cddff7f294ce30.svg" width="35px" alt="Gemini Icon" /> Gemini-API

Reverse-engineered asynchronous python wrapper for Google Gemini (formerly Bard) web client, providing a simple and elegant interface inspired by Google GenerativeAI's official API.

## Installation

```bash
pip install gemini-webapi
```

## Authentication

- Go to <https://gemini.google.com/> and login with your Google account
- Press F12 for web inspector, go to `Network` tab and refresh the page
- Click any request and copy cookie values of `__Secure-1PSID` and `__Secure-1PSIDTS`

## Usage

### Initialization

```python
from gemini import GeminiClient

# Replace "COOKIE VALUE HERE" with your actual cookie values as strings
Secure_1PSID = "COOKIE VALUE HERE"
Secure_1PSIDTS = "COOKIE VALUE HERE"

client = GeminiClient(Secure_1PSID, Secure_1PSIDTS, proxy=None)
await client.init()
```

### Generate contents from text inputs

```python
response = await client.generate_content("Hello World!")
print(response.text)  # Note: simply use print(response) to get the same output if you just want to see the response text
```

### Retrieve images in response

```python
response = await client.generate_content("Send me some pictures of cats")
images = response.images
for image in images:
    print(f"{image.title}({image.url}) - {image.alt}", sep="\n")
```

### Conversations across multiple turns

```python
chat = client.start_chat()  # A chat stores the metadata to keep a conversation continuous. It will automatically get updated after each turn
response1 = await chat.send_message("Briefly introduce Europe")
response2 = await chat.send_message("What's the population there?")
print(response1.text, response2.text, sep="\n----------------------------------\n")
```

### Check and switch to other answer candidates

```python
chat = client.start_chat()
response = await chat.send_message("What's the best Japanese dish in your mind? Choose one only.")
for candidate in response.candidates:
    print(candidate, "\n----------------------------------\n")

# Control the ongoing conversation flow by choosing candidate manually
new_candidate = chat.choose_candidate(index=1) # Choose the second candidate here
followup_response = await chat.send_message("Tell me more about it.")  # Will generate contents based on the chosen candidate
print(new_candidate, followup_response, sep="\n----------------------------------\n")
```
