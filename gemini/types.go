package gemini

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Image represents a single image object returned from Gemini.
type Image struct {
	URL   string
	Title string
	Alt   string
	Proxy string // Optional proxy URL
}

func (i Image) String() string {
	url := i.URL
	if len(url) > 20 {
		url = url[:8] + "..." + url[len(url)-12:]
	}
	return fmt.Sprintf("Image(title='%s', alt='%s', url='%s')", i.Title, i.Alt, url)
}

// Save saves the image to disk.
func (i *Image) Save(path string, filename string, cookies []*http.Cookie, skipInvalidFilename bool) (string, error) {
	if filename == "" {
		parts := strings.Split(i.URL, "/")
		lastPart := parts[len(parts)-1]
		filename = strings.Split(lastPart, "?")[0]
	}

	// Basic validation logic would go here, simplified for now
	if path == "" {
		path = "temp"
	}

	if err := os.MkdirAll(path, 0755); err != nil {
		return "", err
	}

	dest := filepath.Join(path, filename)
	client := &http.Client{}
    // Proxy support would be added here to the transport

	req, err := http.NewRequest("GET", i.URL, nil)
	if err != nil {
		return "", err
	}

	if cookies != nil {
		for _, c := range cookies {
			req.AddCookie(c)
		}
	}

	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return "", fmt.Errorf("error downloading image: %s", resp.Status)
	}

	out, err := os.Create(dest)
	if err != nil {
		return "", err
	}
	defer out.Close()

	_, err = io.Copy(out, resp.Body)
	if err != nil {
		return "", err
	}

	return dest, nil
}

// WebImage is an alias for Image
type WebImage struct {
    Image
}

// GeneratedImage is an alias for Image but with cookies support
type GeneratedImage struct {
	Image
	Cookies []*http.Cookie
}

// Save overrides Image.Save to use internal cookies if not provided
func (g *GeneratedImage) Save(path string, filename string, cookies []*http.Cookie, skipInvalidFilename bool, fullSize bool) (string, error) {
	url := g.URL
	if fullSize {
		url += "=s2048"
	}
    // We create a temporary image with the modified URL to call the base Save
    tempImg := Image{
        URL: url,
        Title: g.Title,
        Alt: g.Alt,
        Proxy: g.Proxy,
    }

    useCookies := cookies
    if useCookies == nil {
        useCookies = g.Cookies
    }

    if filename == "" {
        // Simple timestamp generation
        timestamp := time.Now().Format("20060102150405")
        hashPart := ""
        if len(url) >= 10 {
            hashPart = url[len(url)-10:]
        }
        filename = fmt.Sprintf("%s_%s.png", timestamp, hashPart)
    }

	return tempImg.Save(path, filename, useCookies, skipInvalidFilename)
}

// Candidate represents a single reply candidate object.
type Candidate struct {
	RCID            string
	Text            string
	TextDelta       string
	Thoughts        string
	ThoughtsDelta   string
	WebImages       []WebImage
	GeneratedImages []GeneratedImage
}

func (c Candidate) String() string {
	return c.Text
}

// ModelOutput represents classified output from Gemini.
type ModelOutput struct {
	Metadata   []string
	Candidates []Candidate
	Chosen     int
}

func (m ModelOutput) String() string {
	if len(m.Candidates) > m.Chosen {
		return m.Candidates[m.Chosen].Text
	}
	return ""
}

// Text returns the text of the chosen candidate
func (m ModelOutput) Text() string {
	if len(m.Candidates) > m.Chosen {
		return m.Candidates[m.Chosen].Text
	}
	return ""
}

// Images returns the images of the chosen candidate
func (m ModelOutput) Images() []Image {
	if len(m.Candidates) > m.Chosen {
		c := m.Candidates[m.Chosen]
		images := make([]Image, 0, len(c.WebImages)+len(c.GeneratedImages))
		for _, wi := range c.WebImages {
			images = append(images, wi.Image)
		}
		for _, gi := range c.GeneratedImages {
			images = append(images, gi.Image)
		}
		return images
	}
	return nil
}

// Gem represents a Reusable Gemini Gem object.
type Gem struct {
	ID          string  `json:"id"`
	Name        string  `json:"name"`
	Description string  `json:"description,omitempty"`
	Prompt      string  `json:"prompt,omitempty"`
	Predefined  bool    `json:"predefined"`
}

func (g Gem) String() string {
	return fmt.Sprintf("Gem(id='%s', name='%s', predefined=%v)", g.ID, g.Name, g.Predefined)
}

// RPCData helper struct for Google RPC calls.
type RPCData struct {
	RPCID      string
	Payload    string
	Identifier string
}

func (r RPCData) Serialize() []interface{} {
	return []interface{}{r.RPCID, r.Payload, nil, r.Identifier}
}

// GemJar is a helper for handling a collection of Gem objects.
type GemJar map[string]Gem

func (j GemJar) Get(id string, name string) (Gem, bool) {
	if id != "" {
		if gem, ok := j[id]; ok {
			if name != "" && gem.Name != name {
				return Gem{}, false
			}
			return gem, true
		}
	} else if name != "" {
		for _, gem := range j {
			if gem.Name == name {
				return gem, true
			}
		}
	}
	return Gem{}, false
}

func (j GemJar) Filter(predefined *bool, name *string) GemJar {
	filtered := make(GemJar)
	for id, gem := range j {
		if predefined != nil && gem.Predefined != *predefined {
			continue
		}
		if name != nil && gem.Name != *name {
			continue
		}
		filtered[id] = gem
	}
	return filtered
}
