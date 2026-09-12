"""Offline animated heat-transfer viewer payload and HTML exporter.

The interactive part of the viewer is deliberately kept in the checked-in
``templates/heat_flow.html.in`` fragment.  This module supplies only compact,
validated data and the small standalone document shell needed to open it from
the filesystem.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .model import irradiance


_TEMPLATE_PATH = Path(__file__).parent / "templates" / "heat_flow.html.in"
_SCRIPT_PATH = Path(__file__).parent / "templates" / "playback.js"
_PLACEHOLDER = "__SOLAR_PAYLOAD__"
_SCRIPT_PLACEHOLDER = "__SOLAR_SCRIPT__"


def _json_ready(value: Any) -> Any:
    """Convert values to strict JSON data, rejecting non-finite numbers."""

    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_json_ready(item) for item in value.tolist()]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("animation payload cannot contain NaN or infinity")
        return number
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _rounded(value: Any, digits: int) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("animation payload cannot contain NaN or infinity")
    rounded = round(number, digits)
    # Avoid serialising a surprising negative zero in the viewer labels.
    return 0.0 if rounded == 0 else rounded


def _config_dict(config: Any) -> dict[str, Any]:
    if config is None:
        raise ValueError("each simulation result must provide config")
    if is_dataclass(config):
        raw = asdict(config)
    elif hasattr(config, "to_dict"):
        raw = config.to_dict()
    elif isinstance(config, Mapping):
        raw = dict(config)
    else:
        raw = vars(config)
    result = _json_ready(raw)
    if not isinstance(result, dict):
        raise ValueError("simulation config must serialise to an object")
    return result


def _safe_id(name: str, index: int, used: set[str]) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-_") or f"scenario-{index + 1}"
    if not re.match(r"^[A-Za-z][A-Za-z0-9_-]*$", candidate):
        candidate = f"scenario-{index + 1}-{candidate}"
    base = candidate
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _series_arrays(result: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw = getattr(result, "series", None)
    if not isinstance(raw, Mapping):
        raise ValueError("each simulation result must provide a series mapping")
    keys = ("time_s", "collector_c", "tank_c", "irradiance_w_m2")
    missing = [key for key in keys if key not in raw]
    if missing:
        raise ValueError(f"simulation series is missing keys: {missing}")
    arrays = tuple(np.asarray(raw[key], dtype=float) for key in keys)
    if any(array.ndim != 1 for array in arrays) or len(arrays[0]) == 0:
        raise ValueError("simulation series channels must be non-empty one-dimensional arrays")
    if any(len(array) != len(arrays[0]) for array in arrays[1:]):
        raise ValueError("simulation series channels must have equal lengths")
    if np.any(~np.isfinite(arrays[0])) or np.any(np.diff(arrays[0]) < 0):
        raise ValueError("simulation time series must be finite and sorted")
    for array in arrays[1:]:
        if np.any(~np.isfinite(array)):
            raise ValueError("animation payload cannot contain NaN or infinity")
    return arrays


def _merged_times(output_times: np.ndarray, events: list[Mapping[str, Any]]) -> list[float]:
    event_times: list[float] = []
    for event in events:
        if "time_s" not in event:
            raise ValueError("pump event is missing time_s")
        time = float(event["time_s"])
        if not math.isfinite(time):
            raise ValueError("pump event time must be finite")
        if time < float(output_times[0]) - 1e-8 or time > float(output_times[-1]) + 1e-8:
            raise ValueError("pump event time must lie within the sampled simulation interval")
        event_times.append(time)
    return sorted(set(float(time) for time in output_times) | set(event_times))


def _sample_rows(result: Any) -> list[list[float]]:
    output_time, collector, tank, _output_irradiance = _series_arrays(result)
    config = getattr(result, "config", None)
    events_raw = getattr(result, "events", []) or []
    if not isinstance(events_raw, list):
        raise ValueError("simulation events must be a list")
    events = [event for event in events_raw if isinstance(event, Mapping)]
    if len(events) != len(events_raw):
        raise ValueError("each pump event must be an object")
    times = _merged_times(output_time, events)
    event_by_time = {float(event["time_s"]): event for event in events}

    rows: list[list[float]] = []
    for time in times:
        event = event_by_time.get(time)
        if event is not None:
            if "collector_c" not in event or "tank_c" not in event:
                raise ValueError("pump event must provide collector_c and tank_c")
            collector_value = float(event["collector_c"])
            tank_value = float(event["tank_c"])
        else:
            collector_value = float(np.interp(time, output_time, collector))
            tank_value = float(np.interp(time, output_time, tank))
        # Irradiance is evaluated from the same model function used by the
        # solver, rather than interpolating a charting-only quantity.
        radiation = float(irradiance(time, config))
        rows.append(
            [
                time,
                collector_value if event is not None else _rounded(collector_value, 6),
                tank_value if event is not None else _rounded(tank_value, 6),
                _rounded(radiation, 3),
            ]
        )
    return rows


def build_payload(results: dict[str, Any]) -> dict[str, Any]:
    """Build the compact JSON-ready payload consumed by the HTML viewer."""

    if not isinstance(results, Mapping) or not results:
        raise ValueError("results must be a non-empty mapping")
    scenarios: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, (name, result) in enumerate(results.items()):
        display_name = {
            "clear_differential": "Clear day · automatic pump",
            "clear_continuous": "Clear day · continuous pump",
            "cloudy_differential": "Cloudy day · automatic pump",
            "cloudy_continuous": "Cloudy day · continuous pump",
        }.get(str(name), str(name))
        scenario_id = _safe_id(str(name), index, used_ids)
        events = getattr(result, "events", []) or []
        if not isinstance(events, list):
            raise ValueError("simulation events must be a list")
        scenarios.append(
            {
                "id": scenario_id,
                "name": display_name,
                "config": _config_dict(getattr(result, "config", None)),
                "samples": _sample_rows(result),
                "events": _json_ready(events),
            }
        )
    payload = {"scenarios": scenarios, "initialScenario": scenarios[0]["id"]}
    # Run the same strict conversion used by the HTML serialiser before
    # returning, so callers never receive data that cannot be embedded.
    return _json_ready(payload)


def _payload_json(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    # The payload is embedded in an inline script.  Escaping ``<`` prevents a
    # scenario name or config string containing </script> from terminating it.
    return serialized.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_fragment(results: dict[str, Any]) -> str:
    """Render the root-owned HTML fragment with an inline safe payload."""

    if not _TEMPLATE_PATH.is_file():
        raise FileNotFoundError(f"animation template not found: {_TEMPLATE_PATH}")
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    if template.count(_PLACEHOLDER) != 1:
        raise ValueError(f"animation template must contain exactly one {_PLACEHOLDER} placeholder")
    rendered = template.replace(_PLACEHOLDER, _payload_json(build_payload(results)))
    if _SCRIPT_PLACEHOLDER in rendered:
        if not _SCRIPT_PATH.is_file():
            raise FileNotFoundError(f"animation playback script not found: {_SCRIPT_PATH}")
        script = _SCRIPT_PATH.read_text(encoding="utf-8")
        if script.count(_SCRIPT_PLACEHOLDER):
            raise ValueError(f"playback script must not contain {_SCRIPT_PLACEHOLDER}")
        rendered = rendered.replace(_SCRIPT_PLACEHOLDER, script)
    return rendered


_SHELL_CSS = """
:root{color-scheme:light dark;--blue:#1565a8;--orange:#d18a00;--green:#187c73;--border:#d8e0e7;--foreground:#162536;--background:#f3f7fa;--muted-foreground:#526779;--primary:#1565a8;--primary-foreground:#fff;--font-size-base:16px}
@media(prefers-color-scheme:dark){:root{--blue:#72b7ee;--orange:#f1bf55;--green:#5ec5b5;--border:#3a4b59;--foreground:#edf3f8;--background:#111923;--muted-foreground:#b4c4d0;--primary:#72b7ee;--primary-foreground:#0e1720}}
*,*:before,*:after{box-sizing:border-box}body{margin:0;background:var(--background);color:var(--foreground);font:var(--font-size-base)/1.5 system-ui,-apple-system,Segoe UI,sans-serif}main{max-width:1240px;margin:0 auto;padding:22px}.viz-nav{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:12px}.viz-nav a{color:var(--blue)}
.btn{font:inherit;border:1px solid var(--border);border-radius:7px;background:var(--background);color:var(--foreground);padding:.45rem .7rem;cursor:pointer}.btn:hover{border-color:var(--primary)}.btn-primary{background:var(--primary);color:var(--primary-foreground)}.form-select{font:inherit;max-width:100%;border:1px solid var(--border);border-radius:6px;background:var(--background);color:var(--foreground);padding:.42rem}.form-range{accent-color:var(--primary);width:100%}.viz-controls,.viz-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:10px 0}.form-label{display:flex;gap:8px;flex-wrap:wrap;align-items:center;font-weight:500;max-width:100%}.text-small{font-size:.88rem;color:var(--muted-foreground)}.tabular-nums{font-variant-numeric:tabular-nums}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}@media(pointer:coarse){.btn,.form-select{min-height:44px}}
""".strip()


def write_animation(results: dict[str, Any], output_dir: str | Path) -> None:
    """Write a standalone animated viewer at ``output_dir/index.html``."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    fragment = render_fragment(results)
    document = (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Solar thermal heat flow</title><style>"
        + _SHELL_CSS
        + "</style></head><body><main>"
        "<nav class=\"viz-nav\" aria-label=\"Report navigation\">"
        "<a href=\"report.html\">Graphs and data</a>"
        "<a href=\"verification.json\">Verification</a>"
        "</nav>"
        + fragment
        + "</main></body></html>\n"
    )
    (output_path / "index.html").write_text(document, encoding="utf-8")
