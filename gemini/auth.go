package gemini

import (
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
)

var snlm0ePattern = regexp.MustCompile(`"SNlM0e":"(.*?)"`)
var cfb2hPattern = regexp.MustCompile(`"cfb2h":"(.*?)"`)
var fdrfjePattern = regexp.MustCompile(`"FdrFJe":"(.*?)"`)

// GetAccessToken retrieves the SNlM0e token and other session info.
func GetAccessToken(client *http.Client) (string, string, string, error) {
	req, err := http.NewRequest("GET", EndpointInit, nil)
	if err != nil {
		return "", "", "", err
	}

	// Add headers
	for k, v := range HeadersGemini {
		req.Header.Set(k, v)
	}

	resp, err := client.Do(req)
	if err != nil {
		return "", "", "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return "", "", "", fmt.Errorf("failed to get access token, status code: %d", resp.StatusCode)
	}

	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", "", "", err
	}
	body := string(bodyBytes)

	snlm0eMatch := snlm0ePattern.FindStringSubmatch(body)
	if len(snlm0eMatch) < 2 {
		return "", "", "", fmt.Errorf("SNlM0e not found")
	}
	snlm0e := snlm0eMatch[1]

	cfb2h := ""
	cfb2hMatch := cfb2hPattern.FindStringSubmatch(body)
	if len(cfb2hMatch) >= 2 {
		cfb2h = cfb2hMatch[1]
	}

	fdrfje := ""
	fdrfjeMatch := fdrfjePattern.FindStringSubmatch(body)
	if len(fdrfjeMatch) >= 2 {
		fdrfje = fdrfjeMatch[1]
	}

	return snlm0e, cfb2h, fdrfje, nil
}

// Rotate1PSIDTS refreshes the __Secure-1PSIDTS cookie.
func Rotate1PSIDTS(client *http.Client) (string, []*http.Cookie, error) {
	req, err := http.NewRequest("POST", EndpointRotateCookies, strings.NewReader(`[000,"-0000000000000000000"]`))
	if err != nil {
		return "", nil, err
	}

	for k, v := range HeadersRotateCookies {
		req.Header.Set(k, v)
	}

	resp, err := client.Do(req)
	if err != nil {
		return "", nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return "", nil, fmt.Errorf("failed to rotate cookies, status: %s", resp.Status)
	}

	var newPSIDTS string
	for _, c := range resp.Cookies() {
		if c.Name == "__Secure-1PSIDTS" {
			newPSIDTS = c.Value
		}
	}

	return newPSIDTS, resp.Cookies(), nil
}
