from __future__ import annotations

import unittest

from lord_of_the_machines.llm.costs import estimate_usage_cost, usage_token_summary
from tests.helpers.fake_openai import FakeUsage, FakeUsageDetails


class LlmCostsTests(unittest.TestCase):
    def test_usage_token_summary_extracts_cached_tokens(self) -> None:
        usage = FakeUsage(
            input_tokens=1_000_000,
            output_tokens=100_000,
            total_tokens=1_100_000,
            input_tokens_details=FakeUsageDetails(cached_tokens=200_000),
        )
        summary = usage_token_summary(usage)
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["input_tokens"], 1_000_000)
        self.assertEqual(summary["cached_input_tokens"], 200_000)
        self.assertEqual(summary["billable_input_tokens"], 800_000)
        self.assertEqual(summary["output_tokens"], 100_000)
        self.assertEqual(summary["total_tokens"], 1_100_000)

    def test_estimate_usage_cost_for_gpt_4_1(self) -> None:
        usage = {
            "input_tokens": 1_000_000,
            "cached_input_tokens": 200_000,
            "billable_input_tokens": 800_000,
            "output_tokens": 100_000,
            "total_tokens": 1_100_000,
        }
        cost = estimate_usage_cost(model_name="gpt-4.1", usage=usage)
        self.assertIsNotNone(cost)
        assert cost is not None
        self.assertEqual(cost["currency"], "USD")
        self.assertEqual(cost["rates_per_1m"]["input"], 2.0)
        self.assertEqual(cost["rates_per_1m"]["cached_input"], 0.5)
        self.assertEqual(cost["rates_per_1m"]["output"], 8.0)
        self.assertAlmostEqual(cost["cost_usd"]["input"], 1.6, places=6)
        self.assertAlmostEqual(cost["cost_usd"]["cached_input"], 0.1, places=6)
        self.assertAlmostEqual(cost["cost_usd"]["output"], 0.8, places=6)
        self.assertAlmostEqual(cost["cost_usd"]["total"], 2.5, places=6)


if __name__ == "__main__":
    unittest.main()
