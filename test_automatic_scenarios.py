import unittest

from website.dist.solver import solve


TOUGH_SCENARIO = (
    "A company proposes a waste-heat generator using two finite streams. "
    "Hot thermal oil flows at 0.50 kg/s, entering at 180 °C and leaving at 80 °C. "
    "Its constant specific heat capacity is 2.10 kJ/(kg·K). "
    "Cooling water flows at 1.00 kg/s, entering at 25 °C and leaving at 40 °C, "
    "with a constant specific heat capacity of 4.18 kJ/(kg·K). "
    "The generator claims to produce 42.30 kW of electricity. "
    "The complete system is steady and insulated from its surroundings. "
    "Neglect pressure losses and changes in kinetic and potential energy."
)


class AutomaticScenarioTests(unittest.TestCase):
    def test_finite_stream_prose_produces_verdict_and_actual_code(self):
        response = solve({"scenario": TOUGH_SCENARIO})
        self.assertEqual(response["status"], "evaluated")
        result = response["result"]
        self.assertEqual(result["verdict"]["status"], "NOT FEASIBLE")
        self.assertTrue(result["checks"]["first_law"]["passed"])
        self.assertEqual(result["checks"]["second_law"], "FAIL")
        self.assertAlmostEqual(response["cases"]["finite_stream_engine"]["hot_stream"]["T_in_K"], 453.15)
        self.assertIn("0.50 kg/s", response["source_quotes"].values())
        self.assertTrue(any("def analyse_finite_stream_engine(" in item["source"] for item in response["calculation_code"]))

    def test_fixed_reservoir_prose_runs_directly(self):
        text = ("A heat engine operates between a hot reservoir at 600 K and a cold reservoir at 300 K. "
                "It receives 100 kW of heat and claims to generate 60 kW of electricity.")
        response = solve({"scenario": text})
        self.assertEqual(response["status"], "evaluated")
        self.assertEqual(response["result"]["verdict"]["status"], "NOT FEASIBLE")
        self.assertAlmostEqual(response["result"]["calculations"]["reversible_work_limit_kw"], 50)

    def test_walking_prose_runs_and_calculates_entropy(self):
        text = ("A generator produces electricity from walking. The mechanical power supplied to it is 8 W, "
                "and it claims an electrical output of 5 W. It rejects 3 W of heat at 26.85 °C.")
        response = solve({"scenario": text})
        self.assertEqual(response["status"], "evaluated")
        self.assertEqual(response["result"]["verdict"]["status"], "FEASIBLE / NOT REJECTED")
        self.assertAlmostEqual(response["result"]["calculations"]["S_gen_dot_kw_per_k"], .00001)

    def test_incomplete_description_keeps_numeric_fallback(self):
        response = solve({"scenario": "Generating electricity by walking"})
        self.assertEqual(response["status"], "needs_values")
        self.assertEqual(response["route"], "mechanical_power")
        self.assertIsNone(response["result"])

    def test_solar_and_chemical_prose(self):
        solar = solve({"scenario": "An ideal blackbody solar converter has source temperature 6000 K, "
                       "ambient temperature 300 K, irradiance 1000 W/m², collection area 2 m², "
                       "and claimed electrical output 1.8 kW."})
        self.assertEqual(solar["status"], "evaluated")
        self.assertEqual(solar["result"]["verdict"]["status"], "FEASIBLE / NOT REJECTED")
        chemical = solve({"scenario": "A fuel cell has reaction direction: H2 + 0.5 O2 to H2O(l); "
                          "Gibbs energy -237.141 kJ/mol reaction; reaction rate 0.01 mol/s; "
                          "claimed electrical output 2 kW."})
        self.assertEqual(chemical["status"], "evaluated")
        self.assertEqual(chemical["result"]["verdict"]["status"], "FEASIBLE / NOT REJECTED")

    def test_ambiguous_output_does_not_receive_a_verdict(self):
        text = ("A heat engine has hot reservoir 600 K and cold reservoir 300 K, "
                "receives 100 kW of heat, and claims to generate 50 to 60 kW.")
        response = solve({"scenario": text})
        self.assertEqual(response["status"], "needs_values")
        self.assertIsNone(response["result"])


if __name__ == "__main__":
    unittest.main()
