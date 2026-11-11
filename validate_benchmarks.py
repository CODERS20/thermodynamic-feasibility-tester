"""Reproduce the numerical comparisons in the CL 202 manuscript."""

import json
import math

from run_mock_assignments import base_assignment, modified_assignment
from thermodynamic_feasibility_tester_MASTER import run_case


def benchmark_rows():
    """Return reference and computed results on the same basis."""
    # Independent hand calculations for the two assignment conditions at X=100.
    hot_in_K = 318.15 + 16 / (0.3 * 4.184)
    reversible_cold_out_K = 298.15 * math.sqrt(hot_in_K / 318.15)
    base_reference = 16 - 0.6 * 4.184 * (reversible_cold_out_K - 298.15)
    modified_reference = 12 - 312.5 * 0.1 * (math.log(450 / 350) + 0.0005 * 100)
    _, base = base_assignment(100)
    _, modified = modified_assignment(100)

    water = run_case({"model": "property_change", "T1_K": 298.15, "T2_K": 340,
                      "cp_model": "constant", "cp_kj_kg_k": 4.184})
    walking = run_case({"model": "mechanical_power", "recoverable_mechanical_power_kw": 0.0044,
                        "W_out_kw": 0.0024})
    solar = run_case({"model": "solar_blackbody", "T_source_K": 6000, "T_ambient_K": 300,
                      "irradiance_W_m2": 1000, "collection_area_m2": 2, "W_out_kw": 1.8})
    fuel_cell = run_case({"model": "reaction_gibbs", "reaction_direction": "H2 + 0.5 O2 to H2O(l)",
                          "delta_G_kj_per_mol_rxn": -237.141, "reaction_rate_mol_rxn_s": 0.01,
                          "W_out_kw": 2.0})
    comparisons = [
        ("Base at X=100", "kW", base_reference, base["Strict reversible power ceiling (kW)"],
         "CL 202 Base, independent energy and entropy balances"),
        ("Modified at X=100", "kW", modified_reference, modified["Reversible power ceiling (kW)"],
         "CL 202 Modified, independent gas and wax balances"),
        ("Liquid water sensible enthalpy", "kJ/kg", 3.153 / 0.01801528,
         water.calculations["delta_h_kj_kg"], "NIST-JANAF H-065, 298.15 to 340 K, 1 bar"),
        ("Knee harvester electrical output", "W", 2.4,
         1000 * walking.calculations["reversible_power_limit_kw"],
         "Li et al., measured electrical output compared with the ceiling from measured input"),
        ("Radiation ceiling, reservoir model", "kW", 2 * (1 - 300 / 6000),
         solar.calculations["reversible_power_limit_kw"],
         "Carnot bound on radiation treated as heat from a reservoir at T_sun; sets the verdict"),
        ("Radiation exergy reference, Petela", "kW", 2 * (1 - 4 * 0.05 / 3 + 0.05**4 / 3),
         solar.calculations["petela_radiation_exergy_limit_kw"],
         "Petela model, unfactored equation; reported as a stricter reference only"),
        ("Hydrogen fuel-cell ceiling", "kW", 2 * 96485.33212 * 1.229 * 0.01 / 1000,
         fuel_cell.calculations["reversible_power_limit_kw"], "NETL voltage reference and NIST-JANAF Gibbs input"),
    ]
    return [
        {"comparison": label, "unit": unit, "reference": expected, "computed": actual,
         "difference": actual - expected, "source": source}
        for label, unit, expected, actual, source in comparisons
    ]


if __name__ == "__main__":
    print(json.dumps(benchmark_rows(), indent=2))
