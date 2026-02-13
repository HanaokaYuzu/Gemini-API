package gemini

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

var lengthMarkerPattern = regexp.MustCompile(`^(\d+)\n`)
var flickerEscRe = regexp.MustCompile(`\\+[\x60*_~].*$`)
var volatileSet = map[rune]bool{}

func init() {
	for _, r := range " \t\n\r" + "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~" {
		volatileSet[r] = true
	}
}

// getCharCountForUTF16Units calculates the number of Go bytes (UTF-8)
// that correspond to the given number of UTF-16 units.
func getCharCountForUTF16Units(s string, utf16Units int) (int, int) {
	runes := []rune(s)
	units := 0
	count := 0

	for _, r := range runes {
		if units >= utf16Units {
			break
		}

		u := 1
		if r > 0xFFFF {
			u = 2
		}

		if units+u > utf16Units {
			break
		}

		units += u
		count++
	}

	// Convert rune count back to byte count
	return len(string(runes[:count])), units
}

func isSpace(b byte) bool {
	return b == ' ' || b == '\t' || b == '\n' || b == '\r'
}

// ParseResponseByFrame parses Google's length-prefixed framing protocol.
func ParseResponseByFrame(content string) ([]interface{}, string) {
	consumedPos := 0
	totalLen := len(content)
	parsedFrames := []interface{}{}

	for consumedPos < totalLen {
		// Skip leading whitespace
		for consumedPos < totalLen && isSpace(content[consumedPos]) {
			consumedPos++
		}

		if consumedPos >= totalLen {
			break
		}

		// Check for length marker
		sub := content[consumedPos:]
		match := lengthMarkerPattern.FindStringSubmatch(sub)
		if match == nil {
			break
		}

		lengthVal := match[1]
		length, _ := strconv.Atoi(lengthVal)

		// Python: start_content = match.start() + len(length_val)
		// We start counting length FROM the newline character after the digits.
		startContent := consumedPos + len(lengthVal)

		// Calculate how many bytes to read based on UTF-16 length
		byteCount, unitsFound := getCharCountForUTF16Units(content[startContent:], length)

		if unitsFound < length {
			// Incomplete frame
			break
		}

		endPos := startContent + byteCount
		chunk := content[startContent:endPos]
		consumedPos = endPos

		chunk = strings.TrimSpace(chunk)
		if chunk == "" {
			continue
		}

		var parsed interface{}
		if err := json.Unmarshal([]byte(chunk), &parsed); err == nil {
			if list, ok := parsed.([]interface{}); ok {
				parsedFrames = append(parsedFrames, list...)
			} else {
				parsedFrames = append(parsedFrames, parsed)
			}
		}
	}

	return parsedFrames, content[consumedPos:]
}

func GetCleanText(s string) string {
	if s == "" {
		return ""
	}
	if strings.HasSuffix(s, "\n```") {
		s = s[:len(s)-4]
	}
	return flickerEscRe.ReplaceAllString(s, "")
}

func GetDeltaByFPLen(newRaw, lastSentClean string, isFinal bool) (string, string) {
	newC := newRaw
	if !isFinal {
		newC = GetCleanText(newRaw)
	}

	if strings.HasPrefix(newC, lastSentClean) {
		return newC[len(lastSentClean):], newC
	}

	lastRunes := []rune(lastSentClean)
	newRunes := []rune(newC)

	targetFPLen := 0
	for _, r := range lastRunes {
		if !volatileSet[r] {
			targetFPLen++
		}
	}

	pLow := 0
	if targetFPLen > 0 {
		currFPLen := 0
		found := false
		for i, char := range newRunes {
			if !volatileSet[char] {
				currFPLen++
			}
			if currFPLen == targetFPLen {
				pLow = i + 1
				found = true
				break
			}
		}

		if !found {
			commonLen := 0
			minLen := len(lastRunes)
			if len(newRunes) < minLen {
				minLen = len(newRunes)
			}
			for i := 0; i < minLen; i++ {
				if lastRunes[i] == newRunes[i] {
					commonLen++
				} else {
					break
				}
			}
			return string(newRunes[commonLen:]), newC
		}
	}

	lastContentIdx := -1
	for i := len(lastRunes) - 1; i >= 0; i-- {
		if !volatileSet[lastRunes[i]] {
			lastContentIdx = i
			break
		}
	}

	suffix := lastRunes[lastContentIdx+1:]

	i := 0
	j := 0
	limitN := len(newRunes)
	limitS := len(suffix)

	// Offset pLow is an index into newRunes

	for i < limitS && (pLow+j) < limitN {
		charS := suffix[i]
		charN := newRunes[pLow+j]

		if charS == charN {
			i++
			j++
		} else if charN == '\\' && (pLow+j+1) < limitN && newRunes[pLow+j+1] == charS {
			j += 2
			i++
		} else if charS == '\\' && (i+1) < limitS && suffix[i+1] == charN {
			i += 2
			j++
		} else {
			break
		}
	}

	return string(newRunes[pLow+j:]), newC
}

func GetNestedValue(data interface{}, path []interface{}) interface{} {
	current := data
	for _, key := range path {
		found := false
		if idx, ok := key.(int); ok {
			if list, ok := current.([]interface{}); ok {
				if idx >= -len(list) && idx < len(list) {
					if idx < 0 {
						idx = len(list) + idx
					}
					current = list[idx]
					found = true
				}
			}
		} else if k, ok := key.(string); ok {
			if m, ok := current.(map[string]interface{}); ok {
				if val, ok := m[k]; ok {
					current = val
					found = true
				}
			}
		}

		if !found {
			return nil
		}
	}
	return current
}

func ExtractJSONFromResponse(text string) ([]interface{}, error) {
	content := text
	if strings.HasPrefix(content, ")]}'") {
		content = content[4:]
	}
	content = strings.TrimLeft(content, " \t\n\r")

	// Try framing
	result, _ := ParseResponseByFrame(content)
	if len(result) > 0 {
		return result, nil
	}

	// Try full content
	contentStripped := strings.TrimSpace(content)
	var parsed interface{}
	if err := json.Unmarshal([]byte(contentStripped), &parsed); err == nil {
		if list, ok := parsed.([]interface{}); ok {
			return list, nil
		}
		return []interface{}{parsed}, nil
	}

	// NDJSON
	lines := strings.Split(contentStripped, "\n")
	var collected []interface{}
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var p interface{}
		if err := json.Unmarshal([]byte(line), &p); err == nil {
			if list, ok := p.([]interface{}); ok {
				collected = append(collected, list...)
			} else {
				collected = append(collected, p)
			}
		}
	}

	if len(collected) > 0 {
		return collected, nil
	}

	return nil, fmt.Errorf("could not find valid JSON")
}
