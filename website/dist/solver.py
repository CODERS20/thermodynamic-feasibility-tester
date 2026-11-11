"""Shared website interface to the original Python models."""

import json
import re
import inspect
import thermodynamic_feasibility_tester_MASTER as engine
import run_mock_assignments as assignments
from website.local_scenarios import extract_case

from run_mock_assignments import base_assignment, modified_assignment
from thermodynamic_feasibility_tester_MASTER import run_case
import feasibility_tester as flowchart


# Every quantity on the flowchart route is SI: W, J, J/K, K, kg/s.
FLOWCHART_ROUTE_NAMES = {
    ("thermal", "cycle"): "Thermal fluid - full thermodynamic cycle",
    ("thermal", "steady_flow"): "Thermal fluid - steady flow component",
    ("thermal", "closed"): "Thermal fluid - closed system process",
    ("chemical", "hs"): "Chemical reaction - standard enthalpy and entropy",
    ("chemical", "gibbs"): "Chemical reaction - Gibbs free energy",
    ("mechanical", "electrical"): "Work - electrical",
    ("mechanical", "kinetic"): "Work - kinetic fluid",
    ("mechanical", "potential"): "Work - potential gravity",
    ("mechanical", "shaft"): "Work - shaft rotational",
    ("mechanical", "boundary"): "Work - boundary pressure",
    ("mechanical", "generic"): "Work - generic work input",
    ("solar", None): "Solar radiative",
}

FLOWCHART_ASSUMPTIONS = {
    "thermal": ["Heat entering carries entropy Q_in / T_source.",
                "A full cycle returns the working fluid to its initial state, so Delta S_sys = 0."],
    "chemical": ["Chemical potential is stored internally, so no entropy crosses the boundary with it.",
                 "Delta S_sys is the entropy of reaction at the stated conditions."],
    "mechanical": ["Pure work carries zero entropy: Delta S_sys = 0 and Entropy_in = 0.",
                   "The hardware does not change state during steady operation."],
    "solar": ["Incoming radiation is treated as heat from a reservoir at the sun temperature.",
              "Its entropy flux is therefore Q_sun / T_sun."],
}


def _flowchart_backend(params):
    """Supply an ideal-gas backend when the inputs describe one.

    The guided route asks for explicit temperatures, so a backend is only
    needed for the closed-system internal-energy term and for solving an
    implicit state.
    """
    cp, R = params.get("cp"), params.get("R")
    if isinstance(cp, (int, float)) and isinstance(R, (int, float)):
        return flowchart.IdealGasBackend(cp=float(cp), R=float(R))
    return "auto"


def _flowchart_result(params, raw):
    """Shape a FeasibilityResult like a CaseResult so one renderer serves both."""
    domain = flowchart._canon(params.get("domain"), flowchart._DOMAIN, "domain")
    subtype = None
    for key in ("process_type", "data_type", "work_type"):
        if params.get(key) is not None:
            canon = {"process_type": flowchart._PROCESS, "data_type": flowchart._CHEM,
                     "work_type": flowchart._WORK}[key]
            subtype = flowchart._canon(params[key], canon, key)
            break
    title = FLOWCHART_ROUTE_NAMES.get((domain, subtype), f"{domain} route")

    reasons = []
    if raw.get("error"):
        reasons.append(raw["error"])
    if raw.get("S_gen") is not None:
        sign = "negative" if raw["S_gen"] < 0 else ("zero" if raw["S_gen"] == 0 else "positive")
        reasons.append(
            f"Universal entropy balance: S_gen = Delta S_sys - Entropy_in + Entropy_out "
            f"= {raw['S_gen']:.6g} W/K ({sign})."
        )
    if raw.get("W_lost") is not None:
        reasons.append(f"Gouy-Stodola lost work: W_lost = T_0 * S_gen = {raw['W_lost']:.6g} W.")
    reasons.extend(raw.get("notes") or [])

    calculations = {
        "E_in_W": raw["E_in"],
        "delta_S_sys_W_per_K": raw["dS_sys"],
        "entropy_in_W_per_K": raw["entropy_in"],
        "Q_out_W": raw["Q_out"],
        "entropy_out_W_per_K": raw["entropy_out"],
        "S_gen_W_per_K": raw["S_gen"],
        "W_actual_W": raw["W_actual"],
        "lost_work_W": raw["W_lost"],
        "reversible_work_limit_W": raw["W_rev_max"],
        "reversible_efficiency_fraction": raw["eta_rev"],
        "second_law_efficiency_fraction": raw["eta_II"],
        "T_0_K": raw["T_0"],
        "T_H_eff_K": raw["T_H_eff"],
        "T_sink_eff_K": raw.get("T_sink_eff"),
        "sink_basis": raw.get("sink_basis"),
        "reversible_limit_basis": raw["eta_rev_basis"],
    }
    first_law = "FAIL" if raw["verdict"].startswith("REJECT") else "PASS"
    second_law = "NOT EVALUATED"
    if raw["S_gen"] is not None:
        second_law = "FAIL" if raw["verdict"].startswith("IMPOSSIBLE") else "PASS"
    return {
        "title": title,
        "model": f"flowchart_{domain}" + (f"_{subtype}" if subtype else ""),
        "description": "Evaluated through the universal entropy-generation algorithm.",
        "inputs": params,
        "calculations": calculations,
        "checks": {
            "first_law": first_law,
            "second_law": second_law,
            "decision_path": " -> ".join(raw.get("path") or []),
            "process_classification": raw["verdict"],
        },
        "verdict": {"status": raw["verdict"], "reasons": reasons,
                    "scope_note": "Verdict within the stated model and supplied information."},
        "assumptions": FLOWCHART_ASSUMPTIONS.get(domain, []),
    }


def flowchart_code(domain):
    names = {"thermal": ["_thermal", "_converge"], "chemical": ["_chemical", "_converge"],
             "mechanical": ["_mechanical", "_converge"], "solar": ["_solar", "_converge"]}
    code = [{"name": f"FeasibilityTester.{name}",
             "source": inspect.getsource(getattr(flowchart.FeasibilityTester, name))}
            for name in names.get(domain, [])]
    code.append({"name": "_sink_temperature",
                 "source": inspect.getsource(flowchart.FeasibilityTester._sink_temperature)})
    return code


def solve_flowchart(params):
    if not isinstance(params, dict):
        raise ValueError("Supply the flowchart inputs as an object.")
    tester = flowchart.FeasibilityTester(backend=_flowchart_backend(params))
    try:
        raw = tester.evaluate(params)
    except flowchart.FeasibilityError as error:
        raise ValueError(str(error)) from error
    domain = flowchart._canon(params.get("domain"), flowchart._DOMAIN, "domain")
    result = _flowchart_result(params, raw)
    return {"status": "evaluated", "route": result["model"], "questions": [],
            "source_quotes": {}, "cases": {"flowchart": params}, "result": result,
            "calculation_code": flowchart_code(domain)}


def calculation_code(route):
    names = {
        "mechanical_power": ["analyse_mechanical_power", "resource_result", "make_verdict"],
        "fixed_reservoir_engine": ["analyse_fixed_reservoir_engine", "carnot_efficiency",
                                   "fixed_reservoir_entropy_generation", "make_verdict"],
        "finite_stream_engine": ["analyse_finite_stream_engine", "stream_properties",
                                 "properties_constant_cp", "properties_linear_cp", "effective_temperature", "make_verdict"],
        "solar_blackbody": ["analyse_solar_blackbody", "resource_result", "make_verdict"],
        "reaction_gibbs": ["analyse_reaction_gibbs", "resource_result", "make_verdict"],
        "assignment_base": ["analyse_finite_stream_engine", "properties_constant_cp", "make_verdict"],
        "assignment_modified": ["analyse_property_change", "properties_linear_cp", "phase_change_temperature",
                                "analyse_fixed_reservoir_engine", "make_verdict"],
    }
    code = [{"name": name, "source": inspect.getsource(getattr(engine, name))}
            for name in names.get(route, [])]
    if route.startswith("assignment_"):
        function = assignments.base_assignment if route == "assignment_base" else assignments.modified_assignment
        code.insert(0, {"name": function.__name__, "source": inspect.getsource(function)})
    return code


def solve(request):
    if not isinstance(request, dict):
        raise ValueError("Supply a scenario or a model case.")
    if "flowchart" in request:
        return solve_flowchart(request["flowchart"])
    if "case" in request:
        case = request["case"]
        if case.get("model") == "assignment_base":
            cases, summary = base_assignment(case["suffix"])
            return {"status": "evaluated", "route": case["model"], "cases": cases, "result": summary,
                    "calculation_code": calculation_code(case["model"])}
        if case.get("model") == "assignment_modified":
            cases, summary = modified_assignment(case["suffix"])
            return {"status": "evaluated", "route": case["model"], "cases": cases, "result": summary,
                    "calculation_code": calculation_code(case["model"])}
        result = run_case(case)
        return {"status": "evaluated", "route": result.model, "questions": [],
                "source_quotes": {}, "cases": {result.model: case}, "result": result.as_dict(),
                "calculation_code": calculation_code(result.model)}

    scenario = request.get("scenario")
    if not isinstance(scenario, str) or not 0 < len(scenario.strip()) <= 3000:
        raise ValueError("Enter between 1 and 3,000 characters.")
    route = None
    if re.search(r"\b(?:CL\s*202|Assignment\s*1|mock assignment)\b", scenario, re.IGNORECASE):
        variants = set(re.findall(r"\b(base|modified)\b", scenario.casefold()))
        if len(variants) == 1:
            route = "assignment_" + variants.pop()
    if route is None:
        for candidate, pattern in (
            ("finite_stream_engine", r"\b(?:hot (?:thermal )?oil|hot water|hot stream|cold water|cooling water|cold tap water)\b"),
            ("solar_blackbody", r"\b(?:solar|sunlight|radiation)\b"),
            ("reaction_gibbs", r"\b(?:fuel cell|chemical|gibbs|reaction|battery)\b"),
            ("fixed_reservoir_engine", r"\b(?:heat engine|reservoir|carnot)\b"),
            ("mechanical_power", r"\b(?:walking|footsteps?|mechanical|pedal|pedaling)\b"),
        ):
            if re.search(pattern, scenario, re.IGNORECASE):
                route = candidate
                break
    case, quotes, values, issues = extract_case(scenario, route)
    if case is not None:
        response = solve({"case": case})
        response["source_quotes"] = quotes
        return response
    return {"status": "needs_values", "route": route, "cases": {}, "result": None,
            "source_quotes": quotes, "prefill": values, "issues": issues}


def solve_json(payload):
    try:
        return json.dumps(solve(json.loads(payload)), allow_nan=False)
    except (ValueError, OverflowError) as error:
        return json.dumps({"error": str(error)})
