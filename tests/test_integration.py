"""Exercise exported artifacts, CLI failure behavior and verification itself."""

import csv
import json
import math
import subprocess
import sys
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pytest

from solar_thermal.model import SimulationConfig, simulate
from solar_thermal.verification import verify_result


ROOT = Path(__file__).resolve().parents[1]


class LocalLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("src", "href") and value and not value.startswith(("#", "http:", "https:")):
                self.paths.append(value)


def test_cli_exports_complete_reproducible_offline_report(tmp_path):
    config_path = tmp_path / "scenario.json"
    config_path.write_text(json.dumps({
        "irradiance_profile": "constant", "constant_irradiance_w_m2": 400,
        "duration_s": 2400, "output_step_s": 73,
    }))
    output = tmp_path / "report"
    command = subprocess.run(
        [sys.executable, str(ROOT / "run.py"), "--config", str(config_path), "--output", str(output)],
        text=True, capture_output=True, cwd=tmp_path,
    )
    assert command.returncode == 0, command.stderr
    assert "convergence PASS" in command.stdout
    for filename in ("index.html", "report.html", "comparison.png", "summary.json", "verification.json", "environment.json"):
        assert (output / filename).stat().st_size > 0
    for filename in ("results.csv", "plots.png", "config.json", "summary.json", "pump_events.json"):
        assert (output / "custom" / filename).stat().st_size > 0
    parser = LocalLinks()
    parser.feed((output / "index.html").read_text())
    parser.feed((output / "report.html").read_text())
    assert parser.paths
    assert all((output / link).is_file() for link in parser.paths)
    saved_config = json.loads((output / "custom" / "config.json").read_text())
    saved_summary = json.loads((output / "custom" / "summary.json").read_text())
    assert saved_config["duration_s"] == 2400
    with (output / "custom" / "results.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert float(rows[0]["time_s"]) == 0
    assert float(rows[-1]["time_s"]) == 2400
    assert float(rows[-1]["tank_c"]) == saved_summary["final_tank_c"]
    assert set(row["pump_on"] for row in rows) <= {"0", "1"}
    assert json.loads((output / "verification.json").read_text())["custom"]["passed"]


def test_invalid_cli_config_fails_without_replacing_existing_report(tmp_path):
    config_path = tmp_path / "bad.json"
    config_path.write_text('{"tank_volume_l": -200}')
    output = tmp_path / "report"
    output.mkdir()
    previous = output / "index.html"
    previous.write_text("Previous report must survive an invalid run")
    command = subprocess.run(
        [sys.executable, str(ROOT / "run.py"), "--config", str(config_path), "--output", str(output)],
        text=True, capture_output=True,
    )
    assert command.returncode != 0
    assert "tank_volume_l" in command.stderr
    assert "Traceback" not in command.stderr
    assert previous.read_text() == "Previous report must survive an invalid run"


def test_verification_detects_temperature_error_even_with_small_balance_residual():
    result = simulate(SimulationConfig(
        irradiance_profile="constant", constant_irradiance_w_m2=300,
        duration_s=1200,
    ))
    assert verify_result(result)["passed"]
    result.series["tank_c"] = result.series["tank_c"].copy() + 0.1
    check = verify_result(result)
    assert not check["passed"]
    assert check["max_temperature_difference_c"] > 0.09


def test_reporting_interval_does_not_change_control_events_or_final_state():
    config = SimulationConfig(irradiance_profile="cloudy")
    fine = simulate(replace(config, output_step_s=17))
    coarse = simulate(replace(config, output_step_s=5000))
    assert fine.events == coarse.events
    assert fine.summary["final_tank_c"] == coarse.summary["final_tank_c"]
    for result in (fine, coarse):
        times = result.series["time_s"]
        assert times[0] == 0 and times[-1] == config.duration_s
        assert np.all(np.diff(times) > 0)


def test_solver_cannot_step_over_an_entire_short_daylight_window():
    config = SimulationConfig(sunrise_hour=12, sunset_hour=12.0001, max_step_s=3600)
    result = simulate(config)
    expected_j = (
        2 / math.pi * config.collector_area_m2 * config.peak_irradiance_w_m2
        * (config.sunset_hour - config.sunrise_hour) * 3600
    )
    assert result.series["incident_energy_j"][-1] == pytest.approx(expected_j, rel=1e-7)
