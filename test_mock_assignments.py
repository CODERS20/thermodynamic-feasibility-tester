import math
import unittest

from run_mock_assignments import base_assignment, modified_assignment


class MockAssignmentTests(unittest.TestCase):
    def test_base_x100(self):
        cases, result = base_assignment(100)
        case = cases["base"]
        # Independently evaluate the sensible heat and entropy balances.
        electrical_kw = 45 * 0.25 * 4.184 * 65 / (0.85 * 3600)
        hot_in_K = 318.15 + 16 / (0.3 * 4.184)
        cold_out_K = 298.15 + (16 - electrical_kw) / (0.6 * 4.184)
        cold_out_rev_K = 298.15 * math.sqrt(hot_in_K / 318.15)
        reversible_kw = 16 - 0.6 * 4.184 * (cold_out_rev_K - 298.15)
        self.assertAlmostEqual(case["hot_stream"]["T_in_K"], hot_in_K)
        self.assertAlmostEqual(case["cold_stream"]["T_out_K"], cold_out_K)
        self.assertAlmostEqual(result["Claimed electrical output (kW)"], electrical_kw)
        self.assertAlmostEqual(result["Reversible cold water outlet (K)"], cold_out_rev_K)
        self.assertAlmostEqual(result["Strict reversible power ceiling (kW)"], reversible_kw)
        self.assertAlmostEqual(result["Maximum coffee (L/h)"], 12.97392727)
        self.assertAlmostEqual(result["Maximum coffee powder (kg/h)"], 0.77843564)
        self.assertEqual(result["Verdict"], "FEASIBLE / NOT REJECTED")

    def test_modified_x100(self):
        cases, result = modified_assignment(100)
        # For a 350–450 K linear Cp interval, mean Cp is 1.20 kJ/(kg K).
        heat_kw = 0.1 * 1.20 * 100
        entropy_loss = 0.1 * (math.log(450 / 350) + 0.0005 * 100)
        melt_K = 250 / 0.80
        reversible_kw = heat_kw - melt_K * entropy_loss
        engine = cases["modified_engine"]
        self.assertAlmostEqual(engine["Q_hot_kw"], heat_kw)
        self.assertAlmostEqual(engine["T_hot_K"], heat_kw / entropy_loss)
        self.assertAlmostEqual(engine["T_cold_K"], melt_K)
        self.assertAlmostEqual(result["Claimed electrical output (kW)"], 1.33313725)
        self.assertAlmostEqual(result["Reversible power ceiling (kW)"], reversible_kw)
        self.assertAlmostEqual(result["Maximum coffee (L/h)"], 29.07342181)
        self.assertEqual(result["Verdict"], "FEASIBLE / NOT REJECTED")

    def test_verdicts_across_each_assignment_range(self):
        for suffix in range(400):
            with self.subTest(case="Base", suffix=suffix):
                _, result = base_assignment(suffix)
                expected = "FEASIBLE / NOT REJECTED" if suffix < 291 else "NOT FEASIBLE"
                self.assertEqual(result["Verdict"], expected)
                self.assertEqual(
                    result["Claimed electrical output (kW)"] <= result["Strict reversible power ceiling (kW)"],
                    expected == "FEASIBLE / NOT REJECTED",
                )
        for suffix in range(1, 401):
            with self.subTest(case="Modified", suffix=suffix):
                _, result = modified_assignment(suffix)
                expected = "NOT FEASIBLE" if suffix < 12 else "FEASIBLE / NOT REJECTED"
                self.assertEqual(result["Verdict"], expected)

    def test_out_of_range_suffixes(self):
        for builder, suffix in ((base_assignment, -1), (base_assignment, 400),
                                (modified_assignment, 0), (modified_assignment, 401)):
            with self.subTest(builder=builder.__name__, suffix=suffix):
                with self.assertRaises(ValueError):
                    builder(suffix)

    def test_optional_server_heat_budget(self):
        _, sufficient = modified_assignment(100, 12)
        self.assertEqual(sufficient["Server heat budget check"], "PASS")
        self.assertEqual(sufficient["Verdict"], "FEASIBLE / NOT REJECTED")
        _, insufficient = modified_assignment(100, 11)
        self.assertEqual(insufficient["Server heat budget check"], "FAIL")
        self.assertEqual(insufficient["Verdict"], "NOT FEASIBLE")
        with self.assertRaises(ValueError):
            modified_assignment(100, float("nan"))


if __name__ == "__main__":
    unittest.main()
