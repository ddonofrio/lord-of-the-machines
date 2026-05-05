from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lord_of_the_machines.llm import (
    AgentEnvelopeSpec,
    AgentProtocolError,
    BaseAgent,
    BaseAgentConfig,
    EnvelopeField,
    TokenRateLimiter,
    ToolDefinition,
    ToolCallOutputSpec,
    ToolMethodDefinition,
)
from tests.helpers.fake_openai import (
    FakeClient,
    FakeContextWindowError,
    FakeResponse,
    FakeRateLimitError,
    FakeUsage,
    FakeUsageDetails,
    FakeUnsupportedVerbosityError,
)
from tests.helpers.outputs import custom_reply_output, reply_output, tool_output
from tests.helpers.outputs import native_function_response, native_message_response


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class SpyRateLimiter:
    def __init__(self) -> None:
        self.reservations: list[int] = []

    def reserve(self, token_count: int):
        self.reservations.append(token_count)
        return None


class BaseAgentTests(unittest.TestCase):
    def test_query_builds_configurable_protocol_envelope_and_records_clean_history(self) -> None:
        client = FakeClient([reply_output("hello world")])
        agent = BaseAgent.new(client=client, rate_limiter=None, system_prompt="Reply briefly.")

        reply = agent.query("Simon says hello")

        self.assertEqual(reply.message, "hello world")
        payload = client.responses.calls[0]
        self.assertEqual(payload["model"], "gpt-4.1")
        self.assertIn("Lord of the Machines", payload["instructions"])
        self.assertIn("Reply briefly.", payload["instructions"])
        envelope = json.loads(payload["input"])
        self.assertEqual(envelope["protocol"], "lord_of_the_machines.agent.v1")
        self.assertEqual(envelope["user"]["prompt"], "Simon says hello")
        self.assertEqual(envelope["runtime_context"]["available_tools"][0]["name"], "reply")
        self.assertEqual(
            agent.get_history(),
            [
                {"role": "user", "content": "Simon says hello"},
                {"role": "assistant", "content": "hello world"},
            ],
        )

    def test_envelope_and_output_field_names_are_pluggable(self) -> None:
        envelope = AgentEnvelopeSpec(
            version="custom.agent.v1",
            input_fields=[
                EnvelopeField("protocol", "protocol"),
                EnvelopeField("history", "conversation_history"),
                EnvelopeField("context", "runtime_context"),
                EnvelopeField("request", "user"),
                EnvelopeField("contract", "output_contract"),
            ],
            output=ToolCallOutputSpec(
                calls_field="actions",
                tool_field="tool_name",
                method_field="operation",
                arguments_field="args",
            ),
        )
        client = FakeClient([custom_reply_output("custom ok")])
        agent = BaseAgent.new(client=client, rate_limiter=None, envelope_spec=envelope)

        reply = agent.query({"mission": "test"})

        self.assertEqual(reply.message, "custom ok")
        envelope_payload = json.loads(client.responses.calls[0]["input"])
        self.assertEqual(sorted(envelope_payload), ["context", "contract", "history", "protocol", "request"])
        self.assertEqual(envelope_payload["request"]["prompt"], {"mission": "test"})
        self.assertEqual(
            envelope_payload["contract"]["required_json_shape"],
            {"actions": [{"tool_name": "tool_name", "operation": "method_name", "args": {}}]},
        )
        text_schema = client.responses.calls[0]["text"]["format"]["schema"]
        self.assertIn("actions", text_schema["properties"])

    def test_protocol_repair_keeps_invalid_output_out_of_history(self) -> None:
        client = FakeClient(["not json", reply_output("repaired")])
        agent = BaseAgent.new(client=client, rate_limiter=None)

        reply = agent.query("hello")

        self.assertEqual(reply.message, "repaired")
        repair_prompt = json.loads(client.responses.calls[1]["input"])["user"]["prompt"]
        self.assertEqual(repair_prompt["type"], "protocol_repair_request")
        self.assertIn("Invalid JSON", repair_prompt["parser_error"])
        self.assertEqual(
            agent.get_history(),
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "repaired"},
            ],
        )

    def test_memory_tools_can_reply_in_same_turn_and_feed_results_back(self) -> None:
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "memory",
                        "method": "remember",
                        "arguments": {"key": "mission", "value": "bootstrap", "importance": "high"},
                    },
                    {
                        "tool": "reply",
                        "method": "send_message",
                        "arguments": {"message": "remembered"},
                    },
                ),
                tool_output({"tool": "memory", "method": "recall", "arguments": {"key": "mission"}}),
                reply_output("mission is bootstrap"),
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)

        first = agent.query("remember this")
        second = agent.query("what is the mission?")

        self.assertEqual(first.message, "remembered")
        self.assertEqual(second.message, "mission is bootstrap")
        self.assertEqual(agent.config.memory[0]["key"], "mission")
        tool_prompt = json.loads(client.responses.calls[2]["input"])["user"]["prompt"]
        self.assertEqual(tool_prompt["type"], "tool_results")

    def test_context_rate_limit_verbosity_and_token_preflight_behaviors(self) -> None:
        context_client = FakeClient([FakeContextWindowError("context window token length exceeded"), reply_output("recovered")])
        context_agent = BaseAgent.new(client=context_client, rate_limiter=None)
        context_agent.add_history("user", "previous")
        context_agent.add_history("assistant", "previous answer")
        self.assertEqual(context_agent.query("current").message, "recovered")
        self.assertEqual(json.loads(context_client.responses.calls[1]["input"])["conversation_history"], [])

        rate_limited = FakeClient([FakeRateLimitError("Rate limit reached. Please try again in 1.25s."), reply_output("after wait")])
        with patch("lord_of_the_machines.llm.transport.time.sleep") as sleep:
            self.assertEqual(BaseAgent.new(client=rate_limited, rate_limiter=None).query("hi").message, "after wait")
        sleep.assert_called_once()

        unsupported = FakeClient(
            [
                FakeUnsupportedVerbosityError(
                    "Unsupported value: 'low' is not supported with the 'gpt-4.1' model. Supported values are: 'medium'."
                ),
                reply_output("fixed"),
            ]
        )
        reply = BaseAgent.new(client=unsupported, rate_limiter=None, text_verbosity="low").query("hi")
        self.assertEqual(reply.message, "fixed")
        self.assertEqual(unsupported.responses.calls[1]["text"]["verbosity"], "medium")

        limiter = SpyRateLimiter()
        budget_client = FakeClient([reply_output("budgeted")])
        budget_agent = BaseAgent.new(
            client=budget_client,
            rate_limiter=limiter,
            token_counter_encoding="character",
            max_output_tokens=17,
        )
        self.assertEqual(budget_agent.query("hi").message, "budgeted")
        payload = budget_client.responses.calls[0]
        self.assertEqual(len(limiter.reservations), 1)
        self.assertGreaterEqual(limiter.reservations[0], len(payload["input"]) + len(payload["instructions"]) + 17)

    def test_prompt_cache_fields_control_stable_key_seed(self) -> None:
        stable_client = FakeClient([reply_output("first"), reply_output("second")])
        stable_agent = BaseAgent.new(client=stable_client, rate_limiter=None, system_prompt="Stable mission brief.")
        stable_agent.query("first")
        stable_agent.query("second")
        self.assertEqual(stable_client.responses.calls[0]["prompt_cache_retention"], "24h")
        self.assertTrue(stable_client.responses.calls[0]["prompt_cache_key"].startswith("lotm-gpt-4-1-"))
        self.assertEqual(stable_client.responses.calls[0]["prompt_cache_key"], stable_client.responses.calls[1]["prompt_cache_key"])

        input_seed_client = FakeClient([reply_output("first"), reply_output("second")])
        input_seed_agent = BaseAgent.new(
            client=input_seed_client,
            rate_limiter=None,
            prompt_cache_fields=["model", "instructions", "input"],
        )
        input_seed_agent.query("first")
        input_seed_agent.query("second")
        self.assertNotEqual(input_seed_client.responses.calls[0]["prompt_cache_key"], input_seed_client.responses.calls[1]["prompt_cache_key"])

    def test_token_rate_limiter_waits_until_window_has_capacity(self) -> None:
        clock = FakeClock()
        limiter = TokenRateLimiter(
            tokens_per_window=100,
            window_seconds=60.0,
            clock=clock.monotonic,
            sleeper=clock.sleep,
        )

        first = limiter.reserve(70)
        second = limiter.reserve(40)

        self.assertEqual(first.wait_seconds, 0.0)
        self.assertEqual(second.used_before, 0)
        self.assertEqual(second.wait_seconds, 60.0)
        self.assertEqual(clock.sleeps, [60.0])

    def test_invalid_tool_shape_raises_when_repairs_are_exhausted(self) -> None:
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "reply",
                        "method": "bad",
                        "arguments": {"message": "hello"},
                    }
                )
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None, output_repair_attempts=0)

        with self.assertRaises(AgentProtocolError):
            agent.query("hello")

    def test_openai_native_tool_calling_builds_provider_tools_and_executes_tool_rounds(self) -> None:
        client = FakeClient(
            [
                native_function_response(
                    {
                        "name": "memory__remember",
                        "arguments": {"key": "mission", "value": "bootstrap"},
                        "call_id": "call_memory",
                    },
                    response_id="resp_native_1",
                ),
                native_message_response("done", response_id="resp_native_2"),
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None, tool_calling_mode="openai_native")

        reply = agent.query("remember the mission")

        self.assertEqual(reply.message, "done")
        first_payload = client.responses.calls[0]
        self.assertEqual(first_payload["tools"][0]["type"], "function")
        self.assertIn("memory__remember", [tool["name"] for tool in first_payload["tools"]])
        self.assertEqual(first_payload["text"]["format"]["type"], "text")

        envelope = json.loads(first_payload["input"])
        self.assertNotIn("output_contract", envelope)
        self.assertEqual(envelope["runtime_context"]["tool_calling"]["mode"], "openai_native")
        self.assertNotIn("available_tools", envelope["runtime_context"])

        second_payload = client.responses.calls[1]
        self.assertEqual(second_payload["previous_response_id"], "resp_native_1")
        self.assertEqual(second_payload["input"][0]["type"], "function_call_output")
        self.assertEqual(second_payload["input"][0]["call_id"], "call_memory")
        self.assertEqual(agent.config.memory[0]["key"], "mission")

    def test_openai_native_tool_calling_supports_reply_tool_calls(self) -> None:
        client = FakeClient(
            [
                native_function_response(
                    {
                        "name": "reply__send_message",
                        "arguments": {"message": "native hello"},
                        "call_id": "call_reply",
                    }
                )
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None, tool_calling_mode="openai_native")

        reply = agent.query("say hello")

        self.assertEqual(reply.message, "native hello")
        self.assertEqual(reply.tool_calls[0].call_id, "call_reply")

    def test_unknown_provider_is_rejected_early(self) -> None:
        with self.assertRaises(ValueError):
            BaseAgent.new(client=FakeClient(), rate_limiter=None, provider="unknown")

    def test_legacy_config_sections_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            config_path = Path(tempdir) / "legacy-base-agent.json"
            config_path.write_text(
                json.dumps(
                    {
                        "provider": {"provider": "openai", "model": "gpt-4.1"},
                        "protocol": {"enabled": True},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                BaseAgentConfig.from_file(config_path)

    def test_tools_api_is_typed_and_rejects_legacy_mappings(self) -> None:
        agent = BaseAgent.new(client=FakeClient(), rate_limiter=None)

        listed_tools = agent.list_tools()

        self.assertTrue(all(isinstance(tool, ToolDefinition) for tool in listed_tools))
        self.assertTrue(any(tool.name == "reply" for tool in listed_tools))
        self.assertTrue(any(tool.name == "pagination" for tool in listed_tools))

        with self.assertRaises(TypeError):
            agent.add_tool(
                {
                    "name": "legacy",
                    "methods": [{"name": "run"}],
                }
            )

        agent.add_tool(
            ToolDefinition(
                name="typed_tool",
                methods=[
                    ToolMethodDefinition(
                        name="run",
                        arguments_schema={
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {},
                            "required": [],
                        },
                    )
                ],
            )
        )
        self.assertTrue(any(tool.name == "typed_tool" for tool in agent.list_tools()))

    def test_pagination_tool_can_finish_reply_from_pages(self) -> None:
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "pagination",
                        "method": "append_page",
                        "arguments": {
                            "target": "reply",
                            "content": "part one ",
                            "status": "continue",
                        },
                    }
                ),
                tool_output(
                    {
                        "tool": "pagination",
                        "method": "append_page",
                        "arguments": {
                            "target": "reply",
                            "content": "part two",
                            "status": "stop",
                        },
                    }
                ),
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None, max_tool_rounds=3)

        reply = agent.query("write a long answer")

        self.assertEqual(reply.message, "part one part two")
        self.assertEqual(len(client.responses.calls), 2)
        self.assertEqual(
            agent.get_history(),
            [
                {"role": "user", "content": "write a long answer"},
                {"role": "assistant", "content": "part one part two"},
            ],
        )

    def test_pagination_continue_takes_precedence_over_early_reply(self) -> None:
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "pagination",
                        "method": "append_page",
                        "arguments": {
                            "target": "reply",
                            "content": "first page ",
                            "status": "continue",
                        },
                    },
                    {
                        "tool": "reply",
                        "method": "send_message",
                        "arguments": {"message": "pagination://reply"},
                    },
                ),
                tool_output(
                    {
                        "tool": "pagination",
                        "method": "append_page",
                        "arguments": {
                            "target": "reply",
                            "content": "final page",
                            "status": "stop",
                        },
                    }
                ),
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None, max_tool_rounds=3)

        reply = agent.query("write a long answer")

        self.assertEqual(reply.message, "first page final page")
        self.assertEqual(len(client.responses.calls), 2)

    def test_structured_tool_result_resolves_paginated_reference(self) -> None:
        client = FakeClient(
            [
                tool_output(
                    {
                        "tool": "pagination",
                        "method": "append_page",
                        "arguments": {
                            "target": "artifact_content",
                            "content": "# Title\n",
                            "status": "continue",
                        },
                    }
                ),
                tool_output(
                    {
                        "tool": "pagination",
                        "method": "append_page",
                        "arguments": {
                            "target": "artifact_content",
                            "content": "Body\n",
                            "status": "stop",
                        },
                    },
                    {
                        "tool": "result",
                        "method": "submit",
                        "arguments": {"artifact_content": "pagination://artifact_content"},
                    },
                ),
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None, max_tool_rounds=3)
        agent.add_tool(
            ToolDefinition(
                name="result",
                single_round=True,
                methods=[
                    ToolMethodDefinition(
                        name="submit",
                        arguments_schema={
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {"artifact_content": {"type": "string"}},
                            "required": ["artifact_content"],
                        },
                    )
                ],
            ),
            handlers={"submit": lambda arguments: dict(arguments)},
        )

        result, _reply = agent.query_structured_tool_result(
            "return a long structured artifact",
            tool_name="result",
            method_name="submit",
        )

        self.assertEqual(result, {"artifact_content": "# Title\nBody\n"})

    def test_structured_tool_result_finalizes_usage_and_cost(self) -> None:
        client = FakeClient(
            [
                FakeResponse(
                    tool_output(
                        {
                            "tool": "result",
                            "method": "submit",
                            "arguments": {"value": "done"},
                        }
                    ),
                    usage=FakeUsage(
                        input_tokens=1000,
                        output_tokens=100,
                        total_tokens=1100,
                        input_tokens_details=FakeUsageDetails(cached_tokens=200),
                    ),
                )
            ]
        )
        agent = BaseAgent.new(client=client, rate_limiter=None)
        agent.add_tool(
            ToolDefinition(
                name="result",
                single_round=True,
                methods=[
                    ToolMethodDefinition(
                        name="submit",
                        arguments_schema={
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                        },
                    )
                ],
            ),
            handlers={"submit": lambda arguments: dict(arguments)},
        )

        result, _reply = agent.query_structured_tool_result(
            "return a structured reply",
            tool_name="result",
            method_name="submit",
        )

        self.assertEqual(result, {"value": "done"})
        self.assertEqual(agent.last_query_usage["total_tokens"], 1100)
        self.assertIsNotNone(agent.last_query_cost)


if __name__ == "__main__":
    unittest.main()
