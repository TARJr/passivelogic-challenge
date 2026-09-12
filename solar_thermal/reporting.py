"""Static CSV, JSON, PNG, and offline HTML reporting for simulations.

The reporting layer deliberately has no knowledge of the numerical solver.  It
only consumes the public ``SimulationResult``, which makes the generated
artifacts useful for both command line examples and independent post-processing.
"""

from __future__ import annotations

import csv
import html
import json
import math
import os
import re
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Mapping

# Matplotlib may build a font cache on first import.  Keep that cache in a
# writable temporary location so report generation remains usable in a locked
# down checkout or a read-only home directory.
_MPL_CACHE = Path(tempfile.gettempdir()) / "solar-thermal-mplconfig"
try:
    _MPL_CACHE.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))
except OSError:
    pass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .units import celsius_to_fahrenheit, liters_to_us_gallons, mass_flow_to_us_gpm


_SERIES_ORDER = (
    "time_s",
    "collector_c",
    "tank_c",
    "pump_on",
    "irradiance_w_m2",
    "solar_absorbed_w",
    "collector_loss_w",
    "tank_loss_w",
    "transfer_w",
    "incident_energy_j",
    "absorbed_energy_j",
    "collector_loss_energy_j",
    "tank_loss_energy_j",
    "transfer_energy_j",
    "pump_electric_energy_j",
    "stored_energy_change_j",
    "tank_energy_change_j",
    "balance_residual_j",
)


def _jsonable(value: Any) -> Any:
    """Convert dataclass/numpy values into strict JSON-compatible values."""

    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if value is None or isinstance(value, (str, bytes)):
        return value.decode("utf-8", "replace") if isinstance(value, bytes) else value
    return str(value)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(_jsonable(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _safe_label(label: Any) -> str:
    """Validate a readable, non-traversing directory component from a label."""

    text = str(label)
    if not text or text in {".", ".."} or text.startswith("."):
        raise ValueError(f"unsafe scenario label: {label!r}")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", text) is None:
        raise ValueError(
            f"unsafe scenario label {label!r}; use letters, digits, underscore, dot, or hyphen"
        )
    return text


def _safe_labels(labels: list[Any]) -> dict[Any, str]:
    """Validate labels and reject path collisions."""

    used: set[str] = set()
    result: dict[Any, str] = {}
    for label in labels:
        base = _safe_label(label)
        if base in used:
            raise ValueError(f"scenario labels collide at directory name {base!r}")
        used.add(base)
        result[label] = base
    return result


def _series(result: Any) -> dict[str, np.ndarray]:
    raw = getattr(result, "series", None)
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError("result.series must be a non-empty mapping")
    converted: dict[str, np.ndarray] = {}
    length: int | None = None
    for key, values in raw.items():
        array = np.asarray(values)
        if array.ndim != 1:
            raise ValueError(f"series {key!r} must be one-dimensional")
        if length is None:
            length = len(array)
        elif len(array) != length:
            raise ValueError("all result series must have equal length")
        converted[str(key)] = array
    if length is None or length == 0:
        raise ValueError("result.series must contain at least one sample")
    return converted


def _plot_result(result: Any, path: Path, label: str) -> None:
    data = _series(result)
    required = {"time_s", "collector_c", "tank_c", "irradiance_w_m2", "pump_on"}
    missing = required.difference(data)
    if missing:
        raise ValueError(f"result.series is missing required keys: {sorted(missing)}")

    time_h = np.asarray(data["time_s"], dtype=float) / 3600.0
    collector = np.asarray(data["collector_c"], dtype=float)
    tank = np.asarray(data["tank_c"], dtype=float)
    ambient = float(getattr(getattr(result, "config", None), "ambient_c", 0.0))
    irradiance = np.asarray(data["irradiance_w_m2"], dtype=float)
    pump = np.asarray(data["pump_on"], dtype=bool)

    fig, axes = plt.subplots(2, 3, figsize=(15, 9.2), constrained_layout=True)
    fig.suptitle(f"Solar thermal simulation — {label}", fontsize=16, fontweight="bold")
    ax = axes[0, 0]
    ax.plot(time_h, celsius_to_fahrenheit(collector), color="#c45c18", label="Collector")
    ax.plot(time_h, celsius_to_fahrenheit(tank), color="#1565a8", label="Tank")
    ax.axhline(celsius_to_fahrenheit(ambient), color="#5e6b75", linestyle="--", linewidth=1, label="Ambient")
    ax.set_title("Temperatures")
    ax.set_xlabel("Time (h)")
    ax.set_ylabel("Temperature (°F)")
    ax.grid(alpha=0.25)
    ax.legend(loc="best", frameon=False)

    ax = axes[0, 1]
    ax.plot(time_h, irradiance, color="#e09b16", linewidth=1.7, label="Incident sunlight")
    ax.set_title("Sunlight and pump state")
    ax.set_xlabel("Time (h)")
    ax.set_ylabel("Irradiance (W/m²)")
    ax.grid(alpha=0.25)
    pump_axis = ax.twinx()
    pump_axis.step(time_h, pump.astype(float), where="post", color="#176b58", linewidth=1.4, label="Pump on")
    pump_axis.set_ylim(-0.05, 1.15)
    pump_axis.set_yticks((0, 1), labels=("Off", "On"))
    pump_axis.set_ylabel("Pump")
    handles, labels = ax.get_legend_handles_labels()
    h2, l2 = pump_axis.get_legend_handles_labels()
    ax.legend(handles + h2, labels + l2, loc="best", frameon=False)

    ax = axes[0, 2]
    flow_specs = (
        ("solar_absorbed_w", "Solar absorbed (+ into collector)", "#d18a00"),
        ("collector_loss_w", "Collector loss (+ to ambient)", "#b54d4d"),
        ("tank_loss_w", "Tank loss (+ to ambient)", "#7b5ea7"),
        ("transfer_w", "Transfer (+ collector → tank)", "#187c73"),
    )
    plotted = []
    for key, name, color in flow_specs:
        if key in data:
            line, = ax.plot(time_h, np.asarray(data[key], dtype=float), label=name, color=color)
            plotted.append(line)
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_title("Signed heat flow")
    ax.set_xlabel("Time (h)")
    ax.set_ylabel("Heat flow (W; signed, direction in legend)")
    ax.grid(alpha=0.25)
    if plotted:
        ax.legend(loc="best", frameon=False)

    ax = axes[1, 0]
    energy_specs = (
        ("incident_energy_j", "Incident", "#c78c00"),
        ("absorbed_energy_j", "Absorbed (+ into collector)", "#e0aa26"),
        ("collector_loss_energy_j", "Collector loss (+ to ambient)", "#b54d4d"),
        ("tank_loss_energy_j", "Tank loss (+ to ambient)", "#7b5ea7"),
        ("transfer_energy_j", "Transfer (+ collector → tank)", "#187c73"),
    )
    plotted = []
    for key, name, color in energy_specs:
        if key in data:
            line, = ax.plot(time_h, np.asarray(data[key], dtype=float) / 3.6e6, label=name, color=color)
            plotted.append(line)
    ax.set_title("Accumulated thermal energy")
    ax.set_xlabel("Time (h)")
    ax.set_ylabel("Energy (kWh; signed where applicable)")
    ax.grid(alpha=0.25)
    if plotted:
        ax.legend(loc="best", frameon=False, fontsize=8)
    if "pump_electric_energy_j" in data:
        pump_axis = ax.twinx()
        pump_axis.plot(
            time_h,
            np.asarray(data["pump_electric_energy_j"], dtype=float) / 3.6e6,
            color="#176b58",
            linestyle="--",
            linewidth=1.6,
            label="Pump electricity",
        )
        pump_axis.set_ylabel("Pump electricity (kWh)", color="#176b58")
        pump_axis.tick_params(axis="y", colors="#176b58")

    ax = axes[1, 1]
    balance_specs = (
        ("stored_energy_change_j", "Stored energy change", "#1565a8"),
        ("tank_energy_change_j", "Tank energy change", "#187c73"),
        ("balance_residual_j", "Balance residual", "#b54d4d"),
    )
    plotted = []
    for key, name, color in balance_specs:
        if key in data:
            line, = ax.plot(time_h, np.asarray(data[key], dtype=float) / 3.6e6, label=name, color=color)
            plotted.append(line)
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_title("Stored energy and accounting residual")
    ax.set_xlabel("Time (h)")
    ax.set_ylabel("Energy change (kWh)")
    ax.grid(alpha=0.25)
    if plotted:
        ax.legend(loc="best", frameon=False, fontsize=8)

    ax = axes[1, 2]
    summary = getattr(result, "summary", {}) or {}
    config = getattr(result, "config", None)
    lines = [
        "Units and signs",
        "• Solar absorbed: + into collector.",
        "• Losses: + from component to ambient.",
        "• Transfer: + collector → tank.",
        "• Negative values mean the reverse direction.",
        "• Pump electricity is electrical energy, separate from heat.",
        "",
        "Reported results",
    ]
    for key, name, unit in (
        ("final_collector_c", "Final collector", "°F"),
        ("final_tank_c", "Final tank", "°F"),
        ("stored_energy_change_kwh", "Stored energy change", "kWh"),
        ("pump_electricity_kwh", "Pump electricity", "kWh"),
        ("pump_runtime_hours", "Pump runtime", "h"),
    ):
        if key in summary:
            try:
                number = float(summary[key])
                if key in {"final_collector_c", "final_tank_c"}:
                    number = float(celsius_to_fahrenheit(number))
                lines.append(f"{name}: {number:.3g} {unit}")
            except (TypeError, ValueError):
                lines.append(f"{name}: {summary[key]} {unit}")
    if config is not None:
        lines += [
            "",
            "Configuration",
            f"Profile: {getattr(config, 'irradiance_profile', '—')}",
            f"Pump: {getattr(config, 'pump_mode', '—')}",
            f"Ambient: {float(celsius_to_fahrenheit(getattr(config, 'ambient_c', 0.0))):.3g} °F",
            f"Tank capacity: {float(liters_to_us_gallons(getattr(config, 'tank_volume_l', 0.0))):.3g} US gal",
            f"Loop flow: {float(mass_flow_to_us_gpm(getattr(config, 'mass_flow_kg_s', 0.0), getattr(config, 'water_density_kg_m3', 1000.0))):.3g} US gpm",
            "Clock: daily profile starts at midnight",
            "Tank: one well-mixed node",
        ]
    ax.axis("off")
    ax.text(0.02, 0.98, "\n".join(lines), va="top", ha="left", fontsize=10, linespacing=1.45)

    fig.savefig(path, dpi=160, format="png", facecolor="white")
    plt.close(fig)


def _write_csv(result: Any, path: Path) -> None:
    data = _series(result)
    keys = [key for key in _SERIES_ORDER if key in data]
    keys += sorted(key for key in data if key not in keys)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(keys)
        for index in range(len(next(iter(data.values())))):
            row = []
            for key in keys:
                value = data[key][index]
                if isinstance(value, (bool, np.bool_)):
                    row.append("1" if bool(value) else "0")
                elif isinstance(value, (np.integer, int)):
                    row.append(str(int(value)))
                else:
                    row.append(repr(float(value)))
            writer.writerow(row)


def write_result(result: Any, output_dir: str | Path, label: str) -> None:
    """Write one simulation's machine-readable data and static plot."""

    run_dir = Path(output_dir) / _safe_label(label)
    run_dir.mkdir(parents=True, exist_ok=True)
    config = getattr(result, "config", None)
    _write_csv(result, run_dir / "results.csv")
    _write_json(run_dir / "config.json", config)
    _write_json(run_dir / "summary.json", getattr(result, "summary", {}))
    _write_json(run_dir / "pump_events.json", getattr(result, "events", []))
    _plot_result(result, run_dir / "plots.png", str(label))


def _plot_comparison(results: list[tuple[str, Any]], path: Path) -> None:
    labels = [label for label, _ in results]
    summaries = [getattr(result, "summary", {}) or {} for _, result in results]
    positions = np.arange(len(results))
    width = 0.36 if len(results) <= 8 else min(0.8 / 2, 0.36)
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    fig.suptitle("Solar thermal scenario comparison", fontsize=16, fontweight="bold")

    ax = axes[0, 0]
    ax.bar(positions - width / 2, [float(celsius_to_fahrenheit(s.get("final_collector_c", np.nan))) for s in summaries], width, label="Collector", color="#c45c18")
    ax.bar(positions + width / 2, [float(celsius_to_fahrenheit(s.get("final_tank_c", np.nan))) for s in summaries], width, label="Tank", color="#1565a8")
    ax.set_title("Final temperatures")
    ax.set_ylabel("Temperature (°F)")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)

    ax = axes[0, 1]
    ax.bar(positions - width / 2, [float(s.get("stored_energy_change_kwh", np.nan)) for s in summaries], width, label="Stored energy", color="#1565a8")
    ax.bar(positions + width / 2, [float(s.get("tank_energy_change_kwh", np.nan)) for s in summaries], width, label="Tank energy", color="#187c73")
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_title("Stored heat")
    ax.set_ylabel("Energy change (kWh)")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)

    ax = axes[1, 0]
    ax.bar(positions, [float(s.get("pump_electricity_kwh", np.nan)) for s in summaries], color="#176b58", label="Electricity")
    ax.set_title("Pump use")
    ax.set_ylabel("Electricity (kWh)")
    ax.grid(axis="y", alpha=0.25)
    runtime_axis = ax.twinx()
    runtime_axis.plot(positions, [float(s.get("pump_runtime_hours", np.nan)) for s in summaries], color="#d18a00", marker="o", label="Runtime")
    runtime_axis.set_ylabel("Runtime (h)", color="#d18a00")
    runtime_axis.tick_params(axis="y", colors="#d18a00")

    ax = axes[1, 1]
    ax.bar(positions - width / 2, [float(s.get("incident_solar_kwh", np.nan)) for s in summaries], width, label="Incident solar", color="#d18a00")
    ax.bar(positions + width / 2, [float(s.get("net_heat_to_tank_kwh", np.nan)) for s in summaries], width, label="Net heat to tank", color="#187c73")
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_title("Solar input and tank delivery")
    ax.set_ylabel("Energy (kWh)")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)

    for ax in axes.flat:
        ax.set_xticks(positions)
        ax.set_xticklabels(labels, rotation=28, ha="right")
    fig.savefig(path, dpi=160, format="png", facecolor="white")
    plt.close(fig)


def _comparison_html(results: list[tuple[str, Any]], output_dir: Path, safe: dict[Any, str]) -> str:
    rows: list[str] = []
    scenario_data: dict[str, Any] = {}
    for label, result in results:
        summary = _jsonable(getattr(result, "summary", {}) or {})
        config = _jsonable(getattr(result, "config", None))
        directory = safe[label]
        scenario_data[str(label)] = {"directory": directory, "summary": summary, "config": config}
        esc_label = html.escape(str(label), quote=True)
        def value(key: str, suffix: str = "", converter=None) -> str:
            raw = summary.get(key)
            if raw is None:
                return "—"
            try:
                number = float(raw)
                if converter is not None:
                    number = float(converter(number))
                return html.escape(f"{number:.4g} {suffix}")
            except (TypeError, ValueError):
                return html.escape(f"{raw} {suffix}")
        rows.append(
            "<tr>"
            f"<th scope=\"row\">{esc_label}</th>"
            f"<td>{value('final_collector_c', '°F', celsius_to_fahrenheit)}</td>"
            f"<td>{value('final_tank_c', '°F', celsius_to_fahrenheit)}</td>"
            f"<td>{value('stored_energy_change_kwh', 'kWh')}</td>"
            f"<td>{value('pump_electricity_kwh', 'kWh')}</td>"
            f"<td>{value('pump_runtime_hours', 'h')}</td>"
            f"<td><a href=\"{html.escape(directory)}/plots.png\">plot</a> · "
            f"<a href=\"{html.escape(directory)}/results.csv\">CSV</a> · "
            f"<a href=\"{html.escape(directory)}/config.json\">config</a> · "
            f"<a href=\"{html.escape(directory)}/summary.json\">summary</a> · "
            f"<a href=\"{html.escape(directory)}/pump_events.json\">events</a></td>"
            "</tr>"
        )
    combined = {"scenarios": scenario_data}
    _write_json(output_dir / "summary.json", combined)
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Solar thermal report</title>
<style>
:root{color-scheme:light;--ink:#162536;--muted:#526779;--blue:#1565a8;--amber:#d18a00;--line:#d8e0e7;--paper:#fff;--wash:#f3f7fa}
*{box-sizing:border-box}body{margin:0;background:var(--wash);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 22px 50px}h1{margin:.15em 0 .25em;font-size:clamp(1.8rem,3vw,2.7rem)}h2{margin-top:2em;font-size:1.25rem;color:var(--blue)}p{max-width:80ch;color:var(--muted)}
.card{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:16px 18px;box-shadow:0 3px 14px #17344d0d;margin:18px 0}img{display:block;max-width:100%;height:auto;border:1px solid var(--line);border-radius:8px}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:850px}th,td{text-align:right;padding:10px 9px;border-bottom:1px solid var(--line);white-space:nowrap}th:first-child,td:first-child{text-align:left}thead th{color:var(--blue);font-size:.9rem}tbody th{font-weight:650}tbody tr:nth-child(even){background:#f8fbfd}a{color:#075d9c;text-decoration-thickness:1px;text-underline-offset:2px}a:focus-visible{outline:3px solid #f0b429;outline-offset:2px}.note{font-size:.93rem}
</style></head><body><main>
<h1>Solar thermal simulation report</h1>
<p><a href="index.html">Open animated heat transfer simulation</a></p>
<p>Static, offline results generated from the simulation. All scenario links below point to local files; no server, JavaScript, or external assets are required. The defaults are illustrative and are not calibrated manufacturer data. The tank is represented as one well-mixed node, and the repeating daily irradiance clock starts at midnight.</p>
<p class="note"><a href="verification.json">Verification details</a> · <a href="environment.json">Environment manifest</a> · <a href="summary.json">Combined summary JSON</a></p>
<div class="card"><a href="comparison.png"><img src="comparison.png" alt="Comparison charts for all solar thermal scenarios"></a></div>
<h2>Scenario comparison</h2>
<div class="card table-wrap"><table><thead><tr><th scope="col">Scenario</th><th scope="col">Final collector (°F)</th><th scope="col">Final tank (°F)</th><th scope="col">Stored energy</th><th scope="col">Pump electricity</th><th scope="col">Pump runtime</th><th scope="col">Files</th></tr></thead><tbody>""" + "".join(rows) + """</tbody></table></div>
<div class="card note"><strong>Reading the units and signs.</strong> Displayed temperatures are in °F, tank capacity in US gallons, and loop flow in US gpm. Irradiance remains W/m², thermal heat flow remains W, and accumulated energy remains kWh. Solar absorption is positive into the collector. Collector and tank losses are positive to ambient, and transfer is positive from collector to tank; negative values mean the reverse direction. Pump electricity is tracked separately and is not added to thermal energy. Machine-readable CSV/JSON/config files retain the model's SI units, including °C, litres, and kg/s.</div>
<h2>Scenario files</h2>
<p>Each plot is a six-panel view of temperatures, sunlight and pump state, signed heat flow, accumulated energy, stored-energy accounting, and key parameters/results. The files are also suitable for independent analysis.</p>
</main></body></html>
"""


def write_comparison(results: dict[str, Any], output_dir: str | Path) -> None:
    """Write per-scenario artefacts, comparison charts, and an offline index."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    items = list(results.items())
    safe = _safe_labels([label for label, _ in items])
    _plot_comparison(items, output_path / "comparison.png")
    document = _comparison_html(items, output_path, safe)
    (output_path / "report.html").write_text(document, encoding="utf-8")
