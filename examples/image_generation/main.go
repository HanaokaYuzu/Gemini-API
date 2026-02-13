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

	prompt := "Generate a picture of a futuristic city in cyberpunk style."
	fmt.Printf("User: %s\n", prompt)

	response, err := client.GenerateContent(prompt)
	if err != nil {
		log.Fatalf("Error generating content: %v", err)
	}

	fmt.Printf("Gemini: %s\n", response.Text())

	images := response.Images()
	if len(images) > 0 {
		fmt.Printf("Found %d images:\n", len(images))
		for i, img := range images {
			fmt.Printf("Image %d: %s\n", i+1, img.URL)
			// Save the image
			path, err := img.Save("output_images", fmt.Sprintf("image_%d.png", i), nil, false)
			if err != nil {
				log.Printf("Failed to save image: %v", err)
			} else {
				fmt.Printf("Saved image to: %s\n", path)
			}
		}
	} else {
		fmt.Println("No images generated.")
	}
}
