package main

import (
	"fmt"
	"log"
	"os"

	"github.com/HanaokaYuzu/gemini-webapi-go/gemini"
)

func main() {
	// Replace with your actual cookie values
	secure1PSID := os.Getenv("GEMINI_1PSID")
	secure1PSIDTS := os.Getenv("GEMINI_1PSIDTS")

	if secure1PSID == "" || secure1PSIDTS == "" {
		log.Fatal("Please set GEMINI_1PSID and GEMINI_1PSIDTS environment variables")
	}

	client, err := gemini.NewClient(secure1PSID, secure1PSIDTS, "")
	if err != nil {
		log.Fatalf("Failed to create client: %v", err)
	}

	if err := client.Init(); err != nil {
		log.Fatalf("Failed to initialize client: %v", err)
	}

	fmt.Println("Client initialized successfully!")

	// Simple chat example
	chat := client.StartChat()
	response, err := chat.SendMessage("Hello, Gemini! Tell me a short joke.")
	if err != nil {
		log.Fatalf("Error sending message: %v", err)
	}

	fmt.Printf("Gemini: %s\n", response.Text())
}
