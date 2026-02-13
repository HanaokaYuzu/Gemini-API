<p align="center">
    <img src="https://raw.githubusercontent.com/HanaokaYuzu/Gemini-API/master/assets/banner.png" width="55%" alt="Gemini Banner" align="center">
</p>

# Gemini-API (Go)

A reverse-engineered asynchronous Go wrapper for [Google Gemini](https://gemini.google.com) web app (formerly Bard).

> **Note:** This is a Go port of the original [Python library](https://github.com/HanaokaYuzu/Gemini-API).

## Features

- **Persistent Cookies** - Automatically refreshes cookies in background. Optimized for always-on services.
- **Image Generation** - Natively supports generating and editing images with natural language.
- **Extension Support** - Supports generating contents with Gemini extensions (YouTube, Gmail, etc).
- **Streaming Mode** - Supports stream generation, yielding partial outputs as they are generated.
- **Asynchronous** - Built on standard Go `net/http` and goroutines.

## Installation

```sh
go get github.com/HanaokaYuzu/gemini-webapi-go
```

## Authentication

1.  Go to <https://gemini.google.com> and login with your Google account.
2.  Press F12 for web inspector, go to `Network` tab and refresh the page.
3.  Click any request and copy cookie values of `__Secure-1PSID` and `__Secure-1PSIDTS`.

## Usage

### Initialization

```go
package main

import (
	"log"
	"os"

	"github.com/HanaokaYuzu/gemini-webapi-go/gemini"
)

func main() {
	secure1PSID := "YOUR_SECURE_1PSID"
	secure1PSIDTS := "YOUR_SECURE_1PSIDTS"

	client, err := gemini.NewClient(secure1PSID, secure1PSIDTS, "")
	if err != nil {
		log.Fatal(err)
	}

	if err := client.Init(); err != nil {
		log.Fatal(err)
	}
}
```

### Chat

```go
chat := client.StartChat()
response, err := chat.SendMessage("Hello, Gemini!")
if err != nil {
    log.Fatal(err)
}
fmt.Println(response.Text())
```

### Streaming Chat

```go
chat := client.StartChat()
outChan := make(chan gemini.ModelOutput)
errChan := make(chan error)

go func() {
    defer close(outChan)
    defer close(errChan)
    if err := chat.SendMessageStream("Tell me a story", outChan); err != nil {
        errChan <- err
    }
}()

for out := range outChan {
    if len(out.Candidates) > 0 {
        fmt.Print(out.Candidates[0].TextDelta)
    }
}
```

### Image Generation

```go
response, err := client.GenerateContent("Generate a picture of a cat")
if err != nil {
    log.Fatal(err)
}

for _, img := range response.Images() {
    fmt.Printf("Image URL: %s\n", img.URL)
    // img.Save("path/to/save", "filename.png", nil, false)
}
```

## Disclaimer

This is a reverse-engineered library and is not affiliated with Google. Use at your own risk.
