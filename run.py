#!/usr/bin/env python3
"""Run solar thermal scenarios and produce an offline, verified results report."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Run one JSON configuration instead of the four examples")
    parser.add_argument("--output", type=Path, default=Path("results"), help="Output directory (default: results)")
    args = parser.parse_args()
    try:
        from solar_thermal.model import load_config
        from solar_thermal.reporting import write_result, write_comparison
        from solar_thermal.model import simulate
        from solar_thermal.verification import verify_result
        from solar_thermal.animation import write_animation
        from solar_thermal.units import celsius_to_fahrenheit
    except ImportError as error:
        print(f"Missing dependency: {error}. Activate .venv and run python -m pip install -r requirements.txt", file=sys.stderr)
        return 2

    example_dir = Path(__file__).resolve().parent / "examples"
    paths = [args.config] if args.config else [
        example_dir / "clear_day.json", example_dir / "clear_continuous.json",
        example_dir / "cloudy_day.json", example_dir / "cloudy_continuous.json",
    ]
    labels = ["custom"] if args.config else [
        "clear_differential", "clear_continuous", "cloudy_differential", "cloudy_continuous",
    ]
    try:
        # Complete and verify all calculations before replacing any report files.
        results = {}
        verification = {}
        for label, path in zip(labels, paths):
            result = simulate(load_config(path))
            check = verify_result(result)
            if not check["passed"]:
                raise ValueError(f"{label} failed numerical verification: {json.dumps(check)}")
            results[label] = result
            verification[label] = check
            s = result.summary
            print(
                f"{label}: tank {celsius_to_fahrenheit(s['final_tank_c']):.2f} F, "
                f"stored {s['tank_energy_change_kwh']:.3f} kWh, "
                f"pump {s['pump_runtime_hours']:.2f} h; convergence PASS",
                flush=True,
            )

        args.output.mkdir(parents=True, exist_ok=True)
        for label, result in results.items():
            write_result(result, args.output, label)
        (args.output / "verification.json").write_text(json.dumps(verification, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        manifest = {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": {package: importlib.metadata.version(package) for package in ("numpy", "scipy", "matplotlib")},
            "scenario_files": {label: str(path.name) for label, path in zip(labels, paths)},
            "verification": "Each baseline compared with half max_step_s and 10x tighter tolerances; see verification.json",
        }
        (args.output / "environment.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        write_comparison(results, args.output)
        write_animation(results, args.output)
        print(f"Report: {(args.output / 'index.html').resolve()}")
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Simulation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
