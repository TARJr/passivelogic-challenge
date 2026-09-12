"""A reproducible convergence check for an actual simulation result."""

from dataclasses import replace

import numpy as np

from .model import SimulationResult, simulate


def verify_result(result: SimulationResult) -> dict:
    """Compare the reported run with half-sized steps and tighter tolerances.

    This is independent of the algebraic balance residual: a solver can conserve
    energy and still resolve temperatures or switching times inaccurately.
    """
    refined_config = replace(
        result.config, max_step_s=result.config.max_step_s / 2,
        rtol=max(1e-13, result.config.rtol / 10), atol=result.config.atol / 10,
    )
    refined = simulate(refined_config)
    temperature_error = max(
        float(np.max(np.abs(result.series[key] - refined.series[key])))
        for key in ("collector_c", "tank_c")
    )
    energy_error = abs(
        float(result.series["tank_energy_change_j"][-1])
        - float(refined.series["tank_energy_change_j"][-1])
    )
    same_events = len(result.events) == len(refined.events) and all(
        left["pump_on"] == right["pump_on"]
        for left, right in zip(result.events, refined.events)
    )
    switch_error = max(
        abs(left["time_s"] - right["time_s"])
        for left, right in zip(result.events, refined.events)
    ) if same_events else None
    temperature_limit_c = 1e-3
    energy_limit_j = max(10.0, abs(float(refined.series["tank_energy_change_j"][-1])) * 1e-6)
    switch_limit_s = 1.0
    balance_limit = 1e-7
    passed = (
        temperature_error <= temperature_limit_c
        and energy_error <= energy_limit_j
        and same_events and switch_error <= switch_limit_s
        and result.summary["relative_balance_error"] <= balance_limit
    )
    return {
        "passed": bool(passed),
        "max_temperature_difference_c": temperature_error,
        "temperature_tolerance_c": temperature_limit_c,
        "final_tank_energy_difference_j": energy_error,
        "energy_tolerance_j": energy_limit_j,
        "same_switch_sequence": bool(same_events),
        "max_switch_time_difference_s": switch_error,
        "switch_time_tolerance_s": switch_limit_s,
        "relative_balance_error": result.summary["relative_balance_error"],
        "relative_balance_tolerance": balance_limit,
        "baseline_max_step_s": result.config.max_step_s,
        "refined_max_step_s": refined_config.max_step_s,
        "baseline_rtol": result.config.rtol,
        "refined_rtol": refined_config.rtol,
        "baseline_atol": result.config.atol,
        "refined_atol": refined_config.atol,
    }
