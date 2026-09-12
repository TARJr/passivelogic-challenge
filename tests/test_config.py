"""Contract tests for configuration and the irradiance helper."""

import json
from dataclasses import FrozenInstanceError, replace

import numpy as np
import pytest

from solar_thermal.model import SimulationConfig, config_from_dict, irradiance, load_config


def test_defaults_are_frozen_and_have_documented_values():
    config = SimulationConfig()

    assert config.collector_area_m2 == 4.0
    assert config.tank_volume_l == 200.0
    assert config.pump_mode == "differential"
    assert config.duration_s == 86400.0
    with pytest.raises(FrozenInstanceError):
        config.duration_s = 1.0


def test_replace_produces_an_independent_valid_configuration():
    original = SimulationConfig()
    modified = replace(original, pump_mode="off", duration_s=10.0)

    assert original.pump_mode == "differential"
    assert modified.pump_mode == "off"
    assert modified.duration_s == 10.0
    modified.validate()


def test_config_from_dict_and_load_config_round_trip(tmp_path):
    values = {
        "pump_mode": "continuous",
        "irradiance_profile": "constant",
        "constant_irradiance_w_m2": 325.0,
        "duration_s": 123.0,
    }
    config = config_from_dict(values)
    assert config.pump_mode == "continuous"
    assert config.constant_irradiance_w_m2 == 325.0
    assert config.duration_s == 123.0

    path = tmp_path / "config.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    loaded = load_config(path)
    assert loaded == config


def test_config_from_dict_rejects_unknown_keys():
    with pytest.raises((TypeError, ValueError)):
        config_from_dict({"this_is_not_a_config_field": 1})


@pytest.mark.parametrize(
    "changes",
    [
        {"collector_area_m2": -1.0},
        {"optical_efficiency": 1.01},
        {"collector_loss_w_m2k": float("nan")},
        {"tank_volume_l": 0.0},
        {"water_cp_j_kgk": "4180"},
        {"pump_mode": "intermittent"},
        {"irradiance_profile": "night"},
        {"mass_flow_kg_s": -0.01},
        {"pump_on_delta_k": 2.0, "pump_off_delta_k": 2.0},
        {"pump_on_delta_k": 1.0, "pump_off_delta_k": 2.0},
        {"initial_tank_c": 96.0},
        {"duration_s": float("inf")},
        {"output_step_s": 0.0},
        {"max_step_s": -1.0},
        {"rtol": 0.0},
        {"atol": -1e-8},
    ],
)
def test_validate_rejects_invalid_values(changes):
    with pytest.raises(ValueError):
        config = replace(SimulationConfig(), **changes)
        config.validate()


def test_validate_rejects_bad_temperature_bounds_and_initial_state():
    invalid_changes = [
        {"min_temperature_c": 30.0, "initial_collector_c": 20.0},
        {"max_temperature_c": 20.0, "initial_tank_c": 20.1},
        {"min_temperature_c": 0.0, "max_temperature_c": 0.0},
    ]
    for changes in invalid_changes:
        with pytest.raises(ValueError):
            config = replace(SimulationConfig(), **changes)
            config.validate()


def test_irradiance_clear_profile_is_zero_at_night_and_peaks_at_noon():
    config = replace(
        SimulationConfig(),
        irradiance_profile="clear",
        peak_irradiance_w_m2=800.0,
        sunrise_hour=6.0,
        sunset_hour=18.0,
    )
    times = np.array([0.0, 6.0 * 3600.0, 12.0 * 3600.0, 18.0 * 3600.0, 24.0 * 3600.0])
    # The public helper accepts a scalar time; keep the analytical sample
    # points explicit so this test does not require vectorization.
    values = np.asarray([irradiance(float(time), config) for time in times])

    np.testing.assert_allclose(values, [0.0, 0.0, 800.0, 0.0, 0.0], atol=1e-12)


def test_irradiance_repeats_daily_and_constant_profile_ignores_daylight():
    clear = replace(SimulationConfig(), irradiance_profile="clear", peak_irradiance_w_m2=600.0)
    assert irradiance(8.5 * 3600.0, clear) == pytest.approx(
        irradiance((8.5 + 24.0) * 3600.0, clear)
    )

    constant = replace(
        SimulationConfig(),
        irradiance_profile="constant",
        constant_irradiance_w_m2=123.4,
    )
    np.testing.assert_allclose(
        [irradiance(float(time), constant) for time in [-1.0, 0.0, 6.0 * 3600.0, 23.9 * 3600.0]],
        [123.4] * 4,
    )
