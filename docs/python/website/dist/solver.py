"""Shared website interface to the original Python models."""

import json
import re
import inspect
import thermodynamic_feasibility_tester_MASTER as engine
import run_mock_assignments as assignments
from website.local_scenarios import extract_case

from run_mock_assignments import base_assignment, modified_assignment
from thermodynamic_feasibility_tester_MASTER import run_case


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
