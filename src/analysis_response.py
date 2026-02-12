"""Structured analysis response: phases, key points, and metrics with value + explanation for API and viewer."""
from typing import Any, Dict, List

# Display order for phases and key points
PHASE_ORDER: List[str] = [
    "quiet",
    "eccentric_unloading",
    "eccentric_braking",
    "concentric",
    "flight",
    "landing",
]

KEY_POINT_ORDER: List[str] = [
    "start_of_movement",
    "minimum_force",
    "p1_peak",
    "p2_peak",
    "take_off",
    "landing",
]

# Phase name (from payload) -> slug
_PHASE_NAME_TO_SLUG: Dict[str, str] = {
    "Quiet": "quiet",
    "Eccentric - Unloading": "eccentric_unloading",
    "Eccentric - Braking": "eccentric_braking",
    "Concentric": "concentric",
    "Flight": "flight",
    "Landing": "landing",
}

PHASE_EXPLANATIONS: Dict[str, str] = {
    "quiet": "Standing still; force reflects body weight.",
    "eccentric_unloading": "Force decreases as the body lowers (unweighting).",
    "eccentric_braking": "Force increases as the individual prepares to push off.",
    "concentric": "Push upwards; force rises through P1 and P2 peaks.",
    "flight": "Airborne; force plate reads near zero.",
    "landing": "Impact and absorption after touchdown.",
}

# Key point name (from payload) -> slug
_KEY_POINT_NAME_TO_SLUG: Dict[str, str] = {
    "Start of movement": "start_of_movement",
    "Minimum force (eccentric end)": "minimum_force",
    "P1 peak": "p1_peak",
    "P2 peak": "p2_peak",
    "Take-off": "take_off",
    "Landing": "landing",
}

KEY_POINT_EXPLANATIONS: Dict[str, str] = {
    "start_of_movement": "Onset of countermovement; force first drops below baseline.",
    "minimum_force": "Lowest force in the eccentric phase (deepest unweighting).",
    "p1_peak": "First major force peak in the concentric phase.",
    "p2_peak": "Second major force peak in the concentric phase.",
    "take_off": "Last instant of contact before flight; force leaves baseline.",
    "landing": "First instant of contact after flight; force near takeoff level.",
}

METRIC_EXPLANATIONS: Dict[str, str] = {
    "take_off_velocity_m_s": "Vertical velocity at takeoff from impulse–momentum (m/s).",
    "jump_height_impulse_m": "Jump height from impulse–momentum method (m).",
    "time_to_takeoff_s": "Time from movement onset to takeoff (s).",
    "rsi_mod": "Reactive strength index (modified): jump height / time to takeoff.",
    "flight_time_s": "Time airborne from takeoff to landing (s).",
    "jump_height_flight_m": "Jump height from flight time formula (m).",
    "peak_power_W": "Peak instantaneous power during contact (W).",
    "peak_rfd_N_per_s": "Peak rate of force development during contact (N/s).",
    "max_rfd_index": "Sample index at which peak RFD occurs.",
    "max_rfd_time_s": "Time at which peak RFD occurs (s).",
    "rfd_0_100ms_N_per_s": "Peak RFD in the first 100 ms from onset (N/s).",
    "rfd_0_200ms_N_per_s": "Peak RFD in the first 200 ms from onset (N/s).",
    "peak_rfd_eccentric_N_per_s": "Peak RFD during the eccentric phase (N/s).",
    "peak_rfd_concentric_N_per_s": "Peak RFD during the concentric phase (N/s).",
    "unweighting_impulse_Ns": "Impulse from onset to minimum force (N·s).",
    "unweighting_time_s": "Duration from onset to minimum force (s).",
    "eccentric_time_s": "Duration of eccentric phase (s).",
    "peak_eccentric_velocity_m_s": "Peak downward velocity magnitude in eccentric phase (m/s).",
    "peak_concentric_force_N": "Maximum force in the concentric phase (N).",
    "mean_concentric_force_N": "Mean force during the concentric phase (N).",
    "p1_peak_index": "Sample index of the P1 force peak.",
    "p2_peak_index": "Sample index of the P2 force peak.",
    "p1_peak_N": "Force at the P1 peak (N).",
    "p2_peak_N": "Force at the P2 peak (N).",
    "min_force_N": "Minimum force in the eccentric phase (N).",
    "braking_impulse_Ns": "Impulse from minimum force to P1 (N·s).",
    "propulsion_impulse_Ns": "Impulse from P1 to takeoff (N·s).",
    "concentric_time_s": "Duration of concentric phase from P1 to takeoff (s).",
    "countermovement_depth_m": "Maximum downward COM displacement from onset (m).",
    "com_displacement_at_takeoff_m": "Vertical COM displacement at takeoff from onset (m).",
    "peak_force_asymmetry_pct": "Left–right asymmetry in peak force (%).",
    "concentric_impulse_asymmetry_pct": "Left–right asymmetry in concentric impulse (%).",
    "eccentric_impulse_asymmetry_pct": "Left–right asymmetry in eccentric impulse (%).",
    "rfd_asymmetry_pct": "Left–right asymmetry in peak RFD (%).",
    "structural_peak_num_cycles": "Number of rise–fall cycles detected in the concentric phase.",
    "structural_peak_confidence": "Confidence score (0–1) for structural P1/P2 detection.",
}


def build_analysis_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build the structured analysis block: phases, key_points, metrics as key -> { value, explanation }.

    Uses the existing visualization payload (phases, key_points, metrics). Adds phase_order and
    key_point_order for deterministic display order. Unknown keys get an empty explanation.
    """
    analysis: Dict[str, Any] = {
        "phases": {},
        "key_points": {},
        "metrics": {},
        "phase_order": PHASE_ORDER,
        "key_point_order": KEY_POINT_ORDER,
    }

    for p in payload.get("phases") or []:
        name = p.get("name") or ""
        slug = _PHASE_NAME_TO_SLUG.get(name, name.lower().replace(" - ", "_").replace(" ", "_"))
        explanation = PHASE_EXPLANATIONS.get(slug, "")
        analysis["phases"][slug] = {"value": dict(p), "explanation": explanation}

    for kp in payload.get("key_points") or []:
        name = kp.get("name") or ""
        slug = _KEY_POINT_NAME_TO_SLUG.get(name, name.lower().replace(" ", "_").replace("(", "").replace(")", ""))
        explanation = KEY_POINT_EXPLANATIONS.get(slug, "")
        analysis["key_points"][slug] = {"value": dict(kp), "explanation": explanation}

    for k, v in (payload.get("metrics") or {}).items():
        explanation = METRIC_EXPLANATIONS.get(k, "")
        analysis["metrics"][k] = {"value": v, "explanation": explanation}

    return analysis
