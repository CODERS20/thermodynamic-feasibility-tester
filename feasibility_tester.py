"""
feasibility_tester.py
=====================
Thermodynamic feasibility engine based on a universal entropy-generation balance:

    S_gen = dS_sys - Entropy_in + Entropy_out          (S2 - S1 equation)

Every domain path (thermal/fluid, chemical, mechanical/electrical, solar) reduces
to three universal variables -- E_in, dS_sys, Entropy_in -- which then converge
into one First-Law gate (Q_out >= 0) and one Second-Law gate (S_gen >= 0).

Usage
-----
    from feasibility_tester import FeasibilityTester
    result = FeasibilityTester().evaluate({
        "domain": "thermal_fluid", "process_type": "cycle",
        "Q_in": 1000, "T_source": 600, "W_actual": 400, "T_0": 300,
    })
    print(result["verdict"], result["S_gen"], result["eta_II"])

CLI:  python feasibility_tester.py input.json      (or "-" to read stdin)

Units: all inputs are SI (K, Pa, J, W, J/K, kg ...). E_in, W_actual and the
entropy terms must share one basis (all power [W, W/K] or all energy [J, J/K]).
"""
from __future__ import annotations

import argparse
import bisect
import copy
import json
import math
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

DEFAULT_TOL = 1e-4          # S_gen tolerance (units of the entropy basis, e.g. J/K)
T_SUN_DEFAULT = 5778.0      # K
G_STD = 9.80665             # m/s^2
_MISSING = object()


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class FeasibilityError(Exception):
    """Base class for all engine errors."""


class PreCheckError(FeasibilityError):
    """Step 0 failed (units, T <= 0, efficiency out of [0, 1], non-finite input)."""


class InputError(FeasibilityError):
    """Missing / malformed parameters for the selected path."""


# --------------------------------------------------------------------------- #
# Numerical helpers (dependency-free)
# --------------------------------------------------------------------------- #
def brent(f: Callable[[float], float], a: float, b: float,
          xtol: float = 1e-10, maxiter: int = 200) -> float:
    """Brent's root-finding method on a bracketing interval [a, b]."""
    fa, fb = f(a), f(b)
    if fa == 0.0:
        return a
    if fb == 0.0:
        return b
    if fa * fb > 0:
        raise InputError("Root not bracketed: target property is outside the "
                         "searchable temperature range (or crosses a phase boundary).")
    if abs(fa) < abs(fb):
        a, b, fa, fb = b, a, fb, fa
    c, fc, d, mflag = a, fa, a, True
    for _ in range(maxiter):
        if fb == 0.0 or abs(b - a) < xtol:
            return b
        if fa != fc and fb != fc:      # inverse quadratic interpolation
            s = (a * fb * fc / ((fa - fb) * (fa - fc))
                 + b * fa * fc / ((fb - fa) * (fb - fc))
                 + c * fa * fb / ((fc - fa) * (fc - fb)))
        else:                          # secant
            s = b - fb * (b - a) / (fb - fa)
        lo, hi = sorted(((3 * a + b) / 4, b))
        if (not lo < s < hi
                or (mflag and abs(s - b) >= abs(b - c) / 2)
                or (not mflag and abs(s - b) >= abs(c - d) / 2)
                or (mflag and abs(b - c) < xtol)
                or (not mflag and abs(c - d) < xtol)):
            s, mflag = (a + b) / 2, True          # fall back to bisection
        else:
            mflag = False
        fs = f(s)
        d, c, fc = c, b, fb
        if fa * fs < 0:
            b, fb = s, fs
        else:
            a, fa = s, fs
        if abs(fa) < abs(fb):
            a, b, fa, fb = b, a, fb, fa
    return b


def bisect_root(f: Callable[[float], float], a: float, b: float,
                xtol: float = 1e-10, maxiter: int = 300) -> float:
    """Plain bisection on a bracketing interval [a, b]."""
    fa, fb = f(a), f(b)
    if fa == 0.0:
        return a
    if fb == 0.0:
        return b
    if fa * fb > 0:
        raise InputError("Root not bracketed: target property is outside the "
                         "searchable temperature range (or crosses a phase boundary).")
    for _ in range(maxiter):
        m = 0.5 * (a + b)
        fm = f(m)
        if fm == 0.0 or 0.5 * abs(b - a) < xtol:
            return m
        if fa * fm < 0:
            b, fb = m, fm
        else:
            a, fa = m, fm
    return 0.5 * (a + b)


def simpson(f: Callable[[float], float], a: float, b: float, n: int = 2000) -> float:
    """Composite Simpson's rule (works for a > b, returning a signed integral)."""
    if a == b:
        return 0.0
    n += n % 2
    h = (b - a) / n
    odd = sum(f(a + i * h) for i in range(1, n, 2))
    even = sum(f(a + i * h) for i in range(2, n, 2))
    return (f(a) + f(b) + 4 * odd + 2 * even) * h / 3


# --------------------------------------------------------------------------- #
# Property backends (pluggable)
# --------------------------------------------------------------------------- #
class CoolPropBackend:
    """Mass-basis properties via CoolProp (pip install CoolProp)."""
    requires_fluid = True
    _KEYS = {"h": "H", "s": "S", "u": "U", "cp": "C"}

    def __init__(self) -> None:
        from CoolProp.CoolProp import PropsSI  # raises ImportError if absent
        self._props = PropsSI

    def get(self, out: str, T: float, P: float, fluid: Optional[str]) -> float:
        return self._props(self._KEYS[out], "T", T, "P", P, fluid)

    def T_range(self, fluid: Optional[str]) -> Tuple[float, float]:
        return (self._props("Tmin", fluid) * 1.001, self._props("Tmax", fluid) * 0.999)


class IdealGasBackend:
    """Constant-cp ideal gas. Useful offline, for tests, or as a CoolProp stand-in."""
    requires_fluid = False

    def __init__(self, cp: float, R: float, T_ref: float = 298.15,
                 P_ref: float = 1e5, T_bounds: Tuple[float, float] = (1.0, 5000.0)):
        self.cp, self.R, self.T_ref, self.P_ref, self.T_bounds = cp, R, T_ref, P_ref, T_bounds

    def get(self, out: str, T: float, P: float, fluid: Optional[str] = None) -> float:
        if out == "h":
            return self.cp * (T - self.T_ref)
        if out == "u":
            return (self.cp - self.R) * (T - self.T_ref)
        if out == "s":
            return self.cp * math.log(T / self.T_ref) - self.R * math.log(P / self.P_ref)
        if out == "cp":
            return self.cp
        raise KeyError(out)

    def T_range(self, fluid: Optional[str] = None) -> Tuple[float, float]:
        return self.T_bounds


def _default_backend():
    try:
        return CoolPropBackend()
    except Exception:       # CoolProp not installed
        return None


# --------------------------------------------------------------------------- #
# Input helpers
# --------------------------------------------------------------------------- #
def _num(p: Mapping[str, Any], *keys: str, default: Any = _MISSING) -> float:
    for k in keys:
        if k in p:
            v = p[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise InputError(f"Parameter '{k}' must be a finite number, got {v!r}")
            return float(v)
    if default is not _MISSING:
        return default
    raise InputError(f"Missing required parameter: {' / '.join(keys)}")


def _canon(value: Any, aliases: Mapping[str, str], label: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    if key in aliases:
        return aliases[key]
    raise InputError(f"Unknown {label} {value!r}; expected one of {sorted(set(aliases.values()))}")


_DOMAIN = {
    "1": "thermal", "thermal": "thermal", "thermal_fluid": "thermal", "thermal_fluid_systems": "thermal",
    "2": "chemical", "chemical": "chemical", "chemical_rxn": "chemical",
    "chemical_electrochemical": "chemical", "electrochemical": "chemical",
    "3": "mechanical", "mechanical": "mechanical", "mechanical_electrical": "mechanical",
    "mech_elec_work": "mechanical", "electrical": "mechanical",
    "4": "solar", "solar": "solar", "solar_radiative": "solar", "radiative": "solar",
}
_PROCESS = {
    "1": "cycle", "cycle": "cycle", "full_cycle": "cycle", "full_thermodynamic_cycle": "cycle",
    "2": "steady_flow", "steady_flow": "steady_flow", "steady_flow_component": "steady_flow",
    "3": "closed", "closed": "closed", "closed_system": "closed", "closed_system_process": "closed",
}
_CHEM = {
    "1": "hs", "enthalpy_entropy": "hs", "standard_enthalpy_entropy": "hs",
    "2": "gibbs", "gibbs": "gibbs", "gibbs_free_energy": "gibbs",
}
_WORK = {
    "electrical": "electrical", "kinetic": "kinetic", "kinetic_fluid": "kinetic",
    "potential": "potential", "potential_gravity": "potential",
    "shaft": "shaft", "shaft_rotational": "shaft",
    "boundary": "boundary", "boundary_pressure": "boundary",
    "generic": "generic", "generic_work": "generic", "work_input": "generic",
}
_MODEL = {"constant_cp": "constant_cp", "variable_cp": "variable_cp",
          "phase_change": "phase_change", "state_properties": "state_properties"}

_TEMP_KEYS = ("T_0", "T_source", "T_sun", "T_phase", "T_sink", "sink_T_in", "sink_T_out")
_EFF_KEYS = ("eta", "eta_claimed", "efficiency")


def _pre_checks(p: Mapping[str, Any]) -> None:
    """Step 0 -- units, physical bounds, finiteness. Raises PreCheckError."""
    if str(p.get("units", "SI")).upper() != "SI":
        raise PreCheckError("Unit consistency: engine requires SI units (set units='SI').")

    def positive(name: str, v: Any) -> None:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise PreCheckError(f"{name} must be a finite number, got {v!r}")
        if v <= 0:
            raise PreCheckError(f"Physical bound violated: {name} = {v} must be > 0")

    for k in _TEMP_KEYS:
        if k in p:
            positive(k, p[k])
    for sk in ("state1", "state2"):
        st = p.get(sk) or {}
        if "T" in st:
            positive(f"{sk}.T", st["T"])
        if "P" in st:
            positive(f"{sk}.P", st["P"])
    for k in _EFF_KEYS:
        if k in p and not (isinstance(p[k], (int, float)) and 0.0 <= p[k] <= 1.0):
            raise PreCheckError(f"Efficiency '{k}' must satisfy 0 <= eta <= 1, got {p[k]!r}")


# --------------------------------------------------------------------------- #
# State containers
# --------------------------------------------------------------------------- #
@dataclass
class _Universal:
    """The three universal variables plus bookkeeping (Step 0 initial values = 0)."""
    E_in: float = 0.0
    dS_sys: float = 0.0
    entropy_in: float = 0.0
    T_H_eff: Optional[float] = None       # mapped effective hot temperature (for Carnot)
    trace: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class _Integration:
    dH: float
    dS: float
    T_eff: Optional[float]
    model: str


@dataclass
class FeasibilityResult:
    verdict: str
    S_gen: Optional[float]
    W_lost: Optional[float]
    eta_rev: Optional[float]
    eta_II: Optional[float]
    E_in: float
    dS_sys: float
    entropy_in: float
    Q_out: float
    entropy_out: Optional[float]
    W_actual: float
    W_rev_max: Optional[float]
    T_0: float
    T_H_eff: Optional[float]
    eta_rev_basis: Optional[str]
    T_sink_eff: Optional[float] = None
    sink_basis: Optional[str] = None
    error: Optional[str] = None
    path: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #
class FeasibilityTester:
    """State machine: Pre-checks -> Domain routing -> Convergence -> Verdict."""

    def __init__(self, backend: Any = "auto", tol: float = DEFAULT_TOL,
                 root_method: str = "brent") -> None:
        self.backend = _default_backend() if backend == "auto" else backend
        self.tol = tol
        if root_method not in ("brent", "bisection"):
            raise ValueError("root_method must be 'brent' or 'bisection'")
        self.root_method = root_method
        self._handlers: Dict[str, Callable[[dict, _Universal], None]] = {
            "thermal": self._thermal,
            "chemical": self._chemical,
            "mechanical": self._mechanical,
            "solar": self._solar,
        }

    # ---- public entry point ------------------------------------------------ #
    def evaluate(self, params: Any) -> Dict[str, Any]:
        """Run the full pipeline. `params` is a dict or a JSON string."""
        if isinstance(params, (str, bytes)):
            params = json.loads(params)
        p = copy.deepcopy(dict(params))          # never mutate caller's input

        _pre_checks(p)                           # Step 0
        u = _Universal()                         # E_in = dS_sys = Entropy_in = 0
        domain = _canon(p.get("domain", p.get("primary_energy_domain")), _DOMAIN, "domain")
        u.trace.append(f"D1:{domain}")
        self._handlers[domain](p, u)             # Step 1
        return self._converge(p, u).to_dict()    # Steps 2-4

    # ======================================================================= #
    # Step 1 -- domain handlers
    # ======================================================================= #
    # ---- Case 1: thermal / fluid ------------------------------------------ #
    def _thermal(self, p: dict, u: _Universal) -> None:
        ptype = _canon(p.get("process_type"), _PROCESS, "process_type")
        u.trace.append(f"T1:{ptype}")

        if ptype == "cycle":                                      # Sub-case A
            Q_in = _num(p, "Q_in")
            T_src = _num(p, "T_source")
            u.dS_sys, u.E_in = 0.0, Q_in
            u.entropy_in, u.T_H_eff = Q_in / T_src, T_src
            return

        m = _num(p, "mass_flow", "m_dot") if ptype == "steady_flow" else _num(p, "mass", "m")
        st1, st2 = p.get("state1"), p.get("state2")
        if not isinstance(st1, dict) or not isinstance(st2, dict):
            raise InputError("Thermal steady-flow/closed paths need 'state1' and 'state2' objects.")
        fluid = p.get("fluid")

        self._complete_state(st1, fluid, "state1", u)             # Decision T2
        self._complete_state(st2, fluid, "state2", u)
        integ = self._integrate(p, m, st1, st2, fluid, u)         # Decision T3

        if ptype == "steady_flow":                                # Sub-case B
            u.dS_sys = integ.dS                                   # m_dot (s2 - s1)
            u.E_in = -integ.dH                                    # m_dot (h1 - h2)
            u.entropy_in = 0.0
            u.T_H_eff = integ.T_eff
        else:                                                     # Sub-case C
            Q_in = _num(p, "Q_in", default=0.0)
            dU = self._delta_U(p, m, st1, st2, integ)
            u.dS_sys = integ.dS                                   # m (s2 - s1)
            u.E_in = -dU + Q_in                                   # m (u1 - u2) + Q_in
            if Q_in != 0.0:
                T_src = _num(p, "T_source")
                u.entropy_in = Q_in / T_src
                u.T_H_eff = T_src if Q_in > 0 else integ.T_eff
            else:
                u.T_H_eff = integ.T_eff

    # -- missing-state logic (Decision T2) -- #
    def _need_backend(self) -> Any:
        if self.backend is None:
            raise InputError("A missing temperature/property needs a property backend: "
                             "pip install CoolProp, or pass backend=IdealGasBackend(...).")
        return self.backend

    def _solve_T(self, key: str, target: float, P: float, fluid: Optional[str],
                 bracket: Optional[Tuple[float, float]]) -> float:
        be = self._need_backend()
        if be.requires_fluid and not fluid:
            raise InputError("'fluid' is required to solve for a missing temperature.")
        lo, hi = bracket or be.T_range(fluid)

        def f(T: float) -> float:
            return be.get(key, T, P, fluid) - target

        solver = brent if self.root_method == "brent" else bisect_root
        try:
            return solver(f, lo, hi)
        except ValueError as exc:   # e.g. CoolProp failing exactly on a phase boundary
            raise InputError(f"Property solve failed: {exc}") from exc

    def _complete_state(self, st: dict, fluid: Optional[str], label: str, u: _Universal) -> None:
        if "T" not in st:
            key = next((k for k in ("h", "s", "u") if k in st), None)
            if key is None or "P" not in st:
                raise InputError(f"{label}: temperature missing and cannot be solved "
                                 "(provide P plus one of h, s, u).")
            st["T"] = self._solve_T(key, float(st[key]), float(st["P"]), fluid,
                                    st.get("T_bracket"))
            u.trace.append(f"T2:root_finding({label}.T from {key})")
        else:
            u.trace.append(f"T2:explicit({label})")
        # Fill any missing h/s/u from the property library when possible.
        if "P" in st and self.backend is not None and (fluid or not self.backend.requires_fluid):
            for k in ("h", "s", "u"):
                if k not in st:
                    st[k] = self.backend.get(k, st["T"], st["P"], fluid)

    # -- property integration (Decision T3) -- #
    def _cp_function(self, p: dict, fluid: Optional[str], P: Optional[float]) -> Callable[[float], float]:
        if callable(p.get("cp_func")):
            return p["cp_func"]
        if "cp_polynomial" in p:                     # cp = a0 + a1 T + a2 T^2 + ...
            coeffs = [float(c) for c in p["cp_polynomial"]]
            return lambda T: sum(c * T ** i for i, c in enumerate(coeffs))
        if "cp_table" in p:                          # [[T, cp], ...] linear interpolation
            pts = sorted((float(t), float(c)) for t, c in p["cp_table"])
            xs = [t for t, _ in pts]

            def interp(T: float) -> float:
                if not xs[0] <= T <= xs[-1]:
                    raise InputError(f"cp_table does not cover T = {T:.2f} K")
                i = min(max(bisect.bisect_right(xs, T) - 1, 0), len(xs) - 2)
                (t0, c0), (t1, c1) = pts[i], pts[i + 1]
                return c0 + (c1 - c0) * (T - t0) / (t1 - t0)
            return interp
        if self.backend is not None and P is not None:
            be = self.backend
            return lambda T: be.get("cp", T, P, fluid)
        raise InputError("variable_cp needs cp_func, cp_polynomial, cp_table, or fluid + P with a backend.")

    def _choose_model(self, p: dict, st1: dict, st2: dict) -> str:
        if "property_model" in p:
            return _canon(p["property_model"], _MODEL, "property_model")
        if "latent_heat" in p:
            return "phase_change"
        if any(k in p for k in ("cp_func", "cp_polynomial", "cp_table")):
            return "variable_cp"
        if "cp" in p:
            return "constant_cp"
        if all(k in s for s in (st1, st2) for k in ("h", "s")):
            return "state_properties"
        raise InputError("Cannot choose a property-integration method: give cp, a variable-cp "
                         "source, latent_heat, or full h/s data (or fluid + T/P).")

    def _integrate(self, p: dict, m: float, st1: dict, st2: dict,
                   fluid: Optional[str], u: _Universal) -> _Integration:
        model = self._choose_model(p, st1, st2)
        u.trace.append(f"T3:{model}")
        T1, T2 = st1.get("T"), st2.get("T")

        if model == "constant_cp":
            cp = _num(p, "cp")
            dH = m * cp * (T2 - T1)
            dS = m * cp * math.log(T2 / T1)
            T_eff = T1 if T1 == T2 else (T2 - T1) / math.log(T2 / T1)
        elif model == "variable_cp":
            cp_fn = self._cp_function(p, fluid, st1.get("P"))
            dH = m * simpson(cp_fn, T1, T2)
            dS = m * simpson(lambda T: cp_fn(T) / T, T1, T2)
            T_eff = abs(dH) / abs(dS) if abs(dS) > 1e-300 else T1
        elif model == "phase_change":
            T_ph = _num(p, "T_phase")
            dH = m * _num(p, "latent_heat")          # signed: h2 - h1 (J/kg)
            dS = dH / T_ph
            T_eff = T_ph
        else:                                        # state_properties
            dH = m * (st2["h"] - st1["h"])
            dS = m * (st2["s"] - st1["s"])
            T_eff = abs(dH) / abs(dS) if abs(dS) > 1e-300 else T1
        return _Integration(dH, dS, T_eff, model)

    @staticmethod
    def _delta_U(p: dict, m: float, st1: dict, st2: dict, integ: _Integration) -> float:
        if "u" in st1 and "u" in st2:
            return m * (st2["u"] - st1["u"])
        T1, T2 = st1.get("T"), st2.get("T")
        if "cv" in p and T1 is not None and T2 is not None:
            return m * float(p["cv"]) * (T2 - T1)
        if p.get("incompressible"):
            return integ.dH
        if "R" in p and T1 is not None and T2 is not None:     # ideal gas
            return integ.dH - m * float(p["R"]) * (T2 - T1)
        raise InputError("Closed system needs u on both states, or cv, or R (ideal gas), "
                         "or incompressible=true.")

    # ---- Case 2: chemical / electrochemical ------------------------------- #
    def _chemical(self, p: dict, u: _Universal) -> None:
        dtype = _canon(p.get("data_type"), _CHEM, "data_type")
        u.trace.append(f"C1:{dtype}")
        dH = _num(p, "delta_H")
        if dtype == "hs":
            u.dS_sys = _num(p, "delta_S")
        else:
            dG, T0 = _num(p, "delta_G"), _num(p, "T_0")
            u.dS_sys = (dH - dG) / T0
        u.E_in = abs(dH)
        u.entropy_in = 0.0            # chemical potential stored internally

    # ---- Case 3: mechanical / electrical work ------------------------------ #
    def _mechanical(self, p: dict, u: _Universal) -> None:
        wtype = _canon(p.get("work_type"), _WORK, "work_type")
        u.trace.append(f"M1:{wtype}")
        if wtype == "electrical":
            E = _num(p, "V") * _num(p, "I")
        elif wtype == "kinetic":
            E = 0.5 * _num(p, "mass_flow", "m_dot") * _num(p, "v") ** 2
        elif wtype == "potential":
            E = _num(p, "mass_flow", "m_dot") * _num(p, "g", default=G_STD) * _num(p, "height", "z")
        elif wtype == "shaft":
            E = _num(p, "torque", "tau") * _num(p, "omega")
        elif wtype == "boundary":
            E = _num(p, "P") * _num(p, "delta_V")
        else:  # generic: an already-resolved recoverable work rate, or energy x event rate
            if "energy_per_event" in p or "events_per_s" in p:
                E = _num(p, "energy_per_event") * _num(p, "events_per_s")
            else:
                E = _num(p, "W_input", "work_input")
        u.E_in, u.dS_sys, u.entropy_in = E, 0.0, 0.0   # pure work carries zero entropy

    # ---- Case 4: solar / radiative ----------------------------------------- #
    def _solar(self, p: dict, u: _Universal) -> None:
        Q = _num(p, "Q_sun")
        T_sun = _num(p, "T_sun", default=T_SUN_DEFAULT)
        if T_sun <= 0:
            raise PreCheckError(f"T_sun = {T_sun} must be > 0")
        u.dS_sys, u.E_in = 0.0, Q
        u.entropy_in, u.T_H_eff = Q / T_sun, T_sun

    # ---- sink temperature (Decision 3) ------------------------------------- #
    @staticmethod
    def _sink_temperature(p: dict, T0: float) -> Tuple[float, str]:
        """Resolve the effective sink temperature the waste heat is rejected at.

        The default assumes an infinite ambient reservoir pinned at T_0. When the
        sink is actually a finite stream that warms as it absorbs, pinning it at
        T_0 overstates Entropy_out and therefore S_gen. Supplying either an
        explicit T_sink, or the sink stream's inlet and outlet temperatures,
        resolves this. For a constant-Cp stream the log-mean temperature makes
        Q_out / T_sink_eff identically equal to the stream's own entropy rise,
        so the universal equation becomes exact rather than approximate.
        """
        if "T_sink" in p:
            return _num(p, "T_sink"), "explicit T_sink"
        if "sink_T_in" in p or "sink_T_out" in p:
            t_in, t_out = _num(p, "sink_T_in"), _num(p, "sink_T_out")
            if t_out <= t_in:
                raise InputError("sink_T_out must exceed sink_T_in: the sink stream absorbs heat.")
            return (t_out - t_in) / math.log(t_out / t_in), "log-mean of finite sink stream"
        return T0, "ambient reservoir at T_0"

    # ======================================================================= #
    # Steps 2-4 -- convergence, entropy generation, verdict
    # ======================================================================= #
    def _converge(self, p: dict, u: _Universal) -> FeasibilityResult:
        T0 = _num(p, "T_0")
        if "W_actual" in p:
            W = _num(p, "W_actual")
        else:                                           # derive from a claimed efficiency
            eta_key = next((k for k in _EFF_KEYS if k in p), None)
            if eta_key is None:
                raise InputError("Provide W_actual (or a claimed efficiency: eta / eta_claimed).")
            W = float(p[eta_key]) * u.E_in
            u.notes.append(f"W_actual derived as {eta_key} * E_in")

        # ---- Step 2: First-Law gate ----
        Q_out = u.E_in - W
        u.trace.append("D4:first_law")
        if Q_out < -1e-9 * max(1.0, abs(u.E_in)):       # relative tol. absorbs float noise
            u.trace.append("REJECT")
            return FeasibilityResult(
                verdict="REJECT (First Law Violation)", S_gen=None, W_lost=None, eta_rev=None,
                eta_II=None, E_in=u.E_in, dS_sys=u.dS_sys, entropy_in=u.entropy_in, Q_out=Q_out,
                entropy_out=None, W_actual=W, W_rev_max=None, T_0=T0, T_H_eff=u.T_H_eff,
                eta_rev_basis=None, error="First Law Violation: energy not conserved "
                                          "(claimed work exceeds energy input).",
                path=u.trace, notes=u.notes)
        Q_out = max(Q_out, 0.0)
        T_sink, sink_basis = self._sink_temperature(p, T0)
        if T_sink <= 0:
            raise PreCheckError(f"T_sink_eff = {T_sink} must be > 0")
        entropy_out = Q_out / T_sink
        if sink_basis != "ambient reservoir at T_0":
            u.notes.append(f"Entropy_out used T_sink_eff = {T_sink:.6g} K ({sink_basis})")

        # ---- Step 3: universal entropy generation + reversible limit ----
        S_gen = u.dS_sys - u.entropy_in + entropy_out
        W_rev = u.E_in - T_sink * (u.entropy_in - u.dS_sys)  # work when S_gen == 0

        if u.T_H_eff is not None:
            eta_rev = 1.0 - T0 / u.T_H_eff               # Carnot, T_C,eff = T_0
            basis = "carnot(T_H_eff, T_0)"
            if eta_rev < 0:
                eta_rev, basis = 0.0, "carnot(T_H_eff <= T_0 -> clamped to 0)"
                u.notes.append("T_H_eff <= T_0: no work extractable between these temperatures.")
        elif u.E_in > 0:
            eta_rev = W_rev / u.E_in                     # no heat reservoir: S_gen = 0 limit
            basis = "universal(S_gen=0)"
        else:
            eta_rev, basis = None, None

        # ---- Step 4: verdict ----
        u.trace.append("D5:clausius")
        if S_gen < -self.tol:
            verdict, W_lost, eta_II = "IMPOSSIBLE (Second Law Violation)", None, None
        else:
            if abs(S_gen) <= self.tol:
                verdict, W_lost = "REVERSIBLE LIMIT", 0.0
            else:
                verdict, W_lost = "FEASIBLE", T0 * S_gen
            denom = W + W_lost
            eta_II = W / denom if denom > 0 else None
        u.trace.append(verdict.split(" (")[0])

        return FeasibilityResult(
            verdict=verdict, S_gen=S_gen, W_lost=W_lost, eta_rev=eta_rev, eta_II=eta_II,
            E_in=u.E_in, dS_sys=u.dS_sys, entropy_in=u.entropy_in, Q_out=Q_out,
            entropy_out=entropy_out, W_actual=W, W_rev_max=W_rev, T_0=T0, T_H_eff=u.T_H_eff,
            eta_rev_basis=basis, T_sink_eff=T_sink, sink_basis=sink_basis,
            path=u.trace, notes=u.notes)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Thermodynamic feasibility tester (S2 - S1).")
    ap.add_argument("input", help="JSON file with parameters, or '-' for stdin")
    ap.add_argument("--tol", type=float, default=DEFAULT_TOL, help="S_gen tolerance")
    ap.add_argument("--root-method", choices=("brent", "bisection"), default="brent")
    args = ap.parse_args(argv)
    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    try:
        out = FeasibilityTester(tol=args.tol, root_method=args.root_method).evaluate(raw)
    except FeasibilityError as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, indent=2))
        return 2
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
