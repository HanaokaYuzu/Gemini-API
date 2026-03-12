import unittest

from gemini_webapi.components.research_mixin import ResearchMixin
from gemini_webapi.exceptions import GeminiError, TimeoutError
from gemini_webapi.types import Candidate, DeepResearchPlan, DeepResearchStatus, ModelOutput
from gemini_webapi.utils.research import extract_deep_research_plan


class DummyChat:
    def __init__(self, *, cid: str = "", error: Exception | None = None):
        self.cid = cid
        self.last_output = None
        self._error = error

    async def send_message(self, prompt: str, **kwargs):
        if self._error is not None:
            raise self._error
        return ModelOutput(
            metadata=[self.cid] if self.cid else [],
            candidates=[Candidate(rcid="rc_test", text="ok")],
        )


class DummyResearchClient(ResearchMixin):
    def __init__(self):
        self.deep_research_long_token = None
        self.deep_research_hex_token = None
        self.fallback_called = False
        self.started_with = None
        self._latest_output = ModelOutput(
            metadata=["c_plan"],
            candidates=[Candidate(rcid="rc_final", text="I have completed the research")],
        )

    async def fetch_latest_chat_response(self, cid: str):
        self.fallback_called = True
        return None

    async def inspect_account_status(self, chat=None):
        return {"summary": {}}

    async def _deep_research_preflight(self, chat=None):
        return None

    async def _collect_research_output(self, chat, prompt: str):
        return ModelOutput(
            metadata=[chat.cid] if chat.cid else [],
            candidates=[Candidate(rcid="rc_plan", text="started")],
        )

    def start_chat(self, **kwargs):
        self.started_with = kwargs
        return DummyChat(cid=kwargs.get("cid", ""))

    async def get_deep_research_status(self, research_id: str, chat=None):
        return DeepResearchStatus(
            research_id=research_id,
            state="completed",
            cid=chat.cid or "c_plan",
            done=True,
        )

    async def fetch_latest_chat_response_completed(self, cid: str):
        self.fallback_called = True
        return self._latest_output


class TestResearchUtils(unittest.TestCase):
    def test_extract_deep_research_plan_supports_key_57(self):
        research_id = "12345678-1234-1234-1234-1234567890ab"
        candidate_data = [
            "rc_test",
            ["plan preview"],
            {
                "57": [
                    "Plan title",
                    [[None, "Step 1", "Do thing"]],
                    "5 minutes",
                    ["Start research"],
                    ["https://example.com/confirm"],
                    ["Modify prompt"],
                ],
                "70": 2,
            },
            research_id,
        ]

        plan = extract_deep_research_plan(candidate_data, fallback_text="preview")

        self.assertIsNotNone(plan)
        self.assertEqual(plan["research_id"], research_id)
        self.assertEqual(plan["title"], "Plan title")
        self.assertEqual(plan["steps"], ["Step 1: Do thing"])
        self.assertEqual(plan["confirm_prompt"], "Start research")

    def test_extract_deep_research_plan_returns_none_for_empty_payload(self):
        research_id = "12345678-1234-1234-1234-1234567890ab"
        candidate_data = [{"57": []}, research_id]

        self.assertIsNone(extract_deep_research_plan(candidate_data, fallback_text="preview"))


class TestResearchWorkflow(unittest.IsolatedAsyncioTestCase):
    async def test_collect_research_output_reraises_timeout_without_fallback(self):
        client = DummyResearchClient()
        chat = DummyChat(cid="c_timeout", error=TimeoutError("network stalled"))

        with self.assertRaises(TimeoutError):
            await ResearchMixin._collect_research_output(client, chat, "prompt")

        self.assertFalse(client.fallback_called)

    async def test_collect_research_output_preserves_original_gemini_error(self):
        client = DummyResearchClient()
        chat = DummyChat(cid="c_error", error=GeminiError("original failure"))

        with self.assertRaisesRegex(GeminiError, "original failure"):
            await ResearchMixin._collect_research_output(client, chat, "prompt")

    async def test_start_deep_research_restores_chat_cid_from_plan(self):
        client = DummyResearchClient()
        plan = DeepResearchPlan(research_id="r1", metadata=[], cid="c_saved")

        await client.start_deep_research(plan)

        self.assertEqual(client.started_with["cid"], "c_saved")

    async def test_wait_for_deep_research_restores_chat_cid_from_plan(self):
        client = DummyResearchClient()
        client.fetch_latest_chat_response = client.fetch_latest_chat_response_completed
        plan = DeepResearchPlan(research_id="r1", metadata=[], cid="c_saved")

        result = await client.wait_for_deep_research(plan, poll_interval=0.01, timeout=1)

        self.assertEqual(client.started_with["cid"], "c_saved")
        self.assertTrue(result.done)
        self.assertEqual(result.final_output.text, "I have completed the research")
