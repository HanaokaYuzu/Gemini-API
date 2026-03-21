import unittest

from gemini_webapi.components.research_mixin import ResearchMixin
from gemini_webapi.exceptions import GeminiError, TimeoutError
from gemini_webapi.types import (
    Candidate,
    DeepResearchPlan,
    DeepResearchStatus,
    ModelOutput,
)
from gemini_webapi.utils.research import extract_deep_research_plan


class DummyChat:
    def __init__(self, *, cid="", error=None):
        self.cid = cid
        self.last_output = None
        self._error = error

    async def send_message(self, prompt, **kwargs):
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
            candidates=[
                Candidate(
                    rcid="rc_final",
                    text="I have completed the research",
                )
            ],
        )

    async def fetch_latest_chat_response(self, cid):
        self.fallback_called = True
        return None

    async def inspect_account_status(self, chat=None):
        return {"summary": {}}

    async def _deep_research_preflight(self, chat=None):
        return None

    async def _collect_research_output(self, chat, prompt):
        return ModelOutput(
            metadata=[chat.cid] if chat.cid else [],
            candidates=[Candidate(rcid="rc_plan", text="started")],
        )

    def start_chat(self, **kwargs):
        self.started_with = kwargs
        return DummyChat(cid=kwargs.get("cid", ""))

    async def get_deep_research_status(self, research_id, chat=None):
        return DeepResearchStatus(
            research_id=research_id,
            state="completed",
            cid=chat.cid or "c_plan",
            done=True,
        )

    async def fetch_latest_completed(self, cid):
        self.fallback_called = True
        return self._latest_output


class TestResearchUtils(unittest.TestCase):
    def test_extract_plan_key_57(self):
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
            "12345678-1234-1234-1234-1234567890ab",
        ]
        plan = extract_deep_research_plan(
            candidate_data, fallback_text="preview"
        )
        self.assertIsNotNone(plan)
        self.assertEqual(
            plan["research_id"],
            "12345678-1234-1234-1234-1234567890ab",
        )
        self.assertEqual(plan["title"], "Plan title")
        self.assertEqual(plan["steps"], ["Step 1: Do thing"])
        self.assertEqual(plan["confirm_prompt"], "Start research")

    def test_extract_plan_empty(self):
        candidate_data = [
            {"57": []},
            "12345678-1234-1234-1234-1234567890ab",
        ]
        self.assertIsNone(
            extract_deep_research_plan(
                candidate_data, fallback_text="preview"
            )
        )


class TestResearchWorkflow(unittest.IsolatedAsyncioTestCase):
    async def test_collect_reraises_timeout(self):
        client = DummyResearchClient()
        chat = DummyChat(cid="c_t", error=TimeoutError("stalled"))
        with self.assertRaises(TimeoutError):
            await ResearchMixin._collect_research_output(
                client, chat, "prompt"
            )
        self.assertFalse(client.fallback_called)

    async def test_collect_preserves_gemini_error(self):
        client = DummyResearchClient()
        chat = DummyChat(cid="c_e", error=GeminiError("fail"))
        with self.assertRaisesRegex(GeminiError, "fail"):
            await ResearchMixin._collect_research_output(
                client, chat, "prompt"
            )

    async def test_start_restores_chat_cid(self):
        client = DummyResearchClient()
        plan = DeepResearchPlan(
            research_id="r1", metadata=[], cid="c_saved"
        )
        await client.start_deep_research(plan)
        self.assertEqual(client.started_with["cid"], "c_saved")

    async def test_wait_restores_chat_cid(self):
        client = DummyResearchClient()
        client.fetch_latest_chat_response = (
            client.fetch_latest_completed
        )
        plan = DeepResearchPlan(
            research_id="r1", metadata=[], cid="c_saved"
        )
        result = await client.wait_for_deep_research(
            plan, poll_interval=0.01, timeout=1
        )
        self.assertEqual(client.started_with["cid"], "c_saved")
        self.assertTrue(result.done)
        self.assertEqual(
            result.final_output.text,
            "I have completed the research",
        )
