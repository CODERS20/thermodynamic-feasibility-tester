"""Local, evidence-preserving extraction for the supported engineering models."""

import re

from scenario_input import NUMBER, normalized_value, offline_extract, quote_is_grounded

POWER = r"(?:mW|kW|MW|W|(?:kilo|milli)?watts?)"
TEMP = r"(?:°\s*C|K|C|kelvins?|degrees?\s+Celsius)"
FLOW = r"(?:kg|g)\s*(?:/|per\s+)\s*(?:s|min|seconds?|minutes?)"
CP = r"(?:kJ|J)\s*/\s*(?:\(\s*kg\s*(?:[·/]\s*)?K\s*\)|kg\s*[·/]\s*K)"
LINK = r"\s*(?:(?:is|of|at|=|:)\s*)?"
OUTPUT = (
    r"(?:claims?\s+to\s+(?:produce|generate|deliver)|"
    r"claims?\s+(?:an?\s+)?(?:electrical\s+)?(?:power\s+)?output\s+of|"
    r"(?:claimed\s+)?electrical\s+(?:power\s+)?output|"
    r"claimed\s+(?:power|output)|output\s+power)"
)


def extract_case(text, route):
    values, quotes, issues = {}, {}, []

    def take(field, label, unit, kind, scope=text):
        pattern = rf"{label}{LINK}(?P<quantity>{NUMBER}\s*{unit})(?![\w/²])"
        found = []
        for match in re.finditer(pattern, scope, re.IGNORECASE):
            quote = match["quantity"]
            if not quote_is_grounded(quote, [text]):
                continue
            try:
                found.append((normalized_value(quote, kind), quote))
            except ValueError:
                continue
        unique = {value for value, _ in found}
        if len(unique) > 1:
            values.pop(field, None)
            quotes.pop(field, None)
            issues.append(f"Multiple values were supplied for {field.replace('_', ' ')}.")
        elif found:
            values[field], quotes[field] = found[0]

    # Retain the earlier explicitly labeled formats as well as natural prose.
    extracted = offline_extract([text])
    if extracted["route"] == route:
        from scenario_input import FIELD
        for fact in extracted["facts"]:
            field, quote = fact["field"], fact["quote"]
            if quote_is_grounded(quote, [text]):
                try:
                    values[field] = normalized_value(quote, FIELD[field][1])
                    quotes[field] = quote
                except ValueError:
                    pass

    take("W_out_kw", OUTPUT, POWER, "power")
    if route.startswith("assignment_"):
        take("suffix", r"(?:suffix|\bX)", "", "suffix")
        required = ["suffix"]
    elif route == "mechanical_power":
        take("recoverable_mechanical_power_kw",
             r"(?:mechanical\s+(?:input|power)(?:\s+supplied\s+to\s+(?:it|the generator))?|recoverable\s+(?:mechanical\s+)?power)",
             POWER, "power")
        take("recoverable_energy_per_event_j", r"(?:recoverable\s+(?:mechanical\s+)?energy|energy\s+recovered\s+per\s+step)",
             r"(?:kJ|J|joules?)(?:\s*(?:per|/)\s*step)?", "event_energy")
        take("events_per_s", r"(?:walking\s+rate|cadence|at)", r"steps?\s*(?:/|per\s+)\s*(?:s|min|seconds?|minutes?)", "event_rate")
        take("heat_rejected_kw", r"(?:rejects|rejected\s+heat|measured\s+heat\s+loss)", POWER, "power")
        take("heat_rejection_temperature_K", r"(?:heat\s+at|heat.rejection\s+temperature)", TEMP, "temperature")
        required = ["W_out_kw"]
        required += (["recoverable_mechanical_power_kw"] if "recoverable_mechanical_power_kw" in values
                     else ["recoverable_energy_per_event_j", "events_per_s"])
    elif route == "fixed_reservoir_engine":
        take("T_hot_K", r"(?:hot\s+(?:reservoir|source)(?:\s+temperature)?)", TEMP, "temperature")
        take("T_cold_K", r"(?:cold\s+(?:reservoir|sink)(?:\s+temperature)?)", TEMP, "temperature")
        take("Q_hot_kw", r"(?:receives|heat\s+(?:input|supplied)|heat.input\s+rate)", POWER, "power")
        take("Q_cold_rejected_kw", r"(?:rejects|rejected\s+heat)", POWER, "power")
        required = ["T_hot_K", "T_cold_K", "Q_hot_kw", "W_out_kw"]
    elif route == "finite_stream_engine":
        markers = list(re.finditer(
            r"\b(?P<hot>hot\s+(?:(?:thermal\s+)?oil|water|stream))\b|"
            r"\b(?P<cold>cooling\s+water|cold\s+(?:tap\s+)?water|cold\s+stream)\b", text, re.IGNORECASE))
        for index, marker in enumerate(markers):
            side = "hot_stream" if marker["hot"] else "cold_stream"
            scope = text[marker.start():markers[index+1].start() if index+1 < len(markers) else len(text)]
            take(f"{side}.mass_flow_kg_s", r"(?:flows?\s+at|(?:mass\s+)?flow(?:\s+rate)?)", FLOW, "mass_flow", scope)
            take(f"{side}.T_in_K", r"(?:entering|enters|inlet\s+temperature)", TEMP, "temperature", scope)
            take(f"{side}.T_out_K", r"(?:leaving|leaves|outlet\s+temperature)", TEMP, "temperature", scope)
            take(f"{side}.cp_kj_kg_k", r"(?:(?:constant\s+)?specific\s+heat(?:\s+capacity)?|Cp)", CP, "cp", scope)
        required = ["W_out_kw", *(f"{side}.{field}" for side in ("hot_stream", "cold_stream")
                                  for field in ("mass_flow_kg_s", "T_in_K", "T_out_K", "cp_kj_kg_k"))]
    elif route == "solar_blackbody":
        take("T_source_K", r"(?:source|sun)(?:\s+temperature)?", TEMP, "temperature")
        take("T_ambient_K", r"(?:ambient|environment)(?:\s+temperature)?", TEMP, "temperature")
        take("irradiance_W_m2", r"(?:incident\s+)?irradiance", r"(?:kW|W)\s*/\s*m(?:²|\^?2)", "irradiance")
        take("collection_area_m2", r"(?:collection\s+)?area", r"m(?:²|\^?2)", "area")
        required = ["T_source_K", "T_ambient_K", "irradiance_W_m2", "collection_area_m2", "W_out_kw"]
        if not re.search(r"black.?body|ideal\s+radiation", text, re.IGNORECASE):
            issues.append("Select the ideal blackbody model explicitly if its assumptions apply.")
    elif route == "reaction_gibbs":
        take("delta_G_kj_per_mol_rxn", r"(?:ΔG|delta\s*G|Gibbs\s+energy)", r"(?:kJ|J)/mol(?:\s+reaction)?", "molar_energy")
        take("reaction_rate_mol_rxn_s", r"(?:reaction\s+)?rate", r"(?:m?mol)/(?:s|min)", "molar_rate")
        direction = re.search(r"reaction\s+direction\s*[:=]\s*([^.;\n]+)", text, re.IGNORECASE)
        if direction:
            values["reaction_direction"] = quotes["reaction_direction"] = direction[1].strip()
        required = ["delta_G_kj_per_mol_rxn", "reaction_rate_mol_rxn_s", "reaction_direction", "W_out_kw"]
    else:
        return None, quotes, values, issues

    if issues or any(field not in values for field in required):
        return None, quotes, values, issues
    case = {"model": route, "description": text}
    for field, value in values.items():
        if "." in field:
            group, name = field.split(".")
            case.setdefault(group, {"name": group.replace("_", " "), "cp_model": "constant"})[name] = value
        else:
            case[field] = value
    if route == "finite_stream_engine":
        case["apply_effective_temperature_limit"] = True
    return case, quotes, values, issues
