"""Run with:  python -m unittest test_feasibility -v"""
import math
import unittest

from feasibility_tester import (FeasibilityTester, IdealGasBackend, InputError,
                                PreCheckError, brent, bisect_root)

AIR = IdealGasBackend(cp=1005.0, R=287.0, T_ref=300.0, P_ref=1e5)


def cycle(W):
    return {"domain": "thermal_fluid", "process_type": "cycle",
            "Q_in": 1000, "T_source": 600, "W_actual": W, "T_0": 300}


class Tests(unittest.TestCase):
    def setUp(self):
        self.ft = FeasibilityTester(backend=AIR)

    # ---- Carnot cycle: the three Second-Law verdicts ----
    def test_cycle_reversible_at_carnot(self):
        r = self.ft.evaluate(cycle(500))                  # eta_rev = 0.5
        self.assertEqual(r["verdict"], "REVERSIBLE LIMIT")
        self.assertAlmostEqual(r["eta_rev"], 0.5)
        self.assertAlmostEqual(r["eta_II"], 1.0)

    def test_cycle_feasible(self):
        r = self.ft.evaluate(cycle(400))
        self.assertEqual(r["verdict"], "FEASIBLE")
        self.assertAlmostEqual(r["S_gen"], 1 / 3, places=6)
        self.assertAlmostEqual(r["W_lost"], 100.0, places=6)
        self.assertAlmostEqual(r["eta_II"], 0.8, places=6)

    def test_cycle_impossible(self):
        r = self.ft.evaluate(cycle(600))
        self.assertEqual(r["verdict"], "IMPOSSIBLE (Second Law Violation)")
        self.assertLess(r["S_gen"], 0)

    def test_first_law_reject(self):
        r = self.ft.evaluate(cycle(1200))
        self.assertTrue(r["verdict"].startswith("REJECT"))
        self.assertIsNone(r["S_gen"])

    # ---- other domains ----
    def test_electrical(self):
        r = self.ft.evaluate({"domain": 3, "work_type": "electrical", "V": 230, "I": 10,
                              "W_actual": 2000, "T_0": 298.15})
        self.assertEqual(r["verdict"], "FEASIBLE")
        self.assertAlmostEqual(r["E_in"], 2300)
        self.assertAlmostEqual(r["eta_rev"], 1.0)

    def test_solar_default_sun_temp(self):
        ok = self.ft.evaluate({"domain": "solar", "Q_sun": 1000, "W_actual": 900, "T_0": 300})
        bad = self.ft.evaluate({"domain": "solar", "Q_sun": 1000, "W_actual": 960, "T_0": 300})
        self.assertEqual(ok["verdict"], "FEASIBLE")
        self.assertTrue(bad["verdict"].startswith("IMPOSSIBLE"))

    def test_chemical_gibbs_matches_hs(self):
        a = self.ft.evaluate({"domain": "chemical", "data_type": "gibbs", "delta_H": -286000,
                              "delta_G": -237000, "T_0": 298.15, "W_actual": 200000})
        dS = (-286000 + 237000) / 298.15
        b = self.ft.evaluate({"domain": "chemical", "data_type": "enthalpy_entropy",
                              "delta_H": -286000, "delta_S": dS, "T_0": 298.15,
                              "W_actual": 200000})
        self.assertAlmostEqual(a["S_gen"], b["S_gen"], places=9)

    # ---- steady flow: T_eff / Carnot consistency ----
    def test_steady_flow_constant_cp(self):
        p = {"domain": "thermal_fluid", "process_type": "steady_flow", "mass_flow": 1.0,
             "cp": 1005, "state1": {"T": 800}, "state2": {"T": 500}, "T_0": 300}
        w_rev = 301500 - 300 * 1005 * math.log(800 / 500)
        r = self.ft.evaluate({**p, "W_actual": w_rev})
        self.assertEqual(r["verdict"], "REVERSIBLE LIMIT")
        self.assertAlmostEqual(r["W_rev_max"], w_rev, places=6)
        self.assertAlmostEqual(r["eta_rev"] * r["E_in"], w_rev, places=4)  # Carnot == universal

    def test_variable_cp_matches_constant(self):
        base = {"domain": "thermal_fluid", "process_type": "steady_flow", "mass_flow": 2.0,
                "state1": {"T": 800}, "state2": {"T": 500}, "T_0": 300, "W_actual": 1000}
        a = self.ft.evaluate({**base, "cp": 1005})
        b = self.ft.evaluate({**base, "cp_polynomial": [1005.0]})
        self.assertAlmostEqual(a["S_gen"], b["S_gen"], places=6)

    def test_missing_state_root_finding(self):
        p = {"domain": "thermal_fluid", "process_type": "steady_flow", "mass_flow": 1.0,
             "state1": {"T": 800, "P": 1e6}, "state2": {"P": 1e5, "h": 1005 * 200},
             "T_0": 300, "W_actual": 1000}
        for method in ("brent", "bisection"):
            r = FeasibilityTester(backend=AIR, root_method=method).evaluate(p)
            self.assertTrue(any("root_finding" in s for s in r["path"]))
            self.assertAlmostEqual(r["E_in"], 1005 * (800 - 500), places=3)  # h1 - h2, T2 solved = 500 K

    def test_closed_system(self):
        r = self.ft.evaluate({"domain": "thermal_fluid", "process_type": "closed", "mass": 1.0,
                              "cp": 1005, "cv": 718, "state1": {"T": 500}, "state2": {"T": 400},
                              "T_0": 300, "W_actual": 3000})
        self.assertAlmostEqual(r["E_in"], 71800)
        self.assertEqual(r["verdict"], "FEASIBLE")
        self.assertAlmostEqual(r["W_rev_max"], 71800 - 300 * 1005 * math.log(500 / 400), places=4)

    # ---- Step 0 ----
    def test_prechecks(self):
        with self.assertRaises(PreCheckError):
            self.ft.evaluate({**cycle(100), "T_source": -5})
        with self.assertRaises(PreCheckError):
            self.ft.evaluate({**cycle(100), "eta": 1.2})
        with self.assertRaises(PreCheckError):
            self.ft.evaluate({**cycle(100), "units": "imperial"})
        with self.assertRaises(InputError):
            self.ft.evaluate({"domain": "thermal_fluid", "process_type": "cycle", "T_0": 300,
                              "W_actual": 1, "T_source": 500})   # Q_in missing

    def test_claimed_efficiency(self):
        r = self.ft.evaluate({"domain": "thermal_fluid", "process_type": "cycle", "Q_in": 1000,
                              "T_source": 600, "T_0": 300, "eta_claimed": 0.6})
        self.assertTrue(r["verdict"].startswith("IMPOSSIBLE"))

    def test_root_solvers(self):
        f = lambda x: x ** 3 - 2 * x - 5
        self.assertAlmostEqual(brent(f, 2, 3), 2.0945514815, places=8)
        self.assertAlmostEqual(bisect_root(f, 2, 3), 2.0945514815, places=8)

    # ---- Decision 3: sink that is a finite stream, not an infinite reservoir ----
    def test_finite_sink_stream_matches_exact_two_stream_balance(self):
        """A warming sink stream must reproduce the exact two-stream entropy balance.

        Pinning the sink at T_0 treats it as infinite and overstates S_gen. Supplying
        the sink stream's own inlet/outlet makes Q_out / T_sink_eff identically equal
        to that stream's entropy rise, so the universal equation becomes exact.
        """
        cp, m_hot, m_cold = 4184.0, 0.3, 0.6
        T_hot_out, T_cold_in = 318.15, 298.15
        T_hot_in = T_hot_out + 16000 / (m_hot * cp)
        W = 999.85294
        T_cold_out = T_cold_in + (16000 - W) / (m_cold * cp)

        water = IdealGasBackend(cp=cp, R=0.0, T_ref=273.15)
        ft = FeasibilityTester(backend=water)
        case = {"domain": "thermal_fluid", "process_type": "steady_flow", "mass_flow": m_hot,
                "cp": cp, "state1": {"T": T_hot_in}, "state2": {"T": T_hot_out},
                "T_0": T_cold_in, "W_actual": W}

        exact = (m_hot * cp * math.log(T_hot_out / T_hot_in)
                 + m_cold * cp * math.log(T_cold_out / T_cold_in))

        with_sink = ft.evaluate({**case, "sink_T_in": T_cold_in, "sink_T_out": T_cold_out})
        self.assertAlmostEqual(with_sink["S_gen"], exact, places=9)
        self.assertAlmostEqual(with_sink["T_sink_eff"], 301.127721, places=5)

        # Default (no sink data) still assumes the ambient reservoir, and overstates S_gen.
        default = ft.evaluate(case)
        self.assertAlmostEqual(default["T_sink_eff"], T_cold_in, places=9)
        self.assertGreater(default["S_gen"], 1.9 * exact)

    def test_explicit_sink_temperature_and_validation(self):
        r = self.ft.evaluate({**cycle(400), "T_sink": 320})
        self.assertAlmostEqual(r["T_sink_eff"], 320.0, places=9)
        self.assertAlmostEqual(r["entropy_out"], 600 / 320, places=9)
        self.assertAlmostEqual(r["S_gen"], 600 / 320 - 1000 / 600, places=9)
        # a sink stream must actually absorb heat
        with self.assertRaises(InputError):
            self.ft.evaluate({**cycle(400), "sink_T_in": 310, "sink_T_out": 300})
        with self.assertRaises(PreCheckError):
            self.ft.evaluate({**cycle(400), "T_sink": -5})


if __name__ == "__main__":
    unittest.main()
