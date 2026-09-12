"""Transient, energy-conserving two-node solar thermal model.

All internal quantities use SI units except temperatures (degrees Celsius,
with differences in kelvin) and the tank volume input (litres). See docs/model.md.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from scipy.integrate import solve_ivp


class ModelDomainError(ValueError):
    """The single-phase liquid model has reached its configured validity limit."""


@dataclass(frozen=True)
class SimulationConfig:
    collector_area_m2: float = 4.0
    optical_efficiency: float = 0.75
    collector_loss_w_m2k: float = 5.0
    collector_capacity_j_k: float = 15000.0
    tank_volume_l: float = 200.0
    tank_loss_w_k: float = 2.0
    water_density_kg_m3: float = 1000.0
    water_cp_j_kgk: float = 4180.0
    mass_flow_kg_s: float = 0.03
    pump_mode: str = "differential"
    pump_power_w: float = 25.0
    pump_on_delta_k: float = 6.0
    pump_off_delta_k: float = 2.0
    ambient_c: float = 20.0
    irradiance_profile: str = "clear"
    peak_irradiance_w_m2: float = 800.0
    constant_irradiance_w_m2: float = 0.0
    sunrise_hour: float = 6.0
    sunset_hour: float = 18.0
    initial_collector_c: float = 20.0
    initial_tank_c: float = 20.0
    duration_s: float = 86400.0
    output_step_s: float = 60.0
    max_step_s: float = 60.0
    rtol: float = 1e-8
    atol: float = 1e-8
    min_temperature_c: float = 0.0
    max_temperature_c: float = 95.0

    @property
    def tank_capacity_j_k(self) -> float:
        return self.tank_volume_l / 1000 * self.water_density_kg_m3 * self.water_cp_j_kgk

    def validate(self) -> None:
        """Reject ambiguous, nonphysical or computationally unusable inputs."""
        enum_fields = {
            "pump_mode": {"differential", "continuous", "off"},
            "irradiance_profile": {"clear", "cloudy", "constant"},
        }
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name in enum_fields:
                if not isinstance(value, str) or value not in enum_fields[field.name]:
                    raise ValueError(f"{field.name} must be one of {sorted(enum_fields[field.name])}")
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{field.name} must be a finite number")

        positive = (
            "collector_area_m2", "collector_capacity_j_k", "tank_volume_l",
            "water_density_kg_m3", "water_cp_j_kgk", "duration_s",
            "output_step_s", "max_step_s", "rtol", "atol",
        )
        nonnegative = (
            "collector_loss_w_m2k", "tank_loss_w_k", "mass_flow_kg_s",
            "pump_power_w", "pump_off_delta_k", "peak_irradiance_w_m2",
            "constant_irradiance_w_m2",
        )
        for name in positive:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")
        for name in nonnegative:
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be nonnegative")
        if not 0 <= self.optical_efficiency <= 1:
            raise ValueError("optical_efficiency must be between 0 and 1")
        if self.pump_on_delta_k <= self.pump_off_delta_k:
            raise ValueError("pump_on_delta_k must exceed pump_off_delta_k")
        if not 0 <= self.sunrise_hour < self.sunset_hour <= 24:
            raise ValueError("Require 0 <= sunrise_hour < sunset_hour <= 24")
        if not 0 <= self.min_temperature_c < self.max_temperature_c <= 100:
            raise ValueError("Temperature bounds must satisfy 0 <= min < max <= 100 Celsius")
        for name in ("initial_collector_c", "initial_tank_c"):
            if not self.min_temperature_c < getattr(self, name) < self.max_temperature_c:
                raise ValueError(f"{name} must be strictly inside the temperature bounds")
        if self.rtol < 1e-13 or self.rtol > 1e-2 or self.atol > 1e-2:
            raise ValueError("Require 1e-13 <= rtol <= 1e-2 and 0 < atol <= 1e-2")
        if self.duration_s / self.output_step_s > 1_000_000:
            raise ValueError("Requested output exceeds one million samples; increase output_step_s")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SimulationResult:
    config: SimulationConfig
    series: dict[str, np.ndarray]
    summary: dict[str, Any]
    events: list[dict[str, Any]]


def config_from_dict(values: Mapping[str, Any]) -> SimulationConfig:
    """Load partial overrides; unknown keys are errors, never silently ignored."""
    if not isinstance(values, Mapping):
        raise ValueError("Configuration must be a JSON object")
    unknown = set(values) - {field.name for field in fields(SimulationConfig)}
    if unknown:
        raise ValueError(f"Unknown configuration keys: {', '.join(sorted(map(str, unknown)))}")
    config = SimulationConfig(**values)
    config.validate()
    return config


def load_config(path: str | Path) -> SimulationConfig:
    return config_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def irradiance(time_s: float, config: SimulationConfig) -> float:
    """Synthetic incident irradiance on the collector plane, in W/m2.

    Profiles repeat every 24 hours. They are reproducible scenarios, not measured
    weather or a solar-position calculation. Gaussian cloud dips are smooth.
    """
    if config.irradiance_profile == "constant":
        return config.constant_irradiance_w_m2
    hour = (time_s / 3600) % 24
    if hour <= config.sunrise_hour or hour >= config.sunset_hour:
        return 0.0
    phase = (hour - config.sunrise_hour) / (config.sunset_hour - config.sunrise_hour)
    radiation = config.peak_irradiance_w_m2 * math.sin(math.pi * phase)
    if config.irradiance_profile == "cloudy":
        for center, width, attenuation in ((10, 0.45, 0.75), (12.5, 0.6, 0.85), (15, 0.35, 0.65)):
            radiation *= 1 - attenuation * math.exp(-0.5 * ((hour - center) / width) ** 2)
    return radiation


def _event_record(time_s: float, y: np.ndarray, pump_on: bool) -> dict[str, Any]:
    return {
        "time_s": float(time_s), "pump_on": bool(pump_on),
        "collector_c": float(y[0]), "tank_c": float(y[1]),
    }


def _domain_events(config: SimulationConfig) -> list:
    events = []
    for index in (0, 1):
        for upper in (False, True):
            def limit(t, y, index=index, upper=upper):
                return (config.max_temperature_c - y[index]) if upper else (y[index] - config.min_temperature_c)
            limit.terminal = True
            limit.direction = -1
            events.append(limit)
    return events


def _next_forcing_boundary(time_s: float, config: SimulationConfig) -> float:
    """Split at dawn/dusk so a large solver step cannot skip all of daylight."""
    if config.irradiance_profile == "constant":
        return config.duration_s
    day = math.floor(time_s / 86400)
    candidates = [config.duration_s]
    for offset in (day, day + 1):
        for hour in (config.sunrise_hour, config.sunset_hour):
            boundary = offset * 86400 + hour * 3600
            if boundary > time_s:
                candidates.append(boundary)
    return min(candidates)


def simulate(config: SimulationConfig | None = None) -> SimulationResult:
    """Integrate temperatures and energy accounts, resolving pump switches.

    The output interval controls reporting only. DOP853 selects internal steps;
    max_step_s caps them. At a threshold crossing the integration stops, switches
    pump state and restarts from the same continuous thermal/energy state.
    """
    config = config or SimulationConfig()
    config.validate()
    cc = config.collector_capacity_j_k
    ct = config.tank_capacity_j_k
    collector_ua = config.collector_area_m2 * config.collector_loss_w_m2k
    flow_conductance = config.mass_flow_kg_s * config.water_cp_j_kgk
    # State: Tc, Tt, incident, absorbed, collector loss, tank loss, transfer,
    # pump electricity (energies in joules). Loss and transfer states are signed.
    y = np.array([config.initial_collector_c, config.initial_tank_c, 0., 0., 0., 0., 0., 0.])
    pump_on = config.mass_flow_kg_s > 0 and (
        config.pump_mode == "continuous" or (
            config.pump_mode == "differential" and y[0] - y[1] >= config.pump_on_delta_k
        )
    )
    events = [_event_record(0, y, pump_on)]
    segments = []
    now = 0.0
    evaluations = 0
    runtime_s = 0.0

    while now < config.duration_s:
        active = pump_on

        def rhs(t, state):
            tc, tt = state[:2]
            incident = config.collector_area_m2 * irradiance(t, config)
            absorbed = config.optical_efficiency * incident
            collector_loss = collector_ua * (tc - config.ambient_c)
            tank_loss = config.tank_loss_w_k * (tt - config.ambient_c)
            transfer = flow_conductance * (tc - tt) if active else 0.0
            return np.array([
                (absorbed - collector_loss - transfer) / cc,
                (transfer - tank_loss) / ct,
                incident, absorbed, collector_loss, tank_loss, transfer,
                config.pump_power_w if active else 0.0,
            ])

        guards = _domain_events(config)
        can_switch = config.pump_mode == "differential" and config.mass_flow_kg_s > 0
        if can_switch:
            threshold = config.pump_off_delta_k if active else config.pump_on_delta_k

            def switch(t, state):
                return state[0] - state[1] - threshold

            switch.terminal = True
            switch.direction = -1 if active else 1
            guards.append(switch)

        solution = solve_ivp(
            rhs, (now, _next_forcing_boundary(now, config)), y, method="DOP853",
            rtol=config.rtol, atol=config.atol, max_step=config.max_step_s,
            dense_output=True, events=guards,
        )
        evaluations += solution.nfev
        if not solution.success:
            raise RuntimeError(f"Integration failed at {solution.t[-1]:.6g} s: {solution.message}")
        end = float(solution.t[-1])
        y = solution.y[:, -1].copy()
        for index, hits in enumerate(solution.t_events[:4]):
            if len(hits):
                component = "collector" if index < 2 else "tank"
                bound = config.max_temperature_c if index % 2 else config.min_temperature_c
                raise ModelDomainError(
                    f"The {component} reached the {bound:g} C model limit at {end / 3600:.6f} h. "
                    "This single-phase model does not simulate freezing or boiling; "
                    "reduce the heat input or revise the scenario. No temperature was clamped."
                )
        if end <= now:
            raise RuntimeError("Integration made no progress; check pump thresholds and numerical settings")
        segments.append((now, end, solution.sol))
        if active:
            runtime_s += end - now
        now = end
        if can_switch and len(solution.t_events[-1]):
            pump_on = not pump_on
            events.append(_event_record(now, y, pump_on))
        if len(segments) > 10_000:
            raise RuntimeError("Too many integration segments; shorten the duration or widen the hysteresis band")

    time = np.append(np.arange(0, config.duration_s, config.output_step_s), config.duration_s)
    values = np.full((8, len(time)), np.nan)
    for start, end, interpolator in segments:
        sample_indices = np.flatnonzero((time >= start) & (time <= end))
        if len(sample_indices):
            values[:, sample_indices] = interpolator(time[sample_indices])
    # Include the final state directly rather than relying on interpolation.
    values[:, -1] = y
    if not np.all(np.isfinite(values)):
        raise RuntimeError("Simulation produced nonfinite output")
    event_times = np.array([event["time_s"] for event in events])
    event_states = np.array([event["pump_on"] for event in events], dtype=bool)
    pump = event_states[np.searchsorted(event_times, time, side="right") - 1]
    tc, tt = values[:2]
    radiation = np.array([irradiance(t, config) for t in time])
    stored = cc * (tc - config.initial_collector_c) + ct * (tt - config.initial_tank_c)
    tank_stored = ct * (tt - config.initial_tank_c)
    residual = stored - (values[3] - values[4] - values[5])
    series = {
        "time_s": time, "collector_c": tc, "tank_c": tt, "pump_on": pump,
        "irradiance_w_m2": radiation,
        "solar_absorbed_w": config.optical_efficiency * config.collector_area_m2 * radiation,
        "collector_loss_w": collector_ua * (tc - config.ambient_c),
        "tank_loss_w": config.tank_loss_w_k * (tt - config.ambient_c),
        "transfer_w": pump * flow_conductance * (tc - tt),
        "incident_energy_j": values[2], "absorbed_energy_j": values[3],
        "collector_loss_energy_j": values[4], "tank_loss_energy_j": values[5],
        "transfer_energy_j": values[6], "pump_electric_energy_j": values[7],
        "stored_energy_change_j": stored, "tank_energy_change_j": tank_stored,
        "balance_residual_j": residual,
    }
    energy_scale = max(
        float(np.max(np.abs(values[3]))),
        float(np.max(np.abs(values[4]) + np.abs(values[5]))),
        float(np.max(np.abs(stored))), 1.0,
    )
    summary = {
        "duration_hours": config.duration_s / 3600,
        "final_collector_c": float(tc[-1]), "final_tank_c": float(tt[-1]),
        "peak_collector_c": float(np.max(tc)), "peak_tank_c": float(np.max(tt)),
        "incident_solar_kwh": float(values[2, -1] / 3.6e6),
        "absorbed_solar_kwh": float(values[3, -1] / 3.6e6),
        "collector_loss_kwh": float(values[4, -1] / 3.6e6),
        "tank_loss_kwh": float(values[5, -1] / 3.6e6),
        "net_heat_to_tank_kwh": float(values[6, -1] / 3.6e6),
        "stored_energy_change_kwh": float(stored[-1] / 3.6e6),
        "tank_energy_change_kwh": float(tank_stored[-1] / 3.6e6),
        "pump_electricity_kwh": float(values[7, -1] / 3.6e6),
        "pump_runtime_hours": runtime_s / 3600,
        "pump_starts": sum(1 for event in events if event["pump_on"]),
        "max_balance_residual_j": float(np.max(np.abs(residual))),
        "relative_balance_error": float(np.max(np.abs(residual)) / energy_scale),
        "solver_evaluations": evaluations,
    }
    return SimulationResult(config, series, summary, events)
