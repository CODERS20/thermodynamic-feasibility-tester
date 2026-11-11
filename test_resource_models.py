import json
import tempfile
import unittest
from pathlib import Path

from thermodynamic_feasibility_tester_MASTER import ThermoInputError, load_case, run_case


class ResourceModelTests(unittest.TestCase):
    def test_engine_work_above_all_heat_is_a_first_law_failure(self):
        case = {"model": "fixed_reservoir_engine", "T_hot_K": 600, "T_cold_K": 300,
                "Q_hot_kw": 100, "W_out_kw": 110}
        result = run_case(case)
        self.assertEqual(result.verdict.status, "NOT FEASIBLE")
        self.assertIn("First Law", result.verdict.reasons[0])
        self.assertEqual(result.checks["first_law"]["residual"], -10)
        self.assertFalse(result.checks["first_law"]["passed"])
        self.assertEqual(result.checks["second_law"], "NOT EVALUATED")
        self.assertIsNone(result.calculations["Q_cold_rejected_kw"])
        self.assertIsNone(result.calculations["S_gen_dot_kw_per_k"])
        supplied_rejection = run_case(dict(case, Q_cold_rejected_kw=3))
        self.assertEqual(supplied_rejection.checks["first_law"]["residual"], -13)
        with self.assertRaises(ThermoInputError):
            run_case(dict(case, Q_cold_rejected_kw=-10))

    def test_walking_claims_on_both_sides_of_ceiling(self):
        case = {
            "model": "mechanical_power",
            "recoverable_energy_per_event_j": 4,
            "events_per_s": 2,
        }
        for claim, expected in (
            (0.005, "FEASIBLE / NOT REJECTED"),
            (0.008, "FEASIBLE / NOT REJECTED"),
            (0.009, "NOT FEASIBLE"),
        ):
            with self.subTest(claim=claim):
                result = run_case(dict(case, W_out_kw=claim))
                self.assertAlmostEqual(result.calculations["reversible_power_limit_kw"], 0.008)
                self.assertEqual(result.verdict.status, expected)
                self.assertIn("temperature", result.checks["entropy_balance"])
        result = run_case({"model": "mechanical_power", "recoverable_mechanical_power_kw": 0, "W_out_kw": 1e-8})
        self.assertEqual(result.verdict.status, "NOT FEASIBLE")

    def test_walking_missing_or_ambiguous_data(self):
        result = run_case({"model": "mechanical_power", "description": "Generate electricity by walking"})
        self.assertEqual(result.verdict.status, "INSUFFICIENT DATA / MODEL REQUIRED")
        self.assertIn("recoverable_mechanical_power_kw", result.verdict.reasons[0])
        self.assertIn("W_out_kw", result.verdict.reasons[0])
        result = run_case({"model": "mechanical_power", "recoverable_energy_per_event_j": 4, "W_out_kw": 0.005})
        self.assertIn("events_per_s", result.verdict.reasons[0])
        with self.assertRaises(ThermoInputError):
            run_case({"model": "mechanical_power", "recoverable_mechanical_power_kw": 0.008,
                      "recoverable_energy_per_event_j": 4, "events_per_s": 2, "W_out_kw": 0.005})

    def test_mechanical_heat_and_entropy_balances(self):
        case = {"model": "mechanical_power", "recoverable_mechanical_power_kw": .008,
                "W_out_kw": .005, "heat_rejection_temperature_K": 300}
        inferred = run_case(case)
        self.assertAlmostEqual(inferred.calculations["heat_rejected_kw"], .003)
        self.assertAlmostEqual(inferred.calculations["S_gen_dot_kw_per_k"], .00001)
        self.assertEqual(inferred.checks["entropy_balance"], "PASS")
        measured = run_case(dict(case, heat_rejected_kw=.003))
        self.assertEqual(measured.checks["first_law_balance"], "PASS")
        invalid = run_case(dict(case, heat_rejected_kw=.004))
        self.assertEqual(invalid.verdict.status, "NOT FEASIBLE")
        self.assertEqual(invalid.checks["first_law_balance"], "FAIL")
        self.assertNotIn("S_gen_dot_kw_per_k", invalid.calculations)

    def test_ideal_radiation_limit(self):
        # Radiation is modelled as heat from a reservoir at T_source, so the
        # verdict uses the Carnot fraction 1 - T_0/T_source. At ambient/source
        # = 1/2 that is 1/2, giving a 1 kW ceiling on 2 kW incident. The Petela
        # radiation-exergy fraction (unfactored 17/24 of incident here) is
        # still reported, but as a stricter reference only.
        case = {"model": "solar_blackbody", "T_source_K": 600, "T_ambient_K": 300,
                "irradiance_W_m2": 1000, "collection_area_m2": 2}
        result = run_case(dict(case, W_out_kw=0.7))
        self.assertAlmostEqual(result.calculations["incident_radiation_kw"], 2)
        self.assertAlmostEqual(result.calculations["reversible_power_limit_kw"], 1.0)
        self.assertAlmostEqual(result.calculations["reversible_efficiency_fraction"], 0.5)
        self.assertAlmostEqual(result.calculations["petela_radiation_exergy_limit_kw"], 17 / 24)
        self.assertEqual(result.verdict.status, "FEASIBLE / NOT REJECTED")
        # The entropy balance is now closed, so a Clausius verdict exists.
        self.assertGreater(result.calculations["S_gen_kw_per_k"], 0)
        self.assertEqual(result.checks["second_law"], "PASS")
        self.assertEqual(run_case(dict(case, W_out_kw=1.05)).verdict.status, "NOT FEASIBLE")
        equal_temperatures = run_case(dict(case, T_source_K=300, W_out_kw=1e-8))
        self.assertEqual(equal_temperatures.calculations["reversible_power_limit_kw"], 0)
        self.assertEqual(equal_temperatures.verdict.status, "NOT FEASIBLE")

    def test_solar_matches_gemini_acceptance_case(self):
        """Design acceptance case: a 98% solar claim must be rejected by Clausius."""
        case = {"model": "solar_blackbody", "T_source_K": 5778, "T_ambient_K": 300,
                "irradiance_W_m2": 1000, "collection_area_m2": 1}
        result = run_case(dict(case, W_out_kw=0.980))
        self.assertAlmostEqual(result.calculations["reversible_efficiency_fraction"], 1 - 300 / 5778)
        self.assertLess(result.calculations["S_gen_kw_per_k"], 0)
        self.assertEqual(result.verdict.status, "NOT FEASIBLE")
        self.assertIn("SECOND LAW VIOLATION", result.checks["process_classification"])

    def test_reaction_entropy_balance_recovers_gibbs_limit(self):
        """With delta_H supplied, W_actual + W_lost must equal the -delta_G limit."""
        case = {"model": "reaction_gibbs", "reaction_direction": "H2 + 0.5 O2 to H2O(l)",
                "delta_G_kj_per_mol_rxn": -237.141, "delta_H_kj_per_mol_rxn": -285.83,
                "reaction_rate_mol_rxn_s": 0.01, "T_ambient_K": 298.15, "W_out_kw": 2.0}
        r = run_case(case)
        c = r.calculations
        self.assertAlmostEqual(c["E_in_kw"], 2.8583)
        self.assertAlmostEqual(c["delta_S_rxn_kj_per_mol_rxn_k"], (-285.83 + 237.141) / 298.15)
        self.assertAlmostEqual(c["W_actual_kw"] + c["lost_work_kw"],
                               c["reversible_power_limit_kw"], places=9)
        self.assertGreater(c["S_gen_kw_per_k"], 0)
        self.assertEqual(r.verdict.status, "FEASIBLE / NOT REJECTED")
        # Omitting delta_H keeps the original Gibbs-only behaviour.
        bare = run_case({k: v for k, v in case.items()
                         if k not in ("delta_H_kj_per_mol_rxn", "T_ambient_K")})
        self.assertNotIn("S_gen_kw_per_k", bare.calculations)
        self.assertIn("NOT EVALUATED", bare.checks["entropy_balance"])

    def test_signed_reaction_gibbs(self):
        case = {"model": "reaction_gibbs", "reaction_direction": "A to B",
                "reaction_rate_mol_rxn_s": 0.01}
        result = run_case(dict(case, delta_G_kj_per_mol_rxn=-200, W_out_kw=1))
        self.assertEqual(result.calculations["reversible_power_limit_kw"], 2)
        self.assertEqual(result.verdict.status, "FEASIBLE / NOT REJECTED")
        self.assertEqual(run_case(dict(case, delta_G_kj_per_mol_rxn=-200, W_out_kw=2.1)).verdict.status,
                         "NOT FEASIBLE")
        endergonic = run_case(dict(case, delta_G_kj_per_mol_rxn=200, W_out_kw=0))
        self.assertEqual(endergonic.calculations["signed_reversible_nonexpansion_work_kw"], -2)
        self.assertEqual(endergonic.calculations["minimum_external_work_input_kw"], 2)
        self.assertEqual(endergonic.verdict.status, "NOT FEASIBLE")

    def test_invalid_resource_values(self):
        invalid_cases = [
            {"model": "mechanical_power", "recoverable_mechanical_power_kw": -0.01, "W_out_kw": 0},
            {"model": "mechanical_power", "recoverable_mechanical_power_kw": True, "W_out_kw": 0},
            {"model": "mechanical_power", "recoverable_mechanical_power_kw": float("inf"), "W_out_kw": 0},
            {"model": "solar_blackbody", "T_source_K": 299, "T_ambient_K": 300,
             "irradiance_W_m2": 1000, "collection_area_m2": 2, "W_out_kw": 0.1},
            {"model": "reaction_gibbs", "reaction_direction": " ", "delta_G_kj_per_mol_rxn": -200,
             "reaction_rate_mol_rxn_s": 0.01, "W_out_kw": 1},
        ]
        for case in invalid_cases:
            with self.subTest(case=case), self.assertRaises(ThermoInputError):
                run_case(case)


if __name__ == "__main__":
    unittest.main()


class CaseFileTests(unittest.TestCase):
    CASE = {"model": "fixed_reservoir_engine", "T_hot_K": 600, "T_cold_K": 300,
            "Q_hot_kw": 100, "W_out_kw": 30}

    def _written(self, encoding):
        folder = tempfile.mkdtemp()
        path = Path(folder) / "case.json"
        path.write_text(json.dumps(self.CASE), encoding=encoding)
        return str(path)

    def test_case_file_accepts_a_byte_order_mark(self):
        """Windows editors and PowerShell redirection prepend a UTF-8 BOM."""
        for encoding in ("utf-8", "utf-8-sig"):
            with self.subTest(encoding=encoding):
                self.assertEqual(load_case(self._written(encoding)), self.CASE)

    def test_missing_and_malformed_case_files_are_reported(self):
        with self.assertRaises(ThermoInputError):
            load_case("no_such_case_file.json")
        folder = tempfile.mkdtemp()
        broken = Path(folder) / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ThermoInputError):
            load_case(str(broken))
