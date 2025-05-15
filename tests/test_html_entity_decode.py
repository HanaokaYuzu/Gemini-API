import unittest
from gemini_webapi.types.candidate import Candidate


class TestHtmlEntityDecode(unittest.TestCase):
    def test_html_entity_decoding(self):
        # Test HTML entity decoding functionality
        html_encoded_text = (
            "This is a code snippet: &lt;code&gt;print('Hello, World!')&lt;/code&gt;"
        )
        expected_decoded_text = (
            "This is a code snippet: <code>print('Hello, World!')</code>"
        )

        # Create Candidate instance which should automatically decode HTML entities
        candidate = Candidate(
            rcid="test_rcid",
            text=html_encoded_text,
            thoughts="Testing &lt;b&gt;HTML&lt;/b&gt; entity decoding",
        )

        # Verify that text property is correctly decoded
        self.assertEqual(candidate.text, expected_decoded_text)

        # Verify that thoughts property is correctly decoded
        self.assertEqual(candidate.thoughts, "Testing <b>HTML</b> entity decoding")

    def test_non_html_text(self):
        # Test plain text without any HTML entities
        plain_text = "This is regular text with no HTML entities"

        candidate = Candidate(rcid="test_rcid", text=plain_text)

        # Verify the text remains unchanged
        self.assertEqual(candidate.text, plain_text)

    def test_complex_html_entities(self):
        # Test more complex combinations of HTML entities
        complex_html = "&lt;div&gt;This has &amp;amp; character\n and &quot;quotes&quot;&lt;/div&gt;"
        expected_decoded = '<div>This has &amp; character\n and "quotes"</div>'

        candidate = Candidate(rcid="test_rcid", text=complex_html)

        self.assertEqual(candidate.text, expected_decoded)


if __name__ == "__main__":
    unittest.main()
