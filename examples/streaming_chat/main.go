package main

import (
	"fmt"
	"log"
	"os"

	"github.com/HanaokaYuzu/gemini-webapi-go/gemini"
)

func main() {
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

	chat := client.StartChat()
	outChan := make(chan gemini.ModelOutput)
	errChan := make(chan error)

	prompt := "Write a short poem about coding in Go."

	go func() {
		defer close(outChan)
		defer close(errChan)
		if err := chat.SendMessageStream(prompt, outChan); err != nil {
			errChan <- err
		}
	}()

	fmt.Printf("User: %s\n", prompt)
	fmt.Print("Gemini: ")

	for out := range outChan {
		if len(out.Candidates) > 0 {
			fmt.Print(out.Candidates[0].TextDelta)
		}
	}
	fmt.Println()

	// Check for errors
	select {
	case err := <-errChan:
		if err != nil {
			log.Fatalf("Error streaming message: %v", err)
		}
	default:
	}
}
