package gemini

import (
	"reflect"
	"testing"
)

func TestParseResponseByFrame(t *testing.T) {
	// 5 chars: \n\n[1] (includes newline after digit, and json content)
	input := "5\n\n[1]"
	// ParseResponseByFrame flattens the list if the parsed JSON is a list.
	// So [1] becomes 1 in the frames list.
	expected := []interface{}{float64(1)}

	frames, remaining := ParseResponseByFrame(input)
	if remaining != "" {
		t.Errorf("Expected empty remaining, got %q", remaining)
	}
	if !reflect.DeepEqual(frames, expected) {
		t.Errorf("Expected %v, got %v", expected, frames)
	}

	// Test multiple frames
	// 5 chars: \n\n[1]
	// 5 chars: \n\n[2]
	// Note: ParseResponseByFrame strips whitespace from chunk before parsing json
	input2 := "5\n\n[1]\n5\n\n[2]"
	expected2 := []interface{}{
		float64(1),
		float64(2),
	}
	frames2, remaining2 := ParseResponseByFrame(input2)
	if remaining2 != "" {
		t.Errorf("Expected empty remaining, got %q", remaining2)
	}
	if !reflect.DeepEqual(frames2, expected2) {
		t.Errorf("Expected %v, got %v", expected2, frames2)
	}
}

func TestGetDeltaByFPLen(t *testing.T) {
	// Simple case
	newText := "Hello World"
	lastText := "Hello "
	delta, full := GetDeltaByFPLen(newText, lastText, false)
	if delta != "World" {
		t.Errorf("Expected delta 'World', got '%s'", delta)
	}
	if full != "Hello World" {
		t.Errorf("Expected full 'Hello World', got '%s'", full)
	}

	// Case with formatting (markdown)
	newText2 := "Hello *World*"
	lastText2 := "Hello "
	delta2, _ := GetDeltaByFPLen(newText2, lastText2, false)
	if delta2 != "*World*" {
		t.Errorf("Expected delta '*World*', got '%s'", delta2)
	}

	// Test cleaning
	newText3 := "Hello \n```"
	// Cleaned: "Hello "
	lastText3 := "Hello"
	delta3, full3 := GetDeltaByFPLen(newText3, lastText3, false)
	// Full text should still be raw unless final? No, GetDeltaByFPLen returns raw newC as full if final, or clean newC if not final.
	// Here isFinal=false.
	// Cleaned newText3 is "Hello "
	// lastText3 is "Hello"
	// delta is " "
	if delta3 != " " {
		t.Errorf("Expected delta ' ', got '%q'", delta3)
	}
	if full3 != "Hello " {
		t.Errorf("Expected full 'Hello ', got '%q'", full3)
	}
}
