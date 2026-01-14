"""
Tests for extract_json_from_response() in gemini_webapi.utils.parsing.

These tests define the expected behavior for parsing Google RPC streaming responses,
which use a specific format:
    )]}'              <- XSSI protection header
    159               <- byte length marker
    [["wrb.fr",...]]  <- JSON chunk (may be single or multi-line)

The current implementation uses splitlines() which breaks when JSON chunks span
multiple lines. These tests capture the correct behavior that should be implemented.
"""

import unittest

from gemini_webapi.utils.parsing import extract_json_from_response


class TestExtractJsonFromResponse(unittest.TestCase):
    """Test suite for extract_json_from_response() function."""

    # -------------------------------------------------------------------------
    # Multi-line JSON chunk tests (the bug we're fixing)
    # -------------------------------------------------------------------------

    def test_multiline_json_chunk_basic(self):
        """
        JSON chunk spanning multiple lines should be parsed correctly.

        This is the core bug: splitlines() breaks multi-line JSON because it
        tries to parse each line independently, failing when a JSON array/object
        spans multiple lines.
        """
        # Google RPC format with multi-line JSON chunk
        response = """)]}'
31943
[["wrb.fr","BardGeneratorService","GetReply",
"some data here",
"more data"
]]"""

        result = extract_json_from_response(response)

        # Should successfully parse the multi-line JSON array
        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "wrb.fr")
        self.assertEqual(result[1], "BardGeneratorService")

    def test_multiline_json_chunk_with_nested_arrays(self):
        """
        Multi-line JSON with nested structures should parse correctly.

        Real Google API responses contain deeply nested arrays that often
        span multiple lines for readability in the wire format.
        """
        response = """)]}'
1024
[["wrb.fr","BardGeneratorService","GetReply",[
    ["nested", "array", "data"],
    ["another", "nested", "item"]
],null]]"""

        result = extract_json_from_response(response)

        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "wrb.fr")
        # Verify nested structure is preserved
        self.assertIsInstance(result[3], list)
        self.assertEqual(result[3][0], ["nested", "array", "data"])

    def test_multiline_json_with_escaped_newlines_in_strings(self):
        """
        JSON containing escaped newlines within string values should work.

        This tests that we distinguish between:
        - Actual newlines in the JSON structure (formatting)
        - Escaped newlines within string values (\\n)
        """
        response = """)]}'
512
[["wrb.fr","response",
"This is a string\\nwith escaped newlines\\ninside it"
]]"""

        result = extract_json_from_response(response)

        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "wrb.fr")
        # The escaped newlines should be preserved in the string
        self.assertIn("\\n", result[2])

    def test_multiline_json_chunk_realistic_response(self):
        """
        Test with a realistic multi-line response structure from Google API.

        This mimics the actual format seen in production where the JSON
        payload spans many lines due to its size and structure.
        """
        response = """)]}'
31943
[["wrb.fr","BardGeneratorService","GetReply","[[[\\"Hello! How can I help you today?\\",null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,[\\"en\\"],null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,[\\"c_abc123\\",\\"r_xyz789\\",\\"rc_def456\\"],null,null,null,null,null,null,null,null,null,null,null,null,
null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null
]]]",null,null,null,"generic"]]"""

        result = extract_json_from_response(response)

        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "wrb.fr")
        self.assertEqual(result[1], "BardGeneratorService")
        self.assertEqual(result[2], "GetReply")

    # -------------------------------------------------------------------------
    # Backward compatibility tests (single-line format must still work)
    # -------------------------------------------------------------------------

    def test_single_line_json_chunk(self):
        """
        Single-line JSON chunks should continue to work (backward compatibility).

        This is the format that currently works with splitlines().
        """
        response = """)]}'
159
[["wrb.fr","BardGeneratorService","GetReply","data",null]]"""

        result = extract_json_from_response(response)

        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "wrb.fr")

    def test_single_line_simple_array(self):
        """Simple single-line JSON array should parse correctly."""
        response = """)]}'
25
["simple", "array", 123]"""

        result = extract_json_from_response(response)

        self.assertEqual(result, ["simple", "array", 123])

    def test_single_line_without_xssi_header(self):
        """
        Response without XSSI header but with length marker should work.

        Some endpoints may omit the )]}' header.
        """
        response = """159
[["wrb.fr","BardGeneratorService","GetReply","data",null]]"""

        result = extract_json_from_response(response)

        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "wrb.fr")

    def test_json_only_no_markers(self):
        """
        Plain JSON without any markers should still parse.

        This ensures we don't break simple use cases where the input
        is just raw JSON without Google RPC formatting.
        """
        response = """[["wrb.fr","BardGeneratorService","GetReply"]]"""

        result = extract_json_from_response(response)

        self.assertIsInstance(result, list)
        # Result is the outer array, so result[0] is the inner array
        self.assertEqual(result[0][0], "wrb.fr")

    # -------------------------------------------------------------------------
    # Length marker format tests
    # -------------------------------------------------------------------------

    def test_length_marker_before_json_chunk(self):
        """
        Byte length marker should be used to determine chunk boundaries.

        The Google RPC format includes a byte length before each JSON chunk.
        This length should be used to correctly extract multi-line JSON.
        """
        # 43 bytes: [["wrb.fr","test","data"]]
        response = """)]}'
27
[["wrb.fr","test","data"]]"""

        result = extract_json_from_response(response)

        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "wrb.fr")
        self.assertEqual(result[1], "test")

    def test_multiple_chunks_returns_first_valid(self):
        """
        When multiple JSON chunks exist, should return the first valid one.

        Google RPC responses can contain multiple chunks; we want the first.
        """
        response = """)]}'
27
[["wrb.fr","first","chunk"]]
25
[["second","chunk","here"]]"""

        result = extract_json_from_response(response)

        self.assertIsInstance(result, list)
        # Should return the first chunk
        self.assertEqual(result[1], "first")

    def test_length_marker_with_multiline_chunk(self):
        """
        Length marker should correctly bound a multi-line JSON chunk.

        The byte length tells us exactly how many bytes to read for the
        JSON chunk, allowing correct parsing even when it spans lines.
        """
        # Multi-line JSON chunk with accurate byte length
        json_chunk = """[["wrb.fr",
"multiline",
"chunk"]]"""
        byte_length = len(json_chunk.encode('utf-8'))

        # Build response with length marker
        response = ")]}''\n" + str(byte_length) + "\n" + json_chunk

        result = extract_json_from_response(response)

        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "wrb.fr")
        self.assertEqual(result[1], "multiline")
        self.assertEqual(result[2], "chunk")

    # -------------------------------------------------------------------------
    # Edge cases and error handling
    # -------------------------------------------------------------------------

    def test_empty_string_raises_value_error(self):
        """Empty input should raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            extract_json_from_response("")

        self.assertIn("Could not find", str(ctx.exception))

    def test_non_string_input_raises_type_error(self):
        """Non-string input should raise TypeError."""
        with self.assertRaises(TypeError):
            extract_json_from_response(None)

        with self.assertRaises(TypeError):
            extract_json_from_response(123)

        with self.assertRaises(TypeError):
            extract_json_from_response(["list", "input"])

    def test_no_json_in_response_raises_value_error(self):
        """Response with no valid JSON should raise ValueError."""
        response = """)]}'
This is not JSON
Just plain text"""

        with self.assertRaises(ValueError) as ctx:
            extract_json_from_response(response)

        self.assertIn("Could not find", str(ctx.exception))

    def test_malformed_json_raises_value_error(self):
        """Malformed JSON should raise ValueError."""
        response = ')]}\'\\n50\\n[["unclosed", "array"'

        with self.assertRaises(ValueError):
            extract_json_from_response(response)

    def test_xssi_header_only_raises_value_error(self):
        """Response with only XSSI header should raise ValueError."""
        response = """)]}'"""

        with self.assertRaises(ValueError):
            extract_json_from_response(response)

    def test_whitespace_handling(self):
        """
        Whitespace around JSON should be handled gracefully.

        Trailing/leading whitespace in the response should not break parsing.
        """
        response = """   )]}'
27
[["wrb.fr","test","data"]]
   """

        result = extract_json_from_response(response)

        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "wrb.fr")

    def test_json_object_instead_of_array(self):
        """
        JSON objects (not just arrays) should be parseable.

        While Google typically returns arrays, objects should work too.
        """
        response = """)]}'
35
{"key": "value", "number": 42}"""

        result = extract_json_from_response(response)

        self.assertIsInstance(result, dict)
        self.assertEqual(result["key"], "value")
        self.assertEqual(result["number"], 42)


class TestExtractJsonMultilineEdgeCases(unittest.TestCase):
    """Additional edge cases specifically for multi-line JSON parsing."""

    def test_json_with_unicode_multiline(self):
        """Multi-line JSON containing unicode characters should parse correctly."""
        response = """)]}'
100
[["wrb.fr",
"Hello",
"unicode characters"]]"""

        result = extract_json_from_response(response)

        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "wrb.fr")

    def test_deeply_nested_multiline_structure(self):
        """Deeply nested multi-line JSON structures should parse correctly."""
        response = """)]}'
500
[["wrb.fr","service",[
    [
        [
            "deeply",
            "nested",
            [
                "structure"
            ]
        ]
    ]
]]]"""

        result = extract_json_from_response(response)

        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "wrb.fr")
        self.assertEqual(result[1], "service")
        # Verify deep nesting is preserved
        self.assertEqual(result[2][0][0][0], "deeply")

    def test_json_with_null_values_multiline(self):
        """Multi-line JSON with null values should parse correctly."""
        response = """)]}'
200
[["wrb.fr",
null,
"data",
null,
null]]"""

        result = extract_json_from_response(response)

        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "wrb.fr")
        self.assertIsNone(result[1])
        self.assertEqual(result[2], "data")
        self.assertIsNone(result[3])

    def test_json_with_boolean_values_multiline(self):
        """Multi-line JSON with boolean values should parse correctly."""
        response = """)]}'
150
[["wrb.fr",
true,
false,
"string",
true]]"""

        result = extract_json_from_response(response)

        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "wrb.fr")
        self.assertTrue(result[1])
        self.assertFalse(result[2])

    def test_json_with_numeric_values_multiline(self):
        """Multi-line JSON with various numeric types should parse correctly."""
        response = """)]}'
200
[["wrb.fr",
42,
3.14159,
-100,
1.5e10]]"""

        result = extract_json_from_response(response)

        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "wrb.fr")
        self.assertEqual(result[1], 42)
        self.assertAlmostEqual(result[2], 3.14159)
        self.assertEqual(result[3], -100)
        self.assertEqual(result[4], 1.5e10)


if __name__ == "__main__":
    unittest.main()
