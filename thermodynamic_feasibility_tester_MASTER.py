#!/usr/bin/env python3
"""THERMODYNAMIC FEASIBILITY TESTER — MASTER ENGINE

Purpose
-------
A single, extensible program for testing proposed useful-work processes using
structured thermodynamic inputs. The user manually maps a problem statement
into the fields requested by the program (or supplies a JSON case file).
Natural-language extraction is a separate layer.

Implemented routes
------------------
A. Thermal source/sink route
   1. Fixed-temperature reservoir cyclic heat engine: Carnot limit, First Law,
      entropy generation and a three-way verdict.
   2. Finite hot/cold streams: signed Delta h and Delta s, total rates,
      effective temperatures, First Law consistency, S_gen and an optional
      effective-temperature reversible-reference comparison. The latter is
      explicitly an approximation/model assumption, NOT a universal Carnot
      theorem for every finite-stream arrangement.

B. Reusable entropy-balance route
   3. General steady control volume: mass-stream entropy and energy balances,
      heat interactions and boundary temperatures.
   4. Closed system: First Law and entropy-generation checks.

C. Supporting property / numerical tools
   5. Constant Cp, linear Cp(T)=a+bT, user-supplied numerical Cp(T), phase-
      change temperature, adaptive Simpson integration and bisection.

D. Ideal resource limits
   6. Mechanical-to-electric conversion from recoverable mechanical power.
   7. Undiluted blackbody radiation with a Petela–Landsberg bound.
   8. Isothermal, isobaric reaction with supplied signed molar Gibbs energy.

Other resource models, transient systems, and EOS/property databases require
additional modelling. Unsupported cases return INSUFFICIENT DATA / MODEL REQUIRED.

Units
-----
T: K; specific h: kJ/kg; specific s: kJ/(kg K); Cp: kJ/(kg K);
mass flow: kg/s; heat/work rates: kW (= kJ/s); total heat/work: kJ;
entropy-generation rate: kW/K; entropy generation: kJ/K.

Sign conventions
----------------
Heat into the selected device/system boundary is positive.
Work out of the selected device/system boundary is positive.
Stream Delta h and Delta s are signed outlet-minus-inlet changes.
For a hot source stream, Delta h and Delta s are normally negative;
for a warmed cold sink stream, they are normally positive.

No third-party packages are required. Compatible with Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

ABS_TOL = 1.0e-8
REL_TOL = 1.0e-6
S_GEN_TOL = 1.0e-8


# ============================================================================
# 1. Validation and shared result objects
# ============================================================================

class ThermoInputError(ValueError):
    """Raised for missing, invalid, or physically inconsistent input data."""


def number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ThermoInputError(f"{label} must be numeric.") from exc
    if not math.isfinite(result):
        raise ThermoInputError(f"{label} must be finite.")
    return result


def positive(value: Any, label: str) -> float:
    result = number(value, label)
    if result <= 0.0:
        raise ThermoInputError(f"{label} must be greater than zero.")
    return result


def positive_temperature(value: Any, label: str = "Temperature") -> float:
    result = number(value, label)
    if result <= 0.0:
        raise ThermoInputError(f"{label} must be above 0 K. Enter absolute temperature in Kelvin.")
    return result


def is_close_to_zero(value: float, scale: float = 1.0) -> bool:
    return abs(value) <= ABS_TOL + REL_TOL * max(abs(scale), 1.0)


def check_required(data: Dict[str, Any], fields: Sequence[str], context: str) -> None:
    missing = [field for field in fields if field not in data or data[field] is None]
    if missing:
        raise ThermoInputError(f"Missing {context} field(s): {', '.join(missing)}.")


@dataclass
class BalanceCheck:
    residual: float
    passed: bool
    equation: str
    units: str


@dataclass
class Verdict:
    status: str
    reasons: List[str]
    scope_note: str = (
        "Thermodynamic verdict within the stated model and supplied information; "
        "this does not establish practical, economic, or engineering viability."
    )


@dataclass
class CaseResult:
    title: str
    model: str
    description: str
    inputs: Dict[str, Any]
    calculations: Dict[str, Any]
    checks: Dict[str, Any]
    verdict: Verdict
    assumptions: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "model": self.model,
            "description": self.description,
            "inputs": self.inputs,
            "calculations": self.calculations,
            "checks": self.checks,
            "verdict": asdict(self.verdict),
            "assumptions": self.assumptions,
        }


def entropy_generation_is_negative(sgen: float) -> bool:
    return sgen < -(ABS_TOL + REL_TOL * max(abs(sgen), 1.0))


def entropy_generation_is_reversible(sgen: float) -> bool:
    return abs(sgen) <= (ABS_TOL + REL_TOL * max(abs(sgen), 1.0))


def process_classification(
    sgen: Optional[float],
    first_law: Optional[BalanceCheck] = None,
    mass_balance: Optional[BalanceCheck] = None,
    performance_limit_passed: Optional[bool] = None,
) -> str:
    """Classify the stated process as reversible, irreversible, or impossible."""
    if first_law is not None and not first_law.passed:
        return "IMPOSSIBLE UNDER THE STATED MODEL"
    if mass_balance is not None and not mass_balance.passed:
        return "IMPOSSIBLE UNDER THE STATED STEADY-STATE MODEL"
    if sgen is not None and entropy_generation_is_negative(sgen):
        return "IMPOSSIBLE — SECOND LAW VIOLATION"
    if performance_limit_passed is False:
        return "IMPOSSIBLE — REVERSIBLE LIMIT EXCEEDED"
    if sgen is None:
        return "NOT CLASSIFIED — ENTROPY BALANCE NOT AVAILABLE"
    if entropy_generation_is_reversible(sgen):
        return "REVERSIBLE (LIMITING CASE)"
    return "IRREVERSIBLE (SECOND-LAW ADMISSIBLE)"


def make_verdict(
    first_law: Optional[BalanceCheck] = None,
    sgen: Optional[float] = None,
    work_out: Optional[float] = None,
    work_limit: Optional[float] = None,
    model_limit_valid: bool = False,
    extra_reasons: Optional[List[str]] = None,
    mass_balance: Optional[BalanceCheck] = None,
    work_limit_tolerance: Optional[float] = None,
) -> Verdict:
    """Apply the common three-way verdict logic without overstating certainty."""
    reasons: List[str] = list(extra_reasons or [])
    violations: List[str] = []

    if first_law is not None and not first_law.passed:
        violations.append(
            f"First Law consistency check failed: residual = {first_law.residual:.6g} {first_law.units}."
        )
    if mass_balance is not None and not mass_balance.passed:
        violations.append(
            f"Steady-state mass balance failed: residual = {mass_balance.residual:.6g} {mass_balance.units}."
        )
    if sgen is not None and entropy_generation_is_negative(sgen):
        violations.append(
            f"Entropy generation is negative ({sgen:.6g}); this violates the Second Law for the stated boundary/model."
        )
    if (
        work_out is not None
        and work_limit is not None
        and work_out - work_limit > (
            ABS_TOL + REL_TOL * max(abs(work_limit), 1.0)
            if work_limit_tolerance is None else work_limit_tolerance
        )
    ):
        violations.append(
            f"Claimed useful work ({work_out:.6g}) exceeds the modelled reversible upper limit ({work_limit:.6g})."
        )

    if violations:
        return Verdict("NOT FEASIBLE", violations + reasons)

    if sgen is not None:
        if entropy_generation_is_reversible(sgen):
            reasons.append("S_gen is approximately zero: reversible limiting case within numerical tolerance.")
        else:
            reasons.append("S_gen is positive: irreversible, but Second-Law admissible for the stated model.")
    if first_law is not None and first_law.passed:
        reasons.append("First Law balance is satisfied within numerical tolerance.")

    if model_limit_valid:
        if work_out is not None and work_limit is not None:
            reasons.append("Claimed work does not exceed the reversible limit used by this model.")
        return Verdict("FEASIBLE / NOT REJECTED", reasons)

    reasons.append(
        "The available balance checks do not establish a defensible reversible performance limit."
    )
    return Verdict("INSUFFICIENT DATA / MODEL REQUIRED", reasons)


# ============================================================================
# 2. Thermodynamic property calculations
# ============================================================================

def properties_constant_cp(T1: float, T2: float, cp: float) -> Tuple[float, float]:
    """Signed (delta_h, delta_s) for a constant-Cp temperature change."""
    T1 = positive_temperature(T1, "T1")
    T2 = positive_temperature(T2, "T2")
    cp = positive(cp, "Cp")
    delta_h = cp * (T2 - T1)
    delta_s = cp * math.log(T2 / T1)
    return delta_h, delta_s


def properties_linear_cp(
    T1: float, T2: float, a: float, b: float
) -> Tuple[float, float]:
    """Signed property changes for Cp(T)=a+bT, with Cp positive throughout."""
    T1 = positive_temperature(T1, "T1")
    T2 = positive_temperature(T2, "T2")
    a, b = number(a, "Cp coefficient a"), number(b, "Cp coefficient b")
    cp1, cp2 = a + b * T1, a + b * T2
    if min(cp1, cp2) <= 0.0:
        raise ThermoInputError("Cp(T)=a+bT must remain positive over the entire temperature interval.")
    delta_h = a * (T2 - T1) + 0.5 * b * (T2**2 - T1**2)
    delta_s = a * math.log(T2 / T1) + b * (T2 - T1)
    return delta_h, delta_s


def _simpson_segment(f: Callable[[float], float], a: float, b: float,
                     fa: float, fm: float, fb: float) -> float:
    return (b - a) * (fa + 4.0 * fm + fb) / 6.0


def adaptive_simpson(
    function: Callable[[float], float],
    lower: float,
    upper: float,
    tolerance: float = 1.0e-8,
    max_depth: int = 18,
) -> float:
    """Adaptive Simpson integration for a smooth, finite scalar function."""
    if lower == upper:
        return 0.0
    if upper < lower:
        return -adaptive_simpson(function, upper, lower, tolerance, max_depth)
    if tolerance <= 0 or max_depth < 1:
        raise ThermoInputError("Integration tolerance and maximum depth must be positive.")

    midpoint = 0.5 * (lower + upper)
    f_lower, f_mid, f_upper = function(lower), function(midpoint), function(upper)
    whole = _simpson_segment(function, lower, upper, f_lower, f_mid, f_upper)

    def refine(a: float, b: float, fa: float, fm: float, fb: float,
               estimate: float, tol: float, depth: int) -> float:
        mid = 0.5 * (a + b)
        left_mid, right_mid = 0.5 * (a + mid), 0.5 * (mid + b)
        flm, frm = function(left_mid), function(right_mid)
        left_est = _simpson_segment(function, a, mid, fa, flm, fm)
        right_est = _simpson_segment(function, mid, b, fm, frm, fb)
        delta = left_est + right_est - estimate
        if depth <= 0 or abs(delta) <= 15.0 * tol:
            return left_est + right_est + delta / 15.0
        return (
            refine(a, mid, fa, flm, fm, left_est, tol / 2.0, depth - 1)
            + refine(mid, b, fm, frm, fb, right_est, tol / 2.0, depth - 1)
        )

    return refine(lower, upper, f_lower, f_mid, f_upper, whole, tolerance, max_depth)


def properties_numerical(
    T1: float,
    T2: float,
    cp_function: Callable[[float], float],
) -> Tuple[float, float]:
    """Calculate delta_h=integral(Cp dT), delta_s=integral(Cp/T dT)."""
    T1 = positive_temperature(T1, "T1")
    T2 = positive_temperature(T2, "T2")

    def cp_checked(T: float) -> float:
        cp = positive(cp_function(T), f"Cp({T:g} K)")
        return cp

    delta_h = adaptive_simpson(cp_checked, T1, T2)
    delta_s = adaptive_simpson(lambda T: cp_checked(T) / T, T1, T2)
    return delta_h, delta_s


def effective_temperature(delta_h: float, delta_s: float) -> float:
    """Return |Delta h|/|Delta s|; this is an equivalent descriptor, not magic Carnot data."""
    dh, ds = number(delta_h, "Delta h"), number(delta_s, "Delta s")
    if abs(dh) <= ABS_TOL or abs(ds) <= ABS_TOL:
        raise ThermoInputError("T_eff requires non-zero Delta h and Delta s.")
    return positive_temperature(abs(dh) / abs(ds), "Effective temperature")


def phase_change_temperature(delta_h: float, delta_s: float) -> float:
    """Return Delta h/Delta s for an appropriately defined reversible isothermal phase change."""
    dh, ds = number(delta_h, "Phase-change Delta h"), number(delta_s, "Phase-change Delta s")
    if abs(ds) <= ABS_TOL:
        raise ThermoInputError("Phase-change Delta s must be non-zero.")
    return positive_temperature(dh / ds, "Phase-change temperature")


def solve_temperature_bisection(
    target_delta_h: float,
    reference_temperature: float,
    lower_temperature: float,
    upper_temperature: float,
    cp_function: Callable[[float], float],
    tolerance: float = 1.0e-7,
    max_iterations: int = 150,
) -> float:
    """Solve integral(Tref to T) Cp(T)dT = target_delta_h with bracketing."""
    target = number(target_delta_h, "Target Delta h")
    reference = positive_temperature(reference_temperature, "Reference temperature")
    low = positive_temperature(lower_temperature, "Lower temperature bound")
    high = positive_temperature(upper_temperature, "Upper temperature bound")
    if high <= low:
        raise ThermoInputError("Upper temperature bound must exceed lower bound.")

    def residual(T: float) -> float:
        dh, _ = properties_numerical(reference, T, cp_function)
        return dh - target

    f_low, f_high = residual(low), residual(high)
    if abs(f_low) <= tolerance:
        return low
    if abs(f_high) <= tolerance:
        return high
    if f_low * f_high > 0:
        raise ThermoInputError("Bisection interval does not bracket a root.")

    for _ in range(max_iterations):
        mid = 0.5 * (low + high)
        f_mid = residual(mid)
        if abs(f_mid) <= tolerance or high - low <= tolerance:
            return mid
        if f_low * f_mid <= 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    raise ThermoInputError("Bisection did not converge within the iteration limit.")


def stream_properties(stream: Dict[str, Any]) -> Dict[str, float]:
    """Compute signed state-change properties for one constant/linear-Cp stream."""
    if not isinstance(stream, dict):
        raise ThermoInputError("Each stream must be a JSON object/dictionary.")
    check_required(stream, ["name", "mass_flow_kg_s", "T_in_K", "T_out_K", "cp_model"], "stream")
    name = str(stream["name"])
    mass_flow = number(stream["mass_flow_kg_s"], f"{name} mass flow")
    if mass_flow <= 0:
        raise ThermoInputError(f"{name} mass flow must be positive.")
    t_in = positive_temperature(stream["T_in_K"], f"{name} inlet temperature")
    t_out = positive_temperature(stream["T_out_K"], f"{name} outlet temperature")
    cp_model = str(stream["cp_model"]).lower()

    if cp_model == "constant":
        check_required(stream, ["cp_kj_kg_k"], f"{name} constant-Cp model")
        dh, ds = properties_constant_cp(t_in, t_out, stream["cp_kj_kg_k"])
    elif cp_model == "linear":
        check_required(stream, ["a", "b"], f"{name} linear-Cp model")
        dh, ds = properties_linear_cp(t_in, t_out, stream["a"], stream["b"])
    else:
        raise ThermoInputError(f"{name}: cp_model must be 'constant' or 'linear'.")

    return {
        "mass_flow_kg_s": mass_flow,
        "T_in_K": t_in,
        "T_out_K": t_out,
        "delta_h_kj_kg": dh,
        "delta_s_kj_kg_k": ds,
        "delta_H_dot_kw": mass_flow * dh,
        "delta_S_dot_kw_k": mass_flow * ds,
    }


# ============================================================================
# 3. Performance and balance calculations
# ============================================================================

def carnot_efficiency(T_hot: float, T_cold: float) -> float:
    """Carnot efficiency for a cyclic engine between two fixed reservoirs."""
    th = positive_temperature(T_hot, "Hot reservoir temperature")
    tc = positive_temperature(T_cold, "Cold reservoir temperature")
    if th <= tc:
        raise ThermoInputError("A heat engine needs T_hot > T_cold for positive work output.")
    return 1.0 - tc / th


def actual_efficiency(useful_output: float, defined_input: float) -> float:
    output = number(useful_output, "Useful output")
    input_energy = positive(defined_input, "Defined primary energy input")
    if output < 0:
        raise ThermoInputError("Useful work output cannot be negative in this engine model.")
    return output / input_energy


def fixed_reservoir_entropy_generation(Q_hot: float, T_hot: float,
                                       Q_cold_rejected: float, T_cold: float) -> float:
    """Cyclic engine: S_gen_dot = Q_C/T_C - Q_H/T_H; heat magnitudes are positive."""
    qh = number(Q_hot, "Hot-side heat input")
    qc = number(Q_cold_rejected, "Cold-side rejected heat")
    th = positive_temperature(T_hot, "Hot reservoir temperature")
    tc = positive_temperature(T_cold, "Cold reservoir temperature")
    if qh < 0 or qc < 0:
        raise ThermoInputError("Heat magnitudes must be non-negative.")
    return qc / tc - qh / th


def steady_cv_entropy_generation(
    inlets: Sequence[Dict[str, float]],
    outlets: Sequence[Dict[str, float]],
    heat: Sequence[Dict[str, float]],
) -> float:
    """Steady CV S_gen_dot = sum_out(m*s)-sum_in(m*s)-sum(Q_into/T_boundary)."""
    def stream_term(stream: Dict[str, float], label: str) -> float:
        check_required(stream, ["mass_flow_kg_s", "specific_entropy_kj_kg_k"], label)
        mdot = number(stream["mass_flow_kg_s"], f"{label} mass flow")
        s = number(stream["specific_entropy_kj_kg_k"], f"{label} specific entropy")
        if mdot < 0:
            raise ThermoInputError(f"{label} mass flow cannot be negative.")
        return mdot * s

    sin = sum(stream_term(item, "Inlet stream") for item in inlets)
    sout = sum(stream_term(item, "Outlet stream") for item in outlets)
    q_over_t = 0.0
    for item in heat:
        check_required(item, ["heat_into_cv_kw", "boundary_temperature_K"], "CV heat interaction")
        q = number(item["heat_into_cv_kw"], "Heat into CV")
        tb = positive_temperature(item["boundary_temperature_K"], "Heat boundary temperature")
        q_over_t += q / tb
    return sout - sin - q_over_t


def steady_cv_mass_balance(
    inlets: Sequence[Dict[str, float]], outlets: Sequence[Dict[str, float]]
) -> BalanceCheck:
    """Steady total-mass balance: sum(mdot_in) - sum(mdot_out) = 0."""
    def flow(stream: Dict[str, float], label: str) -> float:
        check_required(stream, ["mass_flow_kg_s"], label)
        mdot = number(stream["mass_flow_kg_s"], f"{label} mass flow")
        if mdot < 0:
            raise ThermoInputError(f"{label} mass flow cannot be negative.")
        return mdot
    mass_in = sum(flow(item, "Inlet stream") for item in inlets)
    mass_out = sum(flow(item, "Outlet stream") for item in outlets)
    residual = mass_in - mass_out
    scale = max(abs(mass_in), abs(mass_out), 1.0)
    return BalanceCheck(residual, is_close_to_zero(residual, scale),
                        "sum(mdot_in) - sum(mdot_out) = 0", "kg/s")


def steady_cv_energy_balance(
    inlets: Sequence[Dict[str, float]],
    outlets: Sequence[Dict[str, float]],
    heat: Sequence[Dict[str, float]],
    work_out_kw: float,
    include_kinetic_potential: bool = False,
) -> BalanceCheck:
    """Steady CV energy residual: Q_in - W_out + E_dot_in - E_dot_out."""
    def flow_energy(stream: Dict[str, float], label: str) -> float:
        check_required(stream, ["mass_flow_kg_s", "specific_enthalpy_kj_kg"], label)
        mdot = number(stream["mass_flow_kg_s"], f"{label} mass flow")
        h = number(stream["specific_enthalpy_kj_kg"], f"{label} specific enthalpy")
        if mdot < 0:
            raise ThermoInputError(f"{label} mass flow cannot be negative.")
        specific = h
        if include_kinetic_potential:
            velocity = number(stream.get("velocity_m_s", 0.0), f"{label} velocity")
            elevation = number(stream.get("elevation_m", 0.0), f"{label} elevation")
            gravity = number(stream.get("g_m_s2", 9.80665), f"{label} gravity")
            specific += velocity**2 / 2000.0 + gravity * elevation / 1000.0
        return mdot * specific

    e_in = sum(flow_energy(item, "Inlet stream") for item in inlets)
    e_out = sum(flow_energy(item, "Outlet stream") for item in outlets)
    q_in = 0.0
    for item in heat:
        check_required(item, ["heat_into_cv_kw", "boundary_temperature_K"], "CV heat interaction")
        q_in += number(item["heat_into_cv_kw"], "Heat into CV")
    work = number(work_out_kw, "Work output")
    residual = q_in - work + e_in - e_out
    scale = max(abs(q_in), abs(work), abs(e_in), abs(e_out), 1.0)
    return BalanceCheck(residual, is_close_to_zero(residual, scale),
                        "Qdot_in - Wdot_out + sum(mdot*e_in) - sum(mdot*e_out) = 0",
                        "kW")


def closed_system_energy_balance(
    delta_energy_kj: float, heat: Sequence[Dict[str, float]], work_out_kj: float
) -> BalanceCheck:
    """Closed-system First Law: Delta E = Q_into - W_out."""
    q_total = 0.0
    for item in heat:
        check_required(item, ["heat_into_system_kj", "boundary_temperature_K"], "closed-system heat interaction")
        q_total += number(item["heat_into_system_kj"], "Heat into system")
        positive_temperature(item["boundary_temperature_K"], "Heat boundary temperature")
    delta_e = number(delta_energy_kj, "Delta E")
    work = number(work_out_kj, "Work out")
    residual = q_total - work - delta_e
    scale = max(abs(q_total), abs(work), abs(delta_e), 1.0)
    return BalanceCheck(residual, is_close_to_zero(residual, scale),
                        "Q_into - W_out - Delta E = 0", "kJ")


def closed_system_entropy_generation(
    delta_entropy_system_kj_k: float, heat: Sequence[Dict[str, float]]
) -> float:
    """Closed-system S_gen = Delta S_system - sum(Q_into/T_boundary)."""
    delta_s = number(delta_entropy_system_kj_k, "System Delta S")
    transfer = 0.0
    for item in heat:
        check_required(item, ["heat_into_system_kj", "boundary_temperature_K"], "closed-system heat interaction")
        q = number(item["heat_into_system_kj"], "Heat into system")
        tb = positive_temperature(item["boundary_temperature_K"], "Heat boundary temperature")
        transfer += q / tb
    return delta_s - transfer


# ============================================================================
# 4. Model adapters — one common input/output structure
# ============================================================================

def analyse_fixed_reservoir_engine(case: Dict[str, Any]) -> CaseResult:
    check_required(case, ["T_hot_K", "T_cold_K", "Q_hot_kw", "W_out_kw"], "fixed-reservoir engine")
    th = positive_temperature(case["T_hot_K"], "Hot reservoir temperature")
    tc = positive_temperature(case["T_cold_K"], "Cold reservoir temperature")
    qh = positive(case["Q_hot_kw"], "Heat input")
    work = number(case["W_out_kw"], "Work output")
    if work < 0:
        raise ThermoInputError("Work output cannot be negative for the heat-engine model.")

    qc_given = case.get("Q_cold_rejected_kw")
    qc_from_first_law = qh - work
    qc = None if qc_given is None else number(qc_given, "Rejected heat")
    if qc is not None and qc < 0:
        raise ThermoInputError("Rejected heat cannot be negative for this engine model.")

    energy_scale = max(qh, work, qc or 0.0, 1.0)
    if qc is None and qc_from_first_law < 0 and not is_close_to_zero(qc_from_first_law, energy_scale):
        energy = BalanceCheck(qc_from_first_law, False, "Qdot_H - Wdot_out >= 0 for Qdot_C >= 0", "kW")
        energy_note = "Claimed work exceeds all supplied heat. No nonnegative rejected heat can close the balance."
        sgen = None
    else:
        if qc is None:
            qc = max(0.0, qc_from_first_law)
            energy_note = "Rejected heat was inferred from the First Law: Q_C = Q_H - W_out."
        else:
            energy_note = "Rejected heat was supplied and independently checked against the First Law."
        energy_residual = qc_from_first_law - qc
        energy = BalanceCheck(energy_residual, is_close_to_zero(energy_residual, energy_scale),
                              "Qdot_H - Wdot_out - Qdot_C = 0", "kW")
        sgen = fixed_reservoir_entropy_generation(qh, th, qc, tc)
    eta_actual = actual_efficiency(work, qh)
    eta_carnot = carnot_efficiency(th, tc)
    work_limit = qh * eta_carnot

    verdict = make_verdict(energy, sgen, work, work_limit, True)
    second_law = "NOT EVALUATED"
    if sgen is not None:
        second_law = "FAIL" if entropy_generation_is_negative(sgen) else "PASS"

    return CaseResult(
        title=case.get("title", "Fixed-reservoir cyclic heat engine"),
        model="fixed_reservoir_engine",
        description=case.get("description", ""),
        inputs={"T_hot_K": th, "T_cold_K": tc, "Q_hot_kw": qh,
                "W_out_kw": work, "Q_cold_rejected_kw": qc},
        calculations={
            "Q_cold_rejected_kw": qc,
            "actual_efficiency_fraction": eta_actual,
            "actual_efficiency_percent": 100.0 * eta_actual,
            "carnot_efficiency_fraction": eta_carnot,
            "carnot_efficiency_percent": 100.0 * eta_carnot,
            "efficiency_margin_below_carnot_fraction": eta_carnot - eta_actual,
            "reversible_work_limit_kw": work_limit,
            "S_gen_dot_kw_per_k": sgen,
        },
        checks={"first_law": asdict(energy), "energy_input_note": energy_note,
                "second_law": second_law,
                "performance_limit": "PASS" if work <= work_limit + ABS_TOL + REL_TOL * max(work_limit, 1.0) else "FAIL",
                "process_classification": process_classification(
                    sgen, energy,
                    performance_limit_passed=(work <= work_limit + ABS_TOL + REL_TOL * max(work_limit, 1.0))
                )},
        verdict=verdict,
        assumptions=[
            "Cyclic device; working-fluid state returns to its initial state over each cycle.",
            "Only two heat reservoirs are included in the model.",
            "Q_H and Q_C are positive heat-rate magnitudes; W_out is positive work rate.",
            "Kinetic and potential energy changes are neglected.",
        ],
    )


def analyse_finite_stream_engine(case: Dict[str, Any]) -> CaseResult:
    check_required(case, ["hot_stream", "cold_stream"], "finite-stream thermal engine")
    hot = stream_properties(case["hot_stream"])
    cold = stream_properties(case["cold_stream"])

    if hot["delta_h_kj_kg"] >= 0:
        raise ThermoInputError("The designated hot/source stream must cool: its outlet enthalpy must be lower than its inlet enthalpy.")
    if cold["delta_h_kj_kg"] <= 0:
        raise ThermoInputError("The designated cold/sink stream must warm: its outlet enthalpy must be higher than its inlet enthalpy.")

    q_hot = -hot["delta_H_dot_kw"]
    q_cold = cold["delta_H_dot_kw"]
    work_from_balance = q_hot - q_cold
    if q_hot <= 0:
        raise ThermoInputError("The hot source must release a positive heat rate.")
    if work_from_balance < -ABS_TOL:
        raise ThermoInputError("The specified stream changes require net work input, not work production.")
    if abs(work_from_balance) <= ABS_TOL:
        work_from_balance = 0.0

    supplied_work = case.get("W_out_kw")
    work_used = work_from_balance if supplied_work is None else number(supplied_work, "Claimed work output")
    if work_used < 0:
        raise ThermoInputError("Claimed work output cannot be negative in this engine model.")
    energy_residual = q_hot - work_used - q_cold
    energy = BalanceCheck(energy_residual,
                          is_close_to_zero(energy_residual, max(q_hot, work_used, q_cold, 1.0)),
                          "Qdot_hot released - Wdot_out - Qdot_cold absorbed = 0 (adiabatic overall boundary)",
                          "kW")

    # Entropy generation for the complete, steady, adiabatic boundary around
    # both streams and the device. No external heat interaction is included.
    sgen = hot["delta_S_dot_kw_k"] + cold["delta_S_dot_kw_k"]

    th_eff = effective_temperature(hot["delta_H_dot_kw"], hot["delta_S_dot_kw_k"])
    tc_eff = effective_temperature(cold["delta_H_dot_kw"], cold["delta_S_dot_kw_k"])
    eta_actual = actual_efficiency(work_used, q_hot)

    # Finite-stream effective temperatures provide a model-specific reference.
    # It is not applied as a universal Carnot theorem without user acceptance.
    use_limit = bool(case.get("apply_effective_temperature_limit", False))
    eta_reference: Optional[float] = None
    work_limit: Optional[float] = None
    limit_note: str
    if th_eff > tc_eff:
        eta_reference = 1.0 - tc_eff / th_eff
        work_limit = q_hot * eta_reference
        limit_note = (
            "Calculated as an effective-temperature reversible reference. "
            "It is a model assumption for this thermal mapping, not a universal "
            "Carnot limit for all finite-stream processes."
        )
    else:
        limit_note = "No positive work-producing effective-temperature ordering: T_hot,eff must exceed T_cold,eff."
        if use_limit:
            raise ThermoInputError(limit_note)

    if use_limit and work_limit is not None and supplied_work is not None:
        verdict = make_verdict(energy, sgen, work_used, work_limit, True)
    else:
        extra = []
        if supplied_work is None:
            extra.append("No independent work-output claim was supplied; the displayed work is inferred from stream enthalpy changes.")
        extra.append("The effective-temperature reference was calculated but not used as a universal limit.")
        if supplied_work is None:
            verdict = make_verdict(energy, sgen, None, None, False, extra)
        else:
            verdict = make_verdict(energy, sgen, work_used, None, False, extra)

    return CaseResult(
        title=case.get("title", "Finite hot-stream / cold-stream thermal device"),
        model="finite_stream_engine",
        description=case.get("description", ""),
        inputs={"hot_stream": dict(case["hot_stream"]),
                "cold_stream": dict(case["cold_stream"]),
                "claimed_W_out_kw": supplied_work,
                "apply_effective_temperature_limit": use_limit},
        calculations={
            "hot_stream_property_results": hot,
            "cold_stream_property_results": cold,
            "heat_released_by_hot_stream_kw": q_hot,
            "heat_absorbed_by_cold_stream_kw": q_cold,
            "work_from_stream_energy_balance_kw": work_from_balance,
            "work_used_for_assessment_kw": work_used,
            "actual_efficiency_relative_to_hot_stream_heat_fraction": eta_actual,
            "actual_efficiency_relative_to_hot_stream_heat_percent": 100.0 * eta_actual,
            "hot_effective_temperature_K": th_eff,
            "cold_effective_temperature_K": tc_eff,
            "effective_temperature_efficiency_reference": eta_reference,
            "effective_temperature_work_reference_kw": work_limit,
            "S_gen_dot_kw_per_k": sgen,
        },
        checks={"first_law": asdict(energy),
                "second_law": "PASS" if not entropy_generation_is_negative(sgen) else "FAIL",
                "process_classification": process_classification(
                    sgen, energy,
                    performance_limit_passed=(None if not use_limit or work_limit is None else
                        work_used <= work_limit + ABS_TOL + REL_TOL * max(work_limit, 1.0))
                ),
                "effective_temperature_limit_comparison": (
                    "NOT USED" if not use_limit or work_limit is None else
                    ("PASS" if work_used <= work_limit + ABS_TOL + REL_TOL * max(work_limit, 1.0) else "FAIL")
                ),
                "effective_temperature_limit_note": limit_note,
                "energy_balance_note": ("Work output was inferred from the two stream enthalpy changes."
                                        if supplied_work is None else
                                        "Claimed work was checked against the stream energy balance.")},
        verdict=verdict,
        assumptions=[
            "Steady operation; both streams have the same inlet and outlet mass flow rates.",
            "The complete boundary encloses the device and both streams.",
            "The complete boundary is adiabatic to the surroundings; no external heat interaction is specified.",
            "Only sensible enthalpy changes represented by the selected Cp models are included.",
            "Kinetic and potential energy changes are neglected.",
            "T_eff=|Delta Hdot|/|Delta Sdot| is an equivalent stream descriptor.",
            ("The effective-temperature efficiency reference is used as a model-specific reversible limit because the input explicitly enabled it."
             if use_limit else "The effective-temperature ratio is not used as a universal performance limit."),
        ],
    )


def analyse_steady_control_volume(case: Dict[str, Any]) -> CaseResult:
    check_required(case, ["inlets", "outlets", "heat", "W_out_kw"], "steady control volume")
    inlets = case["inlets"]
    outlets = case["outlets"]
    heat = case["heat"]
    if not isinstance(inlets, list) or not isinstance(outlets, list) or not isinstance(heat, list):
        raise ThermoInputError("inlets, outlets and heat must each be lists in the JSON input.")
    if not all(isinstance(item, dict) for item in inlets + outlets + heat):
        raise ThermoInputError("Every inlet, outlet and heat interaction must be a JSON object.")
    if not inlets and not outlets:
        raise ThermoInputError("At least one mass inlet or outlet is required for a control-volume model.")

    if not all(isinstance(item, dict) for item in inlets + outlets + heat):
        raise ThermoInputError("Every inlet, outlet and heat interaction must be a JSON object.")
    work = number(case["W_out_kw"], "Work output")
    include_kepe = bool(case.get("include_kinetic_potential", False))
    mass = steady_cv_mass_balance(inlets, outlets)
    energy = steady_cv_energy_balance(inlets, outlets, heat, work, include_kepe)
    sgen = steady_cv_entropy_generation(inlets, outlets, heat)
    verdict = make_verdict(energy, sgen, model_limit_valid=False, mass_balance=mass)

    return CaseResult(
        title=case.get("title", "Steady control-volume balance"),
        model="steady_control_volume",
        description=case.get("description", ""),
        inputs={"inlets": inlets, "outlets": outlets, "heat": heat,
                "W_out_kw": work, "include_kinetic_potential": include_kepe},
        calculations={"S_gen_dot_kw_per_k": sgen},
        checks={"mass_balance": asdict(mass),
                "first_law": asdict(energy),
                "second_law": "PASS" if not entropy_generation_is_negative(sgen) else "FAIL",
                "process_classification": process_classification(sgen, energy, mass),
                "performance_limit": "Not calculated: a complete reversible/exergy limit has not been supplied."},
        verdict=verdict,
        assumptions=[
            "Steady state: accumulation of energy and entropy within the control volume is zero.",
            "All relevant mass streams and heat interactions crossing the selected boundary must be listed.",
            "Heat is positive into the control volume; shaft work is positive out.",
            "Kinetic/potential energy terms are included only when include_kinetic_potential is true.",
            "Passing balance checks does not by itself prove a useful-work claim is below its reversible limit.",
        ],
    )


def analyse_closed_system(case: Dict[str, Any]) -> CaseResult:
    check_required(case, ["delta_E_kj", "delta_S_system_kj_K", "heat", "W_out_kj"], "closed system")
    heat = case["heat"]
    if not isinstance(heat, list) or not all(isinstance(item, dict) for item in heat):
        raise ThermoInputError("heat must be a list of JSON objects in the input.")
    energy = closed_system_energy_balance(case["delta_E_kj"], heat, case["W_out_kj"])
    sgen = closed_system_entropy_generation(case["delta_S_system_kj_K"], heat)
    verdict = make_verdict(energy, sgen, model_limit_valid=False)

    return CaseResult(
        title=case.get("title", "Closed-system energy and entropy balance"),
        model="closed_system",
        description=case.get("description", ""),
        inputs={"delta_E_kj": number(case["delta_E_kj"], "Delta E"),
                "delta_S_system_kj_K": number(case["delta_S_system_kj_K"], "System Delta S"),
                "heat": heat, "W_out_kj": number(case["W_out_kj"], "Work out")},
        calculations={"S_gen_kj_per_k": sgen},
        checks={"first_law": asdict(energy),
                "second_law": "PASS" if not entropy_generation_is_negative(sgen) else "FAIL",
                "process_classification": process_classification(sgen, energy),
                "performance_limit": "Not calculated: no reversible useful-work limit was supplied."},
        verdict=verdict,
        assumptions=[
            "Closed system: no mass crosses the selected boundary.",
            "Delta E includes the energy changes retained in the supplied model (e.g. internal, kinetic and potential).",
            "Heat is positive into the system; work is positive out.",
            "Each heat interaction is represented at a constant boundary temperature.",
        ],
    )


def analyse_property_change(case: Dict[str, Any]) -> CaseResult:
    check_required(case, ["T1_K", "T2_K", "cp_model"], "property calculation")
    model = str(case["cp_model"]).lower()
    if model == "constant":
        check_required(case, ["cp_kj_kg_k"], "constant-Cp property calculation")
        dh, ds = properties_constant_cp(case["T1_K"], case["T2_K"], case["cp_kj_kg_k"])
    elif model == "linear":
        check_required(case, ["a", "b"], "linear-Cp property calculation")
        dh, ds = properties_linear_cp(case["T1_K"], case["T2_K"], case["a"], case["b"])
    else:
        raise ThermoInputError("Property cp_model must be 'constant' or 'linear'.")
    teff = None
    teff_note = "Not defined for zero Delta h or zero Delta s."
    try:
        teff = effective_temperature(dh, ds)
        teff_note = "Equivalent temperature descriptor only; not by itself a reversible work limit."
    except ThermoInputError:
        pass

    phase_temp = None
    if "phase_delta_h_kj_kg" in case or "phase_delta_s_kj_kg_k" in case:
        check_required(case, ["phase_delta_h_kj_kg", "phase_delta_s_kj_kg_k"], "phase-change property calculation")
        phase_temp = phase_change_temperature(case["phase_delta_h_kj_kg"], case["phase_delta_s_kj_kg_k"])

    return CaseResult(
        title=case.get("title", "Thermal property-change calculation"),
        model="property_change",
        description=case.get("description", ""),
        inputs={key: value for key, value in case.items() if key not in {"model", "title", "description"}},
        calculations={"delta_h_kj_kg": dh, "delta_s_kj_kg_k": ds,
                      "effective_temperature_K": teff,
                      "effective_temperature_note": teff_note,
                      "phase_change_temperature_K": phase_temp},
        checks={"property_model": "PASS"},
        verdict=Verdict("PROPERTY CALCULATION ONLY",
                        ["This calculates state-property changes; it does not assess a complete device or establish S_gen."]),
        assumptions=["The selected Cp relation represents the material over the entire stated temperature interval."],
    )


def resource_result(
    case: Dict[str, Any],
    inputs: Dict[str, Any],
    calculations: Dict[str, Any],
    assumptions: List[str],
    missing: Sequence[str] = (),
    rejection: Optional[str] = None,
) -> CaseResult:
    """Report a resource bound without inferring full balance or entropy data."""
    if missing:
        verdict = Verdict("INSUFFICIENT DATA / MODEL REQUIRED", [
            f"Provide {', '.join(missing)} to evaluate this claim."
        ])
        comparison = "NOT EVALUATED"
    elif rejection:
        verdict = Verdict("NOT FEASIBLE", [rejection])
        comparison = "FAIL"
    else:
        verdict = make_verdict(
            work_out=calculations["claimed_electrical_output_kw"],
            work_limit=calculations["reversible_power_limit_kw"],
            model_limit_valid=True,
            work_limit_tolerance=1e-9 * calculations["reversible_power_limit_kw"],
        )
        comparison = "PASS" if verdict.status == "FEASIBLE / NOT REJECTED" else "FAIL"
    return CaseResult(
        title=case.get("title", case["model"].replace("_", " ").capitalize()),
        model=case["model"].lower(),
        description=case.get("description", ""),
        inputs=inputs,
        calculations=calculations,
        checks={
            "performance_limit": comparison,
            "first_law_balance": "NOT EVALUATED — complete energy flows unavailable",
            "entropy_balance": "NOT EVALUATED — entropy generation unavailable",
        },
        verdict=verdict,
        assumptions=assumptions,
    )


def resource_number(case: Dict[str, Any], field: str, minimum: Optional[float] = 0.0) -> float:
    if isinstance(case[field], bool):
        raise ThermoInputError(f"{field} must be numeric.")
    value = number(case[field], field)
    if minimum is not None and value < minimum:
        raise ThermoInputError(f"{field} must be at least {minimum:g}.")
    return value


def analyse_mechanical_power(case: Dict[str, Any]) -> CaseResult:
    power_field = "recoverable_mechanical_power_kw"
    event_fields = ("recoverable_energy_per_event_j", "events_per_s")
    direct = case.get(power_field) is not None
    events = any(case.get(field) is not None for field in event_fields)
    if direct and events:
        raise ThermoInputError("Supply mechanical power or event energy and rate, using one input basis.")
    required = ("W_out_kw", *event_fields) if events else ("W_out_kw", power_field)
    assumptions = [
        "The supplied resource is recoverable mechanical work at the converter input.",
        "Average input and output use the same time interval. Ideal conversion is capped at 100%.",
    ]
    inputs = {field: case[field] for field in required if case.get(field) is not None}
    missing = [field for field in required if field not in inputs]
    if not direct and not events:
        missing[-1] = f"{power_field} (or both {event_fields[0]} and {event_fields[1]})"
    if missing:
        return resource_result(case, inputs, {}, assumptions, missing)

    inputs = {field: resource_number(case, field) for field in required}
    if events:
        power_kw = number(
            inputs[event_fields[0]] * (inputs[event_fields[1]] / 1000),
            "Recoverable mechanical power (kW)",
        )
    else:
        power_kw = inputs[power_field]
    result = resource_result(case, inputs, {
        "claimed_electrical_output_kw": inputs["W_out_kw"],
        "reversible_power_limit_kw": power_kw,
    }, assumptions)
    remainder = power_kw - inputs["W_out_kw"]
    tolerance = 1e-9 * power_kw
    result.calculations["power_remaining_after_electrical_output_kw"] = remainder
    result.checks["input_energy_limit"] = "PASS" if remainder >= -tolerance else "FAIL"
    result.checks["first_law_balance"] = (
        "Energy limit satisfied. Remaining power must leave as heat or other output."
        if remainder >= -tolerance else "FAIL — electrical output exceeds mechanical input."
    )
    result.checks["entropy_balance"] = "Add a heat-rejection temperature to calculate entropy generation."

    heat = None
    energy = None
    if case.get("heat_rejected_kw") is not None:
        heat = resource_number(case, "heat_rejected_kw")
        result.inputs["heat_rejected_kw"] = heat
        residual = remainder - heat
        energy = BalanceCheck(residual, abs(residual) <= 1e-9 * max(power_kw, heat),
                              "Mechanical input - electrical output - rejected heat = 0", "kW")
        result.calculations["first_law_residual_kw"] = residual
        result.checks["first_law_balance"] = "PASS" if energy.passed else "FAIL"
    elif remainder >= -tolerance:
        heat = max(0.0, remainder)
        result.checks["heat_rejection_basis"] = "Inferred from the energy balance."
    if heat is not None:
        result.calculations["heat_rejected_kw"] = heat

    sgen = None
    if case.get("heat_rejection_temperature_K") is not None:
        temperature = positive_temperature(resource_number(case, "heat_rejection_temperature_K"),
                                           "Heat rejection temperature")
        result.inputs["heat_rejection_temperature_K"] = temperature
        if heat is not None and remainder >= -tolerance and (energy is None or energy.passed):
            sgen = heat / temperature
            result.calculations["S_gen_dot_kw_per_k"] = sgen
            result.checks["entropy_balance"] = "PASS"
            result.checks["process_classification"] = process_classification(sgen, energy)
            result.assumptions.append(
                "Steady converter with no entropy accumulation or material flow. "
                "All remaining input leaves as heat at the single supplied boundary temperature."
            )
        else:
            result.checks["entropy_balance"] = "Resolve the energy-balance failure before evaluating entropy."
    result.verdict = make_verdict(
        first_law=energy, sgen=sgen, work_out=inputs["W_out_kw"], work_limit=power_kw,
        model_limit_valid=True, work_limit_tolerance=tolerance,
    )
    return result


def analyse_solar_blackbody(case: Dict[str, Any]) -> CaseResult:
    fields = ("T_source_K", "T_ambient_K", "irradiance_W_m2", "collection_area_m2", "W_out_kw")
    assumptions = [
        "Ideal undiluted blackbody radiation with a blackbody reference environment.",
        "Irradiance and effective collection area describe the same incident beam at the aperture.",
        "The bound describes radiative exergy and applies under the ideal radiation model.",
    ]
    inputs = {field: case[field] for field in fields if case.get(field) is not None}
    missing = [field for field in fields if field not in inputs]
    if missing:
        return resource_result(case, inputs, {}, assumptions, missing)

    inputs = {field: resource_number(case, field) for field in fields}
    source_K = positive_temperature(inputs["T_source_K"], "Radiation source temperature")
    ambient_K = positive_temperature(inputs["T_ambient_K"], "Ambient temperature")
    if source_K < ambient_K:
        raise ThermoInputError("This solar model requires a source at least as warm as the environment.")
    area_m2 = positive(inputs["collection_area_m2"], "Collection area")
    incident_kw = number((inputs["irradiance_W_m2"] / 1000) * area_m2, "Incident power (kW)")
    ratio = ambient_K / source_K
    # Factored form of 1 - (4/3)r + (1/3)r**4 avoids cancellation near r=1.
    exergy_fraction = (1 - ratio)**2 * (ratio**2 + 2 * ratio + 3) / 3
    return resource_result(case, inputs, {
        "incident_radiation_kw": incident_kw,
        "petela_landsberg_exergy_fraction": exergy_fraction,
        "claimed_electrical_output_kw": inputs["W_out_kw"],
        "reversible_power_limit_kw": incident_kw * exergy_fraction,
    }, assumptions)


def analyse_reaction_gibbs(case: Dict[str, Any]) -> CaseResult:
    fields = ("reaction_direction", "delta_G_kj_per_mol_rxn", "reaction_rate_mol_rxn_s", "W_out_kw")
    assumptions = [
        "Reaction Gibbs energy applies to the stated direction at the operating temperature, pressure and composition.",
        "Both molar quantities use moles of reaction extent for the same stoichiometry.",
        "The reaction is the sole work source. Reversible non-expansion work per mole is minus Delta G.",
    ]
    inputs = {field: case[field] for field in fields if case.get(field) is not None}
    missing = [field for field in fields if field not in inputs]
    if missing:
        return resource_result(case, inputs, {}, assumptions, missing)

    direction = inputs["reaction_direction"]
    if not isinstance(direction, str) or not direction.strip():
        raise ThermoInputError("reaction_direction must describe the direction used for Delta G.")
    inputs["reaction_direction"] = direction.strip()
    delta_g = inputs["delta_G_kj_per_mol_rxn"] = resource_number(case, fields[1], minimum=None)
    rate = inputs["reaction_rate_mol_rxn_s"] = positive(resource_number(case, fields[2]), "Reaction rate")
    claimed_kw = inputs["W_out_kw"] = resource_number(case, "W_out_kw")
    signed_limit_kw = number(-delta_g * rate, "Signed reversible work rate (kW)")
    rejection = None
    if delta_g > 0:
        rejection = "The specified forward reaction requires external work input at the stated conditions."
    return resource_result(case, inputs, {
        "claimed_electrical_output_kw": claimed_kw,
        "signed_reversible_nonexpansion_work_kw": signed_limit_kw,
        "minimum_external_work_input_kw": max(0.0, -signed_limit_kw),
        "reversible_power_limit_kw": max(0.0, signed_limit_kw),
    }, assumptions, rejection=rejection)


def analyse_unsupported_domain(case: Dict[str, Any]) -> CaseResult:
    domain = str(case.get("domain", "nonthermal/unspecified"))
    explanation = case.get("reason", "A domain-specific reversible model and complete required data have not been provided.")
    return CaseResult(
        title=case.get("title", "Unsupported or incomplete thermodynamic model"),
        model="unsupported_domain",
        description=case.get("description", ""),
        inputs={"domain": domain},
        calculations={},
        checks={"model_support": "NO APPLICABLE MODEL SELECTED"},
        verdict=Verdict("INSUFFICIENT DATA / MODEL REQUIRED", [str(explanation)]),
        assumptions=[
            "No Carnot temperatures are invented for a nonthermal process.",
            "The assessment requires a supported route and its physical input data.",
        ],
    )


def analyse_case(case: Dict[str, Any]) -> CaseResult:
    """Single entry point: validate the model name and dispatch to its adapter."""
    if not isinstance(case, dict):
        raise ThermoInputError("A case must be supplied as a JSON object/dictionary.")
    check_required(case, ["model"], "case")
    model = str(case["model"]).lower()
    dispatch = {
        "fixed_reservoir_engine": analyse_fixed_reservoir_engine,
        "finite_stream_engine": analyse_finite_stream_engine,
        "steady_control_volume": analyse_steady_control_volume,
        "closed_system": analyse_closed_system,
        "property_change": analyse_property_change,
        "unsupported_domain": analyse_unsupported_domain,
        "mechanical_power": analyse_mechanical_power,
        "solar_blackbody": analyse_solar_blackbody,
        "reaction_gibbs": analyse_reaction_gibbs,
    }
    if model not in dispatch:
        supported = ", ".join(dispatch)
        raise ThermoInputError(f"Unknown model '{model}'. Supported model keys: {supported}.")
    return dispatch[model](case)


def run_case(case: Dict[str, Any]) -> CaseResult:
    """Public orchestration function used by the CLI and external callers."""
    return analyse_case(case)


# ============================================================================
# 5. Standardized examples for validation and demonstration
# ============================================================================

def resource_examples() -> List[Dict[str, Any]]:
    return [
        {
            "model": "mechanical_power", "title": "Walking energy harvester",
            "description": "Illustrative recoverable mechanical energy per step at the converter input.",
            "recoverable_energy_per_event_j": 4.0, "events_per_s": 2.0, "W_out_kw": 0.005,
        },
        {
            "model": "solar_blackbody", "title": "Ideal blackbody radiation example",
            "T_source_K": 5778.0, "T_ambient_K": 300.0, "irradiance_W_m2": 1000.0,
            "collection_area_m2": 2.0, "W_out_kw": 1.0,
        },
        {
            "model": "reaction_gibbs", "title": "Illustrative exergonic cell reaction",
            "reaction_direction": "Reactants to products as specified for Delta G",
            "delta_G_kj_per_mol_rxn": -200.0, "reaction_rate_mol_rxn_s": 0.01, "W_out_kw": 1.0,
        },
    ]


def demonstration_cases() -> List[Dict[str, Any]]:
    """Return validation cases; these are demonstrations, not hidden user inputs."""
    return [
        {
            "title": "Baseline two-reservoir engine",
            "model": "fixed_reservoir_engine",
            "description": "600 K source, 300 K sink, 100 kW heat input and 30 kW work output.",
            "T_hot_K": 600.0, "T_cold_K": 300.0, "Q_hot_kw": 100.0, "W_out_kw": 30.0,
        },
        {
            "title": "Finite hot/cold stream example",
            "model": "finite_stream_engine",
            "description": "One hot stream cools and one cold stream warms; adiabatic complete boundary.",
            "hot_stream": {"name": "Hot source", "mass_flow_kg_s": 1.0,
                           "T_in_K": 600.0, "T_out_K": 400.0,
                           "cp_model": "constant", "cp_kj_kg_k": 4.18},
            "cold_stream": {"name": "Cold sink", "mass_flow_kg_s": 2.0,
                            "T_in_K": 300.0, "T_out_K": 377.75,
                            "cp_model": "constant", "cp_kj_kg_k": 4.18},
            "W_out_kw": 186.01,
            "apply_effective_temperature_limit": False,
        },
        {
            "title": "Finite-stream model-specific limit demonstration",
            "model": "finite_stream_engine",
            "description": "Same stream changes; explicitly enables the effective-temperature reference for comparison.",
            "hot_stream": {"name": "Hot source", "mass_flow_kg_s": 1.0,
                           "T_in_K": 600.0, "T_out_K": 400.0,
                           "cp_model": "constant", "cp_kj_kg_k": 4.18},
            "cold_stream": {"name": "Cold sink", "mass_flow_kg_s": 2.0,
                            "T_in_K": 300.0, "T_out_K": 377.75,
                            "cp_model": "constant", "cp_kj_kg_k": 4.18},
            "W_out_kw": 186.01,
            "apply_effective_temperature_limit": True,
        },
        {
            "title": "Impossible fixed-reservoir claim",
            "model": "fixed_reservoir_engine",
            "description": "60% claimed efficiency where the Carnot limit is 50%.",
            "T_hot_K": 600.0, "T_cold_K": 300.0, "Q_hot_kw": 100.0, "W_out_kw": 60.0,
        },
        {
            "title": "Variable Cp and phase-change property calculation",
            "model": "property_change",
            "description": "Property-only test using Cp(T)=1+0.0005T and a reversible phase-change ratio.",
            "T1_K": 500.0, "T2_K": 350.0, "cp_model": "linear", "a": 1.0, "b": 0.0005,
            "phase_delta_h_kj_kg": 250.0, "phase_delta_s_kj_kg_k": 0.80,
        },
        {
            "title": "Nonthermal case without an exergy model",
            "model": "unsupported_domain",
            "domain": "mechanical",
            "reason": "An input/output ratio alone does not supply a complete available-work or exergy model.",
        },
    ] + resource_examples()


def self_test() -> List[str]:
    """Run deterministic internal checks; raise AssertionError on a failed test."""
    passed: List[str] = []

    # Constant Cp analytical formula and sign checks.
    dh, ds = properties_constant_cp(300.0, 500.0, 4.0)
    assert abs(dh - 800.0) < 1e-10 and ds > 0
    dh_cool, ds_cool = properties_constant_cp(500.0, 300.0, 4.0)
    assert dh_cool < 0 and ds_cool < 0
    passed.append("constant-Cp enthalpy/entropy formulas and sign convention")

    # Constant and linear Cp equivalence when b=0.
    dh_linear, ds_linear = properties_linear_cp(300.0, 500.0, 4.0, 0.0)
    assert abs(dh - dh_linear) < 1e-10 and abs(ds - ds_linear) < 1e-10
    passed.append("linear-Cp formula and constant-Cp special case")

    # Numerical integral agrees with analytical linear-Cp result.
    cp_func = lambda T: 1.0 + 0.0005 * T
    dh_exact, ds_exact = properties_linear_cp(350.0, 500.0, 1.0, 0.0005)
    dh_num, ds_num = properties_numerical(350.0, 500.0, cp_func)
    assert abs(dh_num - dh_exact) < 1e-7 and abs(ds_num - ds_exact) < 1e-7
    passed.append("adaptive Simpson integration vs analytical Cp(T)")

    # Bisection recovers the known endpoint.
    recovered = solve_temperature_bisection(dh_exact, 350.0, 400.0, 550.0, cp_func)
    assert abs(recovered - 500.0) < 1e-5
    passed.append("bracketed bisection temperature solver")

    # Fixed-reservoir reference case.
    baseline = analyse_case({"model": "fixed_reservoir_engine", "T_hot_K": 600,
                             "T_cold_K": 300, "Q_hot_kw": 100, "W_out_kw": 30})
    assert abs(baseline.calculations["Q_cold_rejected_kw"] - 70.0) < 1e-10
    assert abs(baseline.calculations["carnot_efficiency_fraction"] - 0.5) < 1e-10
    assert abs(baseline.calculations["actual_efficiency_fraction"] - 0.3) < 1e-10
    assert abs(baseline.calculations["S_gen_dot_kw_per_k"] - (70/300 - 100/600)) < 1e-10
    assert baseline.verdict.status == "FEASIBLE / NOT REJECTED"
    passed.append("fixed-reservoir First Law, Carnot, entropy and feasible verdict")

    # At the Carnot limit, the idealized engine is reversible.
    reversible = analyse_case({"model": "fixed_reservoir_engine", "T_hot_K": 600,
                               "T_cold_K": 300, "Q_hot_kw": 100, "W_out_kw": 50})
    assert reversible.verdict.status == "FEASIBLE / NOT REJECTED"
    assert process_classification(reversible.calculations["S_gen_dot_kw_per_k"],
                                  performance_limit_passed=True) == "REVERSIBLE (LIMITING CASE)"
    passed.append("reversible fixed-reservoir limiting case")

    # Impossible reservoir claim must fail both Carnot and entropy checks.
    impossible = analyse_case({"model": "fixed_reservoir_engine", "T_hot_K": 600,
                               "T_cold_K": 300, "Q_hot_kw": 100, "W_out_kw": 60})
    assert impossible.verdict.status == "NOT FEASIBLE"
    assert impossible.calculations["S_gen_dot_kw_per_k"] < 0
    passed.append("impossible fixed-reservoir claim rejected")

    # Finite streams: verify property rates and entropy generation.
    finite_case = demonstration_cases()[1]
    finite = analyse_case(finite_case)
    assert abs(finite.calculations["heat_released_by_hot_stream_kw"] - 836.0) < 1e-8
    assert finite.calculations["S_gen_dot_kw_per_k"] > 0
    assert finite.checks["first_law"]["passed"]
    assert finite.verdict.status == "INSUFFICIENT DATA / MODEL REQUIRED"
    passed.append("finite-stream properties, energy consistency and entropy generation")

    # Explicitly selected effective-temperature reference is checked but labelled.
    finite_limit_case = demonstration_cases()[2]
    finite_limit = analyse_case(finite_limit_case)
    assert finite_limit.calculations["effective_temperature_efficiency_reference"] is not None
    assert finite_limit.verdict.status == "FEASIBLE / NOT REJECTED"
    passed.append("opt-in effective-temperature performance reference")

    # Property / phase-change demonstration.
    prop = analyse_case(demonstration_cases()[4])
    assert prop.calculations["delta_h_kj_kg"] < 0
    assert prop.calculations["phase_change_temperature_K"] == 312.5
    passed.append("variable-Cp and phase-change property calculations")

    # General CV entropy balance. Adiabatic flow with entropy increase is positive.
    cv_in = [{"mass_flow_kg_s": 1.0, "specific_entropy_kj_kg_k": 1.0,
              "specific_enthalpy_kj_kg": 100.0}]
    cv_out = [{"mass_flow_kg_s": 1.0, "specific_entropy_kj_kg_k": 1.2,
               "specific_enthalpy_kj_kg": 80.0}]
    cv_sgen = steady_cv_entropy_generation(cv_in, cv_out, [])
    cv_mass = steady_cv_mass_balance(cv_in, cv_out)
    cv_energy = steady_cv_energy_balance(cv_in, cv_out, [], 20.0)
    assert abs(cv_sgen - 0.2) < 1e-12 and cv_mass.passed and cv_energy.passed
    passed.append("steady control-volume mass, energy and entropy balances")

    # Closed system entropy and energy balances.
    closed_energy = closed_system_energy_balance(10.0, [
        {"heat_into_system_kj": 15.0, "boundary_temperature_K": 300.0}], 5.0)
    closed_sgen = closed_system_entropy_generation(0.06, [
        {"heat_into_system_kj": 15.0, "boundary_temperature_K": 300.0}])
    assert closed_energy.passed and abs(closed_sgen - 0.01) < 1e-12
    passed.append("closed-system First Law and entropy balance")

    # A failed energy balance must be rejected.
    bad_energy_case = analyse_case({"model": "fixed_reservoir_engine", "T_hot_K": 600,
                                    "T_cold_K": 300, "Q_hot_kw": 100, "W_out_kw": 30,
                                    "Q_cold_rejected_kw": 60})
    assert bad_energy_case.verdict.status == "NOT FEASIBLE"
    passed.append("inconsistent First Law input correctly rejected")

    # A steady CV must satisfy mass conservation as well as its energy balance.
    bad_cv = analyse_case({
        "model": "steady_control_volume", "inlets": [
            {"mass_flow_kg_s": 1.0, "specific_enthalpy_kj_kg": 100.0,
             "specific_entropy_kj_kg_k": 1.0}],
        "outlets": [{"mass_flow_kg_s": 0.9, "specific_enthalpy_kj_kg": 80.0,
                     "specific_entropy_kj_kg_k": 1.2}],
        "heat": [], "W_out_kw": 28.0
    })
    assert not bad_cv.checks["mass_balance"]["passed"]
    assert bad_cv.verdict.status == "NOT FEASIBLE"
    passed.append("steady control-volume mass conservation check")

    # No independent work claim means no performance verdict, even if a
    # user elects to display the effective-temperature comparison.
    no_claim = dict(demonstration_cases()[2])
    no_claim.pop("W_out_kw")
    no_claim_result = analyse_case(no_claim)
    assert no_claim_result.verdict.status == "INSUFFICIENT DATA / MODEL REQUIRED"
    passed.append("missing independent work claim returns insufficient data")

    # Negative entropy generation must be rejected.
    violation = make_verdict(sgen=-0.01, model_limit_valid=False)
    assert violation.status == "NOT FEASIBLE"
    assert process_classification(-0.01) == "IMPOSSIBLE — SECOND LAW VIOLATION"
    passed.append("negative entropy generation correctly rejected")

    return passed


# ============================================================================
# 6. Input interface: interactive prompts and JSON case files
# ============================================================================

def ask_text(prompt: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value if value else (default if default is not None else "")


def ask_float(prompt: str, default: Optional[float] = None) -> float:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return float(default)
        try:
            return float(raw)
        except ValueError:
            print("Please enter a numeric value.")


def ask_int(prompt: str, default: Optional[int] = None) -> int:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return int(default)
        try:
            return int(raw)
        except ValueError:
            print("Please enter a whole number.")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = input(f"{prompt} ({hint}): ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes", "true", "1"}


def interactive_case() -> Dict[str, Any]:
    print("\nTHERMODYNAMIC FEASIBILITY TESTER — INPUT MODE")
    print("Enter data in SI/thermodynamic units shown. Temperatures must be in K.")
    print("Extract the data from the written problem before selecting a model.")
    print("\nChoose the model:")
    print("  1. Fixed-temperature reservoir cyclic heat engine")
    print("  2. Finite hot stream + finite cold stream")
    print("  3. General steady control volume (energy + entropy balances)")
    print("  4. Closed system (energy + entropy balances)")
    print("  5. Property changes only (Delta h, Delta s, T_eff, optional phase change)")
    print("  6. Unsupported/future domain (returns insufficient model)")
    print("  7. Mechanical-to-electric conversion")
    print("  8. Ideal blackbody radiation")
    print("  9. Signed reaction Gibbs energy")
    choice = ask_text("Model number")
    title = ask_text("Short case title", "User-supplied case")
    description = ask_text("Brief process description", "")

    if choice == "1":
        case: Dict[str, Any] = {
            "model": "fixed_reservoir_engine", "title": title, "description": description,
            "T_hot_K": ask_float("Hot reservoir temperature (K)"),
            "T_cold_K": ask_float("Cold reservoir temperature (K)"),
            "Q_hot_kw": ask_float("Heat supplied from hot reservoir (kW)"),
            "W_out_kw": ask_float("Claimed work output (kW)"),
        }
        if ask_yes_no("Do you have a separately specified rejected-heat rate?", False):
            case["Q_cold_rejected_kw"] = ask_float("Rejected heat rate (kW)")
        return case

    if choice == "2":
        def ask_stream(label: str, default_name: str) -> Dict[str, Any]:
            print(f"\n{label} stream")
            name = ask_text("Stream name", default_name)
            mdot = ask_float("Mass flow rate (kg/s)")
            tin = ask_float("Inlet temperature (K)")
            tout = ask_float("Outlet temperature (K)")
            cp_model = ask_text("Cp model: constant or linear", "constant").lower()
            stream: Dict[str, Any] = {"name": name, "mass_flow_kg_s": mdot,
                                      "T_in_K": tin, "T_out_K": tout,
                                      "cp_model": cp_model}
            if cp_model == "constant":
                stream["cp_kj_kg_k"] = ask_float("Constant Cp (kJ/kg K)")
            elif cp_model == "linear":
                stream["a"] = ask_float("Cp coefficient a")
                stream["b"] = ask_float("Cp coefficient b")
            else:
                print("Unknown Cp model; validation will report the issue.")
            return stream
        hot_stream = ask_stream("Hot/source", "Hot source")
        cold_stream = ask_stream("Cold/sink", "Cold sink")
        case = {"model": "finite_stream_engine", "title": title, "description": description,
                "hot_stream": hot_stream, "cold_stream": cold_stream}
        has_work = ask_yes_no("Do you have a claimed work output to test?", True)
        if has_work:
            case["W_out_kw"] = ask_float("Claimed work output (kW)")
        use_limit = ask_yes_no(
            "Use the effective-temperature ratio as a model-specific reversible reference? (not universal)",
            False,
        )
        case["apply_effective_temperature_limit"] = use_limit
        return case

    if choice == "3":
        print("\nFor each stream, provide mass flow, specific h and specific s.")
        inlets: List[Dict[str, float]] = []
        outlets: List[Dict[str, float]] = []
        for label, target in (("inlet", inlets), ("outlet", outlets)):
            count = ask_int(f"Number of {label} streams", 1)
            if count < 0:
                raise ThermoInputError("The number of streams cannot be negative.")
            for i in range(count):
                print(f"{label.title()} stream {i+1}")
                item = {"mass_flow_kg_s": ask_float("Mass flow (kg/s)"),
                        "specific_enthalpy_kj_kg": ask_float("Specific enthalpy (kJ/kg)"),
                        "specific_entropy_kj_kg_k": ask_float("Specific entropy (kJ/kg K)")}
                if ask_yes_no("Include velocity/elevation for this stream?", False):
                    item["velocity_m_s"] = ask_float("Velocity (m/s)")
                    item["elevation_m"] = ask_float("Elevation (m)")
                target.append(item)
        heat: List[Dict[str, float]] = []
        n_heat = ask_int("Number of heat interactions", 0)
        if n_heat < 0:
            raise ThermoInputError("The number of heat interactions cannot be negative.")
        for i in range(n_heat):
            print(f"Heat interaction {i+1} (positive into control volume)")
            heat.append({"heat_into_cv_kw": ask_float("Heat rate (kW)"),
                         "boundary_temperature_K": ask_float("Boundary temperature (K)")})
        work = ask_float("Shaft work output (kW)")
        include_kepe = ask_yes_no("Include kinetic/potential energy terms?", False)
        return {"model": "steady_control_volume", "title": title, "description": description,
                "inlets": inlets, "outlets": outlets, "heat": heat,
                "W_out_kw": work, "include_kinetic_potential": include_kepe}

    if choice == "4":
        delta_e = ask_float("System total energy change Delta E (kJ)")
        delta_s = ask_float("System entropy change Delta S (kJ/K)")
        n_heat = ask_int("Number of heat interactions", 1)
        if n_heat < 0:
            raise ThermoInputError("The number of heat interactions cannot be negative.")
        heat = []
        for i in range(n_heat):
            print(f"Heat interaction {i+1} (positive into system)")
            heat.append({"heat_into_system_kj": ask_float("Heat transfer (kJ)"),
                         "boundary_temperature_K": ask_float("Boundary temperature (K)")})
        work = ask_float("Work output (kJ)")
        return {"model": "closed_system", "title": title, "description": description,
                "delta_E_kj": delta_e, "delta_S_system_kj_K": delta_s,
                "heat": heat, "W_out_kj": work}

    if choice == "5":
        t1, t2 = ask_float("Initial temperature T1 (K)"), ask_float("Final temperature T2 (K)")
        cp_model = ask_text("Cp model: constant or linear", "constant").lower()
        case = {"model": "property_change", "title": title, "description": description,
                "T1_K": t1, "T2_K": t2, "cp_model": cp_model}
        if cp_model == "constant":
            case["cp_kj_kg_k"] = ask_float("Constant Cp (kJ/kg K)")
        elif cp_model == "linear":
            case["a"] = ask_float("Cp coefficient a")
            case["b"] = ask_float("Cp coefficient b")
        if ask_yes_no("Include phase-change Delta h and Delta s?", False):
            case["phase_delta_h_kj_kg"] = ask_float("Phase-change Delta h (kJ/kg)")
            case["phase_delta_s_kj_kg_k"] = ask_float("Phase-change Delta s (kJ/kg K)")
        return case

    if choice == "6":
        domain = ask_text("Domain (e.g. chemical, radiative, mechanical)", "unspecified")
        reason = ask_text("What required model/data is missing?", "A domain-specific reversible/exergy model has not been supplied.")
        return {"model": "unsupported_domain", "title": title, "description": description,
                "domain": domain, "reason": reason}

    if choice == "7":
        if ask_yes_no("Is recoverable mechanical power already known?", True):
            resource = {"recoverable_mechanical_power_kw": ask_float("Recoverable mechanical power (kW)")}
        else:
            resource = {
                "recoverable_energy_per_event_j": ask_float("Recoverable energy per event (J)"),
                "events_per_s": ask_float("Events per second"),
            }
        return {"model": "mechanical_power", "title": title, "description": description,
                "W_out_kw": ask_float("Claimed electrical output (kW)"), **resource}

    if choice == "8":
        return {"model": "solar_blackbody", "title": title, "description": description,
                "T_source_K": ask_float("Blackbody source temperature (K)"),
                "T_ambient_K": ask_float("Ambient temperature (K)"),
                "irradiance_W_m2": ask_float("Incident irradiance (W/m^2)"),
                "collection_area_m2": ask_float("Effective collection area (m^2)"),
                "W_out_kw": ask_float("Claimed electrical output (kW)")}

    if choice == "9":
        return {"model": "reaction_gibbs", "title": title, "description": description,
                "reaction_direction": ask_text("Reaction direction used for Delta G"),
                "delta_G_kj_per_mol_rxn": ask_float("Signed Delta G at operating conditions (kJ/mol reaction)"),
                "reaction_rate_mol_rxn_s": ask_float("Forward reaction rate (mol reaction/s)"),
                "W_out_kw": ask_float("Claimed electrical output (kW)")}

    raise ThermoInputError("Choose a model number from 1 to 9.")


# ============================================================================
# 7. Reporting, JSON I/O and command-line entry point
# ============================================================================

def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.8g}"
    if isinstance(value, dict):
        return json.dumps(value, indent=2, ensure_ascii=False)
    if isinstance(value, list):
        return json.dumps(value, indent=2, ensure_ascii=False)
    return str(value)


def print_report(result: CaseResult) -> None:
    print("\n" + "=" * 78)
    print("THERMODYNAMIC FEASIBILITY REPORT")
    print("=" * 78)
    print(f"Case       : {result.title}")
    print(f"Model      : {result.model}")
    if result.description:
        print(f"Description: {result.description}")
    print(f"\nQUICK VERDICT: {result.verdict.status}")
    if "process_classification" in result.checks:
        print(f"PROCESS CLASSIFICATION: {result.checks['process_classification']}")

    print("\nINPUTS")
    for key, value in result.inputs.items():
        print(f"  {key}: {_format_value(value)}")

    print("\nCALCULATIONS")
    if result.calculations:
        for key, value in result.calculations.items():
            print(f"  {key}: {_format_value(value)}")
    else:
        print("  No calculations available for this model.")

    print("\nCHECKS")
    for key, value in result.checks.items():
        print(f"  {key}: {_format_value(value)}")

    print("\nASSUMPTIONS / MODEL BOUNDARY")
    for item in result.assumptions:
        print(f"  - {item}")

    print("\nVERDICT")
    print(f"  {result.verdict.status}")
    for reason in result.verdict.reasons:
        print(f"  - {reason}")
    print(f"  Note: {result.verdict.scope_note}")
    print("=" * 78)


def load_case(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError as exc:
        raise ThermoInputError(f"Input JSON file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ThermoInputError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ThermoInputError("The JSON root must be an object describing one case.")
    return data


def write_templates(folder: str = "thermo_case_templates") -> Path:
    """Write starter JSON files illustrating each supported case format."""
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    templates = {
        "fixed_reservoir_engine.json": {
            "title": "My fixed-reservoir engine", "model": "fixed_reservoir_engine",
            "description": "Describe the process and relevant boundary.",
            "T_hot_K": 600.0, "T_cold_K": 300.0, "Q_hot_kw": 100.0, "W_out_kw": 30.0
        },
        "finite_stream_engine.json": {
            "title": "My finite-stream thermal process", "model": "finite_stream_engine",
            "description": "Manually identify the hot source and cold sink from the process.",
            "hot_stream": {"name": "Hot source", "mass_flow_kg_s": 1.0, "T_in_K": 600.0,
                           "T_out_K": 400.0, "cp_model": "constant", "cp_kj_kg_k": 4.18},
            "cold_stream": {"name": "Cold sink", "mass_flow_kg_s": 2.0, "T_in_K": 300.0,
                            "T_out_K": 377.75, "cp_model": "constant", "cp_kj_kg_k": 4.18},
            "W_out_kw": 186.01,
            "apply_effective_temperature_limit": False
        },
        "steady_control_volume.json": {
            "title": "My steady control volume", "model": "steady_control_volume",
            "description": "List every mass and heat interaction crossing the chosen boundary.",
            "inlets": [{"mass_flow_kg_s": 1.0, "specific_enthalpy_kj_kg": 100.0,
                        "specific_entropy_kj_kg_k": 1.0}],
            "outlets": [{"mass_flow_kg_s": 1.0, "specific_enthalpy_kj_kg": 80.0,
                         "specific_entropy_kj_kg_k": 1.1}],
            "heat": [], "W_out_kw": 20.0, "include_kinetic_potential": False
        },
        "closed_system.json": {
            "title": "My closed-system process", "model": "closed_system",
            "description": "Specify total system changes and all heat transfers.",
            "delta_E_kj": 10.0, "delta_S_system_kj_K": 0.06,
            "heat": [{"heat_into_system_kj": 15.0, "boundary_temperature_K": 300.0}],
            "W_out_kj": 5.0
        },
        "property_change.json": {
            "title": "My property calculation", "model": "property_change",
            "description": "State 1 to state 2 property change.",
            "T1_K": 300.0, "T2_K": 500.0, "cp_model": "constant", "cp_kj_kg_k": 4.18
        }
    }
    templates.update({f"{example['model']}.json": example for example in resource_examples()})
    for filename, content in templates.items():
        with open(target / filename, "w", encoding="utf-8") as file:
            json.dump(content, file, indent=2)
    return target


def run_demonstrations() -> None:
    print("THERMODYNAMIC FEASIBILITY TESTER — VALIDATION DEMONSTRATIONS")
    passed = self_test()
    print(f"\nInternal self-tests: {len(passed)} passed")
    for i, test_name in enumerate(passed, 1):
        print(f"  {i}. PASS — {test_name}")
    for case in demonstration_cases():
        print_report(run_case(case))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Thermodynamic Feasibility Tester: structured input, model selection, balances and verdicts."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--input", metavar="FILE.json", help="Analyse a structured JSON case file.")
    group.add_argument("--demo", action="store_true", help="Run built-in validation demonstrations.")
    group.add_argument("--self-test", action="store_true", help="Run internal formula/logic tests only.")
    group.add_argument("--make-templates", action="store_true", help="Write editable JSON input templates.")
    args = parser.parse_args(argv)

    try:
        if args.self_test:
            tests = self_test()
            print(f"SELF-TEST PASSED: {len(tests)} checks")
            for item in tests:
                print(f"  PASS — {item}")
            return 0
        if args.demo:
            run_demonstrations()
            return 0
        if args.make_templates:
            folder = write_templates()
            print(f"Editable input templates written to: {folder.resolve()}")
            return 0
        if args.input:
            case = load_case(args.input)
            print_report(run_case(case))
            return 0

        case = interactive_case()
        print_report(run_case(case))
        return 0
    except (ThermoInputError, OSError) as error:
        print(f"\nINPUT / MODEL ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
