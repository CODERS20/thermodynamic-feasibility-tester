"""Build and evaluate the two CL 202 mock assignments with the M3 engine."""

import argparse
import json
import math
from pathlib import Path

import thermodynamic_feasibility_tester_MASTER as thermo


BASE_RANGE = range(0, 400)
MODIFIED_RANGE = range(1, 401)
WATER_CP_KJ_KG_K = 4.184
TAP_WATER_K = 298.15
BREW_WATER_K = 363.15
CUP_L = 0.25
POWDER_KG_PER_L = 0.060
# The assignments specify water density of 1 kg/L and 85% heater efficiency.
COFFEE_KJ_PER_L = WATER_CP_KJ_KG_K * (BREW_WATER_K - TAP_WATER_K) / 0.85


def base_assignment(suffix):
    if suffix not in BASE_RANGE:
        raise ValueError("Base requires a roll-number suffix from 000 to 399.")

    hot_flow = (200 + suffix) / 1000
    cold_flow = (500 + suffix) / 1000
    hot_out_K = 318.15
    hot_capacity_rate = hot_flow * WATER_CP_KJ_KG_K
    cold_capacity_rate = cold_flow * WATER_CP_KJ_KG_K
    heat_in_kw = 15 + suffix / 100
    cups_per_hour = 40 + suffix / 20
    claimed_kw = cups_per_hour * CUP_L * COFFEE_KJ_PER_L / 3600
    hot_in_K = hot_out_K + heat_in_kw / hot_capacity_rate
    heat_rejected_kw = heat_in_kw - claimed_kw
    cold_out_K = TAP_WATER_K + heat_rejected_kw / cold_capacity_rate

    case = {
        "model": "finite_stream_engine",
        "title": f"Assignment 1 Base (X={suffix:03d})",
        "description": "Cold outlet is derived from the claimed work and First Law.",
        "hot_stream": {
            "name": "GPU cooling water",
            "mass_flow_kg_s": hot_flow,
            "T_in_K": hot_in_K,
            "T_out_K": hot_out_K,
            "cp_model": "constant",
            "cp_kj_kg_k": WATER_CP_KJ_KG_K,
        },
        "cold_stream": {
            "name": "Heat-rejection tap water",
            "mass_flow_kg_s": cold_flow,
            "T_in_K": TAP_WATER_K,
            "T_out_K": cold_out_K,
            "cp_model": "constant",
            "cp_kj_kg_k": WATER_CP_KJ_KG_K,
        },
        "W_out_kw": claimed_kw,
        "apply_effective_temperature_limit": True,
    }
    result = thermo.run_case(case)
    calc = result.calculations

    # For the strict ceiling, the cold stream gains exactly the entropy the hot
    # stream loses. Its outlet temperature therefore differs from the claim's.
    hot_entropy_loss = -calc["hot_stream_property_results"]["delta_S_dot_kw_k"]
    reversible_cold_rise_K = TAP_WATER_K * math.expm1(hot_entropy_loss / cold_capacity_rate)
    max_work_kw = heat_in_kw - cold_capacity_rate * reversible_cold_rise_K
    max_coffee_l_per_hour = max_work_kw * 3600 / COFFEE_KJ_PER_L

    summary = {
        "Verdict": result.verdict.status,
        "Claimed cups per hour": cups_per_hour,
        "Heat input (kW)": heat_in_kw,
        "Claimed electrical output (kW)": claimed_kw,
        "Rejected heat at claimed output (kW)": heat_rejected_kw,
        "Hot water inlet (deg C)": hot_in_K - 273.15,
        "Cold water outlet at claimed output (deg C)": cold_out_K - 273.15,
        "Effective hot temperature (K)": calc["hot_effective_temperature_K"],
        "Effective cold temperature (K)": calc["cold_effective_temperature_K"],
        "Claimed efficiency (%)": calc["actual_efficiency_relative_to_hot_stream_heat_percent"],
        "Effective-temperature reference efficiency (%)": 100 * calc["effective_temperature_efficiency_reference"],
        "Entropy generation at claimed output (kW/K)": calc["S_gen_dot_kw_per_k"],
        "Reversible cold water outlet (K)": TAP_WATER_K + reversible_cold_rise_K,
        "Strict reversible power ceiling (kW)": max_work_kw,
        "Maximum coffee (L/h)": max_coffee_l_per_hour,
        "Maximum coffee powder (kg/h)": max_coffee_l_per_hour * POWDER_KG_PER_L,
    }
    return {"base": case}, summary


def modified_assignment(suffix, server_heat_kw=None):
    if suffix not in MODIFIED_RANGE:
        raise ValueError("Modified requires a roll-number suffix from 001 to 400.")
    if server_heat_kw is not None:
        server_heat_kw = thermo.positive(server_heat_kw, "Server heat budget")

    properties = {
        "model": "property_change",
        "title": f"Assignment 1 Modified gas and wax properties (X={suffix:03d})",
        "T1_K": 400 + 0.5 * suffix,
        "T2_K": 350.0,
        "cp_model": "linear",
        "a": 1.0,
        "b": 0.0005,
        "phase_delta_h_kj_kg": 250.0,
        "phase_delta_s_kj_kg_k": 0.80,
    }
    property_values = thermo.run_case(properties).calculations
    cups_per_hour = 50 + 0.1 * suffix
    gas_heat_kw = -0.1 * property_values["delta_h_kj_kg"]
    case = {
        "model": "fixed_reservoir_engine",
        "title": f"Assignment 1 Modified equivalent-temperature engine (X={suffix:03d})",
        "description": (
            "Gas temperature represents equivalent entropy transfer. "
            "The sink is isothermal paraffin melting."
        ),
        "T_hot_K": property_values["effective_temperature_K"],
        "T_cold_K": property_values["phase_change_temperature_K"],
        "Q_hot_kw": gas_heat_kw,
        "W_out_kw": cups_per_hour * CUP_L * COFFEE_KJ_PER_L / 3600,
    }
    result = thermo.run_case(case)
    calc = result.calculations
    max_work_kw = calc["reversible_work_limit_kw"]
    summary = {
        "Verdict": result.verdict.status,
        "Claimed cups per hour": cups_per_hour,
        "Gas heat released (kW)": gas_heat_kw,
        "Claimed electrical output (kW)": case["W_out_kw"],
        "Rejected heat at claimed output (kW)": calc["Q_cold_rejected_kw"],
        "Effective hot temperature (K)": case["T_hot_K"],
        "Wax melting temperature (K)": case["T_cold_K"],
        "Claimed efficiency (%)": calc["actual_efficiency_percent"],
        "Reversible efficiency (%)": calc["carnot_efficiency_percent"],
        "Entropy generation at claimed output (kW/K)": calc["S_gen_dot_kw_per_k"],
        "Reversible power ceiling (kW)": max_work_kw,
        "Maximum coffee (L/h)": max_work_kw * 3600 / COFFEE_KJ_PER_L,
        "Sink assumption": "Wax can absorb heat at its melting temperature.",
    }
    if server_heat_kw is not None:
        excess_kw = gas_heat_kw - server_heat_kw
        budget_passed = excess_kw <= 0 or thermo.is_close_to_zero(excess_kw, server_heat_kw)
        summary["Server heat budget (kW)"] = server_heat_kw
        summary["Server heat budget check"] = "PASS" if budget_passed else "FAIL"
        if not budget_passed:
            summary["Verdict"] = "NOT FEASIBLE"
            summary["Reason"] = "Gas heat exceeds the supplied server heat budget."
            summary["Reversible ceiling scope"] = "Conditional on the specified gas states."
    return {"modified_properties": properties, "modified_engine": case}, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suffix", type=int, help="Last three digits of the roll number.")
    parser.add_argument("--case", choices=("both", "base", "modified"), default="both")
    parser.add_argument("--output-dir", type=Path, help="Write the engine inputs as JSON.")
    parser.add_argument("--server-heat-kw", type=float, help="Optional heat budget for Modified.")
    args = parser.parse_args()

    suffix = args.suffix
    try:
        if args.case == "both" and suffix not in BASE_RANGE and suffix not in MODIFIED_RANGE:
            raise ValueError("Enter a roll-number suffix from 000 to 400.")
        run_base = args.case == "base" or (args.case == "both" and suffix in BASE_RANGE)
        run_modified = args.case == "modified" or (args.case == "both" and suffix in MODIFIED_RANGE)
        if args.server_heat_kw is not None and not run_modified:
            raise ValueError("--server-heat-kw requires an applicable Modified case.")

        reports = []
        if run_base:
            reports.append(("Base", *base_assignment(suffix)))
        if run_modified:
            reports.append(("Modified", *modified_assignment(suffix, args.server_heat_kw)))

        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
        if args.case == "both" and not run_base:
            print("Base skipped. Its suffix range is 000 to 399.")
        if args.case == "both" and not run_modified:
            print("Modified skipped. Its suffix range is 001 to 400.")
        for name, cases, summary in reports:
            print(f"\n{name} (X={suffix:03d})")
            for label, value in summary.items():
                formatted = f"{value:.8g}" if isinstance(value, float) else value
                print(f"  {label}: {formatted}")
            if args.output_dir:
                for key, case in cases.items():
                    path = args.output_dir / f"{key}_x{suffix:03d}.json"
                    path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
                    print(f"  Wrote {path}")
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
