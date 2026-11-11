import io
import json
import unittest
from unittest.mock import patch

import scenario_input as scenario
import thermodynamic_feasibility_tester_MASTER as thermo


WALKING = "Can I generate electricity by walking?"


def extraction(route, **quotes):
    return {"route": route, "facts": [{"field": name, "quote": value} for name, value in quotes.items()],
            "ambiguities": []}


class ScenarioInputTests(unittest.TestCase):
    def test_hot_server_water_scenario_asks_for_data_and_accepts_labeled_reply(self):
        text = (
            "Instead of letting this hot water cool off into the atmosphere, they propose "
            "a new proprietary technology. The device takes hot water from the servers, "
            "generates electricity, and rejects remaining heat into a stream of normal cold tap water. "
            "The electricity would run an office coffee maker."
        )
        result = scenario.analyze_scenario(text).as_dict()
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["route"], "finite_stream_engine")
        self.assertEqual(result["source_quotes"], {})
        self.assertTrue(any("hot stream inlet temperature" in question for question in result["questions"]))
        self.assertTrue(any("cold stream mass flow" in question for question in result["questions"]))
        self.assertTrue(any("output power" in question for question in result["questions"]))

        reply = (
            "Hot inlet temperature: 70 °C. Hot outlet temperature: 50 °C. Hot flow: 0.2 kg/s. "
            "Hot Cp: 4.184 kJ/(kg K). Cold inlet temperature: 20 °C. Cold outlet temperature: 27 °C. "
            "Cold flow: 0.4 kg/s. Cold Cp: 4.184 kJ/(kg K). Claimed power: 5.0208 kW."
        )
        result = scenario.analyze_scenario(text, replies=[reply]).as_dict()
        self.assertEqual(result["status"], "evaluated")
        self.assertAlmostEqual(result["cases"]["finite_stream_engine"]["hot_stream"]["T_in_K"], 343.15)
        self.assertTrue(result["result"]["checks"]["first_law"]["passed"])

    def test_walking_clarification_then_json_equivalence(self):
        turns = [WALKING]
        case, evidence, issues = scenario.prepare_case(turns, scenario.offline_extract(turns))
        self.assertIsNone(case)
        self.assertEqual(evidence, {})
        self.assertTrue(any("recoverable mechanical power" in issue for issue in issues))
        self.assertTrue(any("output power" in issue for issue in issues))

        turns.append("Recoverable energy is 4 J per step, at 120 steps per minute. Electrical output is 5 W.")
        case, evidence, issues = scenario.prepare_case(turns, scenario.offline_extract(turns))
        self.assertEqual(issues, [])
        self.assertEqual(evidence["events_per_s"], "120 steps per minute")
        _, actual = scenario.assess_case(case)
        expected = thermo.run_case({
            "model": "mechanical_power", "recoverable_energy_per_event_j": 4,
            "events_per_s": 2, "W_out_kw": 0.005,
        })
        self.assertEqual(actual.calculations, expected.calculations)
        self.assertEqual(actual.verdict, expected.verdict)

    def test_paraphrase_and_power_units(self):
        variants = (
            "Footsteps provide recoverable mechanical power of 8 watts. Target: 5 watts.",
            "Walking with recoverable power of 8000 mW and 0.005 kW of electrical output.",
        )
        for phrase in variants:
            with self.subTest(phrase=phrase):
                turns = [phrase]
                case, _, issues = scenario.prepare_case(turns, scenario.offline_extract(turns))
                self.assertEqual(issues, [])
                self.assertAlmostEqual(case["recoverable_mechanical_power_kw"], 0.008)
                self.assertAlmostEqual(case["W_out_kw"], 0.005)

    def test_ambiguous_invented_or_wrong_dimension_values_stop_assessment(self):
        for text, quote in (
            ("Output: 5 to 7 W.", "7 W"),
            ("Output: 5 W or 7 W.", "7 W"),
            ("Output is between 5 and 7 W.", "7 W"),
            ("Output is between 5 W and 7 W.", "5 W"),
            ("Output: -5 W.", "5 W"),
            ("Output: 0.005 W.", "005 W"),
            ("Output: 5 mW.", "5 MW"),
            ("Output: 5 W per event.", "5 W"),
            ("Output: 5 kJ.", "5 kJ"),
            ("Output: 5.", "5"),
            ("Output: 8 W.", "5 W"),
        ):
            with self.subTest(text=text, quote=quote):
                facts = extraction("mechanical_power", W_out_kw=quote)
                case, evidence, issues = scenario.prepare_case([text], facts)
                self.assertIsNone(case)
                self.assertNotIn("W_out_kw", evidence)
                self.assertTrue(issues)

    def test_conflicting_walking_claims(self):
        turns = [WALKING, "Recoverable power is 8 W. Output power is 5 W.", "Output power is 6 W."]
        case, _, issues = scenario.prepare_case(turns, scenario.offline_extract(turns))
        self.assertIsNone(case)
        self.assertTrue(any("unambiguous" in issue for issue in issues))

    def test_fixed_reservoir_temperatures_and_unsupported_route(self):
        text = "Cyclic engine between 326.85 °C and 26.85 °C, heat input 100 kW, claimed output 30000 W."
        facts = extraction("fixed_reservoir_engine", T_hot_K="326.85 °C", T_cold_K="26.85 °C",
                           Q_hot_kw="100 kW", W_out_kw="30000 W")
        case, _, issues = scenario.prepare_case([text], facts)
        self.assertEqual(issues, [])
        self.assertAlmostEqual(case["T_hot_K"], 600)
        self.assertAlmostEqual(case["T_cold_K"], 300)
        self.assertAlmostEqual(thermo.run_case(case).calculations["reversible_work_limit_kw"], 50)
        case, _, issues = scenario.prepare_case(["Combustion engine without property data."], extraction("unsupported"))
        self.assertIsNone(case)
        self.assertTrue(issues)

    def test_finite_stream_case_uses_normal_engine_structure(self):
        facts = {
            "W_out_kw": "1 kW",
            "hot_stream.mass_flow_kg_s": "0.3 kg/s", "hot_stream.T_in_K": "58 °C",
            "hot_stream.T_out_K": "45 °C", "hot_stream.cp_kj_kg_k": "4.184 kJ/(kg K)",
            "cold_stream.mass_flow_kg_s": "0.6 kg/s", "cold_stream.T_in_K": "25 °C",
            "cold_stream.T_out_K": "31 °C", "cold_stream.cp_kj_kg_k": "4.184 kJ/(kg K)",
        }
        case, _, issues = scenario.prepare_case([", ".join(facts.values())], extraction("finite_stream_engine", **facts))
        self.assertEqual(issues, [])
        self.assertEqual(case["hot_stream"]["cp_model"], "constant")
        self.assertAlmostEqual(case["cold_stream"]["T_in_K"], 298.15)
        self.assertEqual(thermo.run_case(case).model, "finite_stream_engine")

    def test_explicit_mock_assignments_reuse_builders(self):
        for variant, count, limit in (("Base", 1, 1.15306839), ("Modified", 2, 2.58392412)):
            with self.subTest(variant=variant):
                turns = [f"Run CL 202 Assignment 1 {variant} for suffix 100."]
                case, _, issues = scenario.prepare_case(turns, scenario.offline_extract(turns))
                self.assertEqual(issues, [])
                engine_cases, summary = scenario.assess_case(case)
                self.assertEqual(len(engine_cases), count)
                label = "Strict reversible power ceiling (kW)" if variant == "Base" else "Reversible power ceiling (kW)"
                self.assertAlmostEqual(summary[label], limit)

    def test_openai_structured_response_handoff(self):
        expected = extraction("mechanical_power", recoverable_mechanical_power_kw="8 W", W_out_kw="5 W")
        for fact in expected["facts"]:
            fact["item"] = None
        payload = {"status": "completed", "output": [
            {"type": "reasoning"},
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(expected)}]},
        ]}
        turns = [WALKING, "Recoverable power is 8 W; output is 5 W."]
        with patch("scenario_input.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as request:
            result = scenario.openai_extract(turns, "test-key", "test-model")
        sent = request.call_args.args[0]
        self.assertEqual(sent.full_url, "https://api.openai.com/v1/responses")
        body = json.loads(sent.data)
        self.assertEqual([message["content"] for message in body["input"]], turns)
        self.assertIs(body["text"]["format"]["strict"], True)
        fields = body["text"]["format"]["schema"]["properties"]["facts"]["items"]
        self.assertIn("item", fields["required"])
        self.assertIs(body["store"], False)
        self.assertEqual(result, expected)
        case, _, issues = scenario.prepare_case(turns, result)
        self.assertEqual(issues, [])
        self.assertEqual(thermo.run_case(case).verdict.status, "FEASIBLE / NOT REJECTED")

    def test_openai_refusal_has_no_verdict(self):
        payload = {"status": "completed", "output": [
            {"type": "message", "content": [{"type": "refusal", "refusal": "No extraction"}]},
        ]}
        with patch("scenario_input.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            with self.assertRaisesRegex(ValueError, "complete extraction"):
                scenario.openai_extract([WALKING], "test-key", "test-model")

    def test_machine_readable_handoff(self):
        pending = scenario.analyze_scenario(WALKING).as_dict()
        self.assertEqual(pending["status"], "needs_input")
        self.assertTrue(pending["questions"])
        self.assertEqual(pending["cases"], {})
        complete = scenario.analyze_scenario(WALKING, replies=[
            "Recoverable energy is 4 J per step, at 120 steps per minute. Electrical output is 5 W.",
        ]).as_dict()
        self.assertEqual(complete["status"], "evaluated")
        self.assertEqual(complete["cases"]["mechanical_power"]["W_out_kw"], 0.005)
        self.assertEqual(complete["source_quotes"]["W_out_kw"], "5 W")
        self.assertEqual(complete["result"]["verdict"]["status"], "FEASIBLE / NOT REJECTED")
        self.assertEqual(complete["result"]["calculations"]["reversible_power_limit_kw"], 0.008)
        json.dumps(complete, allow_nan=False)

    def test_closed_system_signed_heat_and_complete_json(self):
        text = "A closed system loses 30 kJ of energy and 0.04 kJ/K of entropy. Net work out is 10 kJ. It rejects 20 kJ at 300 K."
        facts = extraction("closed_system", delta_E_kj="-30 kJ", delta_S_system_kj_K="-0.04 kJ/K",
                           W_out_kj="10 kJ")
        facts["facts"].extend([
            {"field": "heat.heat_out_of_system_kj", "quote": "20 kJ", "item": 1},
            {"field": "heat.boundary_temperature_K", "quote": "300 K", "item": 1},
        ])
        # A signed state change must be grounded in a signed source quantity.
        pending = scenario.analyze_scenario(text, extractor=lambda _: facts).as_dict()
        self.assertEqual(pending["status"], "needs_input")
        signed = "Closed system: delta E = -30 kJ, delta S = -0.04 kJ/K. Work out is 10 kJ. Rejects 20 kJ at 300 K."
        result = scenario.analyze_scenario(signed, extractor=lambda _: facts).as_dict()
        self.assertEqual(result["status"], "evaluated")
        self.assertEqual(result["cases"]["closed_system"]["heat"], [
            {"heat_into_system_kj": -20.0, "boundary_temperature_K": 300.0},
        ])
        self.assertTrue(result["result"]["checks"]["first_law"]["passed"])

    def test_steady_flow_keeps_streams_separate_and_requires_explicit_heat_basis(self):
        text = ("Steady adiabatic control volume. Inlets are 0.5 kg/s at 120 kJ/kg and 1 kJ/(kg K), "
                "and 0.5 kg/s at 80 kJ/kg and 1.2 kJ/(kg K). Outlet is 1 kg/s at 80 kJ/kg "
                "and 1.2 kJ/(kg K). Work output is 20 kW.")
        facts = extraction("steady_control_volume", W_out_kw="20 kW", adiabatic="adiabatic")
        for group, item, values in (
            ("inlets", 1, ("0.5 kg/s", "120 kJ/kg", "1 kJ/(kg K)")),
            ("inlets", 2, ("0.5 kg/s", "80 kJ/kg", "1.2 kJ/(kg K)")),
            ("outlets", 1, ("1 kg/s", "80 kJ/kg", "1.2 kJ/(kg K)")),
        ):
            facts["facts"].extend({"field": f"{group}.{field}", "quote": quote, "item": item}
                                  for field, quote in zip(scenario.MASS_PROPERTIES, values))
        actual = scenario.analyze_scenario(text, extractor=lambda _: facts).as_dict()
        self.assertEqual(actual["status"], "evaluated")
        self.assertEqual(actual["cases"]["steady_control_volume"]["heat"], [])
        self.assertEqual(len(actual["cases"]["steady_control_volume"]["inlets"]), 2)
        self.assertTrue(actual["result"]["checks"]["mass_balance"]["passed"])
        self.assertTrue(actual["result"]["checks"]["first_law"]["passed"])
        pending = scenario.analyze_scenario(text.replace("adiabatic", "non-adiabatic"),
                                            extractor=lambda _: facts).as_dict()
        self.assertEqual(pending["status"], "needs_input")
        self.assertTrue(any("heat transfer" in question for question in pending["questions"]))

    def test_first_law_rejection_is_preserved_by_nlp(self):
        text = "Cyclic engine at 600 K and 300 K, receives 100 kW and claims 110 kW."
        facts = extraction("fixed_reservoir_engine", T_hot_K="600 K", T_cold_K="300 K",
                           Q_hot_kw="100 kW", W_out_kw="110 kW")
        actual = scenario.analyze_scenario(text, extractor=lambda _: facts).as_dict()
        self.assertEqual(actual["status"], "evaluated")
        self.assertEqual(actual["result"]["verdict"]["status"], "NOT FEASIBLE")
        self.assertIn("First Law", actual["result"]["verdict"]["reasons"][0])


if __name__ == "__main__":
    unittest.main()
