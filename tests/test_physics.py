"""Independent physics and numerical checks for the solar thermal model."""

from dataclasses import replace

import numpy as np
import pytest

from solar_thermal.model import ModelDomainError, SimulationConfig, irradiance, simulate


def cfg(**changes):
    """Make a compact test configuration while retaining contract defaults."""
    return replace(SimulationConfig(), **changes)


def final(result, name):
    return float(result.series[name][-1])


def test_pump_off_cooling_matches_two_independent_exponentials():
    config = cfg(
        pump_mode="off",
        irradiance_profile="constant",
        constant_irradiance_w_m2=0.0,
        collector_area_m2=2.0,
        collector_loss_w_m2k=3.0,
        collector_capacity_j_k=6000.0,
        tank_volume_l=20.0,
        tank_loss_w_k=4.0,
        ambient_c=15.0,
        initial_collector_c=75.0,
        initial_tank_c=55.0,
        duration_s=2400.0,
        output_step_s=60.0,
        max_step_s=10.0,
    )
    result = simulate(config)
    t = config.duration_s
    cc = config.collector_capacity_j_k
    ct = config.tank_volume_l / 1000.0 * config.water_density_kg_m3 * config.water_cp_j_kgk
    kc = config.collector_area_m2 * config.collector_loss_w_m2k
    kt = config.tank_loss_w_k
    expected_collector = config.ambient_c + (config.initial_collector_c - config.ambient_c) * np.exp(-kc * t / cc)
    expected_tank = config.ambient_c + (config.initial_tank_c - config.ambient_c) * np.exp(-kt * t / ct)

    assert np.all(result.series["pump_on"] == np.array(False))
    assert np.allclose(result.series["transfer_w"], 0.0, atol=1e-10)
    assert final(result, "collector_c") == pytest.approx(expected_collector, abs=2e-7)
    assert final(result, "tank_c") == pytest.approx(expected_tank, abs=2e-7)


def test_adiabatic_pumped_system_reaches_energy_weighted_equilibrium():
    config = cfg(
        pump_mode="continuous",
        mass_flow_kg_s=0.25,
        collector_area_m2=2.0,
        collector_loss_w_m2k=0.0,
        tank_loss_w_k=0.0,
        collector_capacity_j_k=5000.0,
        tank_volume_l=4.0,
        initial_collector_c=80.0,
        initial_tank_c=20.0,
        irradiance_profile="constant",
        constant_irradiance_w_m2=0.0,
        duration_s=300.0,
        output_step_s=5.0,
        max_step_s=2.0,
    )
    result = simulate(config)
    cc = config.collector_capacity_j_k
    ct = config.tank_volume_l / 1000 * config.water_density_kg_m3 * config.water_cp_j_kgk
    expected = (cc * config.initial_collector_c + ct * config.initial_tank_c) / (cc + ct)
    total_change = cc * (final(result, "collector_c") - config.initial_collector_c) + ct * (
        final(result, "tank_c") - config.initial_tank_c
    )

    assert final(result, "collector_c") == pytest.approx(expected, abs=1e-6)
    assert final(result, "tank_c") == pytest.approx(expected, abs=1e-6)
    assert total_change == pytest.approx(0.0, abs=0.02)
    assert final(result, "transfer_energy_j") > 0.0
    assert result.summary["collector_loss_kwh"] == pytest.approx(0.0, abs=1e-12)
    assert result.summary["tank_loss_kwh"] == pytest.approx(0.0, abs=1e-12)


def test_initial_ambient_equilibrium_stays_at_rest():
    config = cfg(
        pump_mode="differential",
        mass_flow_kg_s=0.10,
        ambient_c=22.0,
        initial_collector_c=22.0,
        initial_tank_c=22.0,
        irradiance_profile="constant",
        constant_irradiance_w_m2=0.0,
        duration_s=12000.0,
        output_step_s=300.0,
        max_step_s=60.0,
    )
    result = simulate(config)

    np.testing.assert_allclose(result.series["collector_c"], 22.0, atol=1e-10)
    np.testing.assert_allclose(result.series["tank_c"], 22.0, atol=1e-10)
    np.testing.assert_allclose(result.series["transfer_w"], 0.0, atol=1e-10)
    assert result.events == [{"time_s": 0.0, "pump_on": False, "collector_c": 22.0, "tank_c": 22.0}]


def test_clear_day_incident_energy_matches_analytic_sine_integral():
    config = cfg(
        pump_mode="off",
        irradiance_profile="clear",
        peak_irradiance_w_m2=900.0,
        collector_area_m2=3.0,
        collector_loss_w_m2k=30.0,
        tank_loss_w_k=3.0,
        duration_s=86400.0,
        output_step_s=600.0,
        max_step_s=60.0,
    )
    result = simulate(config)
    daylight_s = (config.sunset_hour - config.sunrise_hour) * 3600.0
    expected_incident_j = (
        config.collector_area_m2
        * config.peak_irradiance_w_m2
        * daylight_s
        * 2.0
        / np.pi
    )

    assert final(result, "incident_energy_j") == pytest.approx(expected_incident_j, rel=2e-8)
    assert final(result, "incident_energy_j") > 0.0


def test_thermal_change_matches_independent_external_energy_integral():
    config = cfg(
        pump_mode="continuous",
        mass_flow_kg_s=0.12,
        collector_area_m2=2.5,
        collector_loss_w_m2k=4.0,
        tank_loss_w_k=3.0,
        collector_capacity_j_k=6000.0,
        tank_volume_l=12.0,
        ambient_c=18.0,
        initial_collector_c=25.0,
        initial_tank_c=20.0,
        irradiance_profile="constant",
        constant_irradiance_w_m2=350.0,
        duration_s=20000.0,
        output_step_s=300.0,
        max_step_s=60.0,
    )
    result = simulate(config)
    cc = config.collector_capacity_j_k
    ct = config.tank_volume_l / 1000.0 * config.water_density_kg_m3 * config.water_cp_j_kgk
    thermal_change_j = cc * (final(result, "collector_c") - result.series["collector_c"][0]) + ct * (
        final(result, "tank_c") - result.series["tank_c"][0]
    )
    external_net_j = (
        final(result, "absorbed_energy_j")
        - final(result, "collector_loss_energy_j")
        - final(result, "tank_loss_energy_j")
    )

    # This independently recomputes storage change from temperatures and uses
    # only external cumulative flows; transfer is internal and cancels.
    assert thermal_change_j == pytest.approx(external_net_j, rel=2e-7, abs=0.05)
    assert abs(thermal_change_j) > 1000.0


def test_constant_sun_steady_state_matches_linear_energy_balance():
    config = cfg(
        pump_mode="continuous",
        mass_flow_kg_s=0.20,
        collector_area_m2=2.0,
        optical_efficiency=0.80,
        peak_irradiance_w_m2=300.0,
        irradiance_profile="constant",
        constant_irradiance_w_m2=300.0,
        collector_loss_w_m2k=3.0,
        tank_loss_w_k=4.0,
        collector_capacity_j_k=3000.0,
        tank_volume_l=10.0,
        ambient_c=20.0,
        initial_collector_c=20.0,
        initial_tank_c=20.0,
        duration_s=120000.0,
        output_step_s=3600.0,
        max_step_s=300.0,
    )
    result = simulate(config)
    qabs = config.optical_efficiency * config.collector_area_m2 * config.constant_irradiance_w_m2
    kc = config.collector_area_m2 * config.collector_loss_w_m2k
    kt = config.tank_loss_w_k
    conductance = config.mass_flow_kg_s * config.water_cp_j_kgk
    tank_rise = qabs / (kc * (1.0 + kt / conductance) + kt)
    collector_rise = tank_rise * (1.0 + kt / conductance)

    assert final(result, "tank_c") == pytest.approx(config.ambient_c + tank_rise, abs=0.12)
    assert final(result, "collector_c") == pytest.approx(config.ambient_c + collector_rise, abs=0.12)
    assert final(result, "transfer_w") > 0.0


def test_no_sun_system_returns_to_ambient_and_differential_pump_turns_off():
    config = cfg(
        pump_mode="differential",
        mass_flow_kg_s=0.10,
        collector_area_m2=2.0,
        collector_loss_w_m2k=4.0,
        collector_capacity_j_k=5000.0,
        tank_volume_l=10.0,
        tank_loss_w_k=4.0,
        ambient_c=20.0,
        initial_collector_c=80.0,
        initial_tank_c=60.0,
        irradiance_profile="constant",
        constant_irradiance_w_m2=0.0,
        duration_s=100000.0,
        output_step_s=1800.0,
        max_step_s=300.0,
    )
    result = simulate(config)

    assert final(result, "collector_c") == pytest.approx(config.ambient_c, abs=0.1)
    assert final(result, "tank_c") == pytest.approx(config.ambient_c, abs=0.1)
    assert bool(result.series["pump_on"][-1]) is False
    assert result.summary["pump_starts"] >= 1
    assert any(event["pump_on"] is False for event in result.events[1:])


@pytest.mark.parametrize("pump_mode", ["off", "continuous"])
def test_off_or_zero_flow_has_no_heat_transfer(pump_mode):
    config = cfg(
        pump_mode=pump_mode,
        mass_flow_kg_s=0.0 if pump_mode == "continuous" else 0.25,
        collector_loss_w_m2k=0.0,
        tank_loss_w_k=0.0,
        collector_area_m2=1.0,
        irradiance_profile="constant",
        constant_irradiance_w_m2=0.0,
        initial_collector_c=80.0,
        initial_tank_c=20.0,
        duration_s=200.0,
        output_step_s=20.0,
        max_step_s=10.0,
    )
    result = simulate(config)

    assert np.all(result.series["pump_on"] == np.array(False))
    np.testing.assert_allclose(result.series["transfer_w"], 0.0, atol=1e-12)
    assert final(result, "collector_c") == pytest.approx(80.0, abs=1e-10)
    assert final(result, "tank_c") == pytest.approx(20.0, abs=1e-10)


def test_continuous_pump_allows_reverse_heat_flow():
    config = cfg(
        pump_mode="continuous",
        mass_flow_kg_s=1.0,
        collector_area_m2=1.0,
        collector_loss_w_m2k=0.0,
        tank_loss_w_k=0.0,
        collector_capacity_j_k=4000.0,
        tank_volume_l=2.0,
        initial_collector_c=20.0,
        initial_tank_c=80.0,
        irradiance_profile="constant",
        constant_irradiance_w_m2=0.0,
        duration_s=5000.0,
        output_step_s=50.0,
        max_step_s=20.0,
    )
    result = simulate(config)
    cc = config.collector_capacity_j_k
    ct = config.tank_volume_l / 1000 * config.water_density_kg_m3 * config.water_cp_j_kgk
    expected = (cc * 20.0 + ct * 80.0) / (cc + ct)

    assert np.min(result.series["transfer_w"]) < 0.0
    assert final(result, "transfer_energy_j") < 0.0
    assert final(result, "collector_c") == pytest.approx(expected, abs=1e-5)
    assert final(result, "tank_c") == pytest.approx(expected, abs=1e-5)


def test_hysteresis_switch_events_hit_exact_thresholds():
    rising = cfg(
        pump_mode="differential",
        mass_flow_kg_s=0.10,
        collector_capacity_j_k=1000.0,
        tank_volume_l=24.0,
        collector_area_m2=2.0,
        collector_loss_w_m2k=0.0,
        tank_loss_w_k=0.0,
        pump_on_delta_k=2.0,
        pump_off_delta_k=1.0,
        initial_collector_c=20.0,
        initial_tank_c=20.0,
        irradiance_profile="constant",
        constant_irradiance_w_m2=800.0,
        duration_s=100.0,
        output_step_s=25.0,
        max_step_s=10.0,
    )
    rise_result = simulate(rising)
    on_event = next(event for event in rise_result.events[1:] if event["pump_on"])
    assert on_event["collector_c"] - on_event["tank_c"] == pytest.approx(2.0, abs=2e-6)
    assert on_event["time_s"] < rising.output_step_s

    falling = replace(
        rising,
        constant_irradiance_w_m2=0.0,
        initial_collector_c=50.0,
        initial_tank_c=20.0,
        duration_s=100.0,
    )
    fall_result = simulate(falling)
    off_event = next(event for event in fall_result.events[1:] if not event["pump_on"])
    assert off_event["collector_c"] - off_event["tank_c"] == pytest.approx(1.0, abs=2e-6)
    assert off_event["time_s"] < falling.output_step_s


def test_initial_pump_state_obeys_mode_threshold_and_zero_flow_rules():
    equal_on = cfg(
        pump_mode="differential",
        initial_collector_c=26.0,
        initial_tank_c=20.0,
        pump_on_delta_k=6.0,
        pump_off_delta_k=2.0,
        duration_s=1.0,
        output_step_s=1.0,
    )
    assert simulate(equal_on).events[0]["pump_on"] is True

    below_on = replace(equal_on, initial_collector_c=25.9)
    assert simulate(below_on).events[0]["pump_on"] is False

    zero_flow = replace(equal_on, pump_mode="continuous", mass_flow_kg_s=0.0)
    assert simulate(zero_flow).events[0]["pump_on"] is False


def test_tighter_solver_settings_converge_to_the_same_physical_result():
    coarse = cfg(
        pump_mode="continuous",
        mass_flow_kg_s=0.08,
        collector_area_m2=3.0,
        collector_loss_w_m2k=4.0,
        tank_loss_w_k=2.0,
        tank_volume_l=20.0,
        collector_capacity_j_k=7000.0,
        irradiance_profile="constant",
        constant_irradiance_w_m2=450.0,
        duration_s=12000.0,
        output_step_s=300.0,
        max_step_s=120.0,
        rtol=1e-6,
        atol=1e-7,
    )
    tight = replace(coarse, max_step_s=10.0, rtol=2e-10, atol=2e-10)
    coarse_result = simulate(coarse)
    tight_result = simulate(tight)

    for key in ("collector_c", "tank_c", "transfer_energy_j", "stored_energy_change_j"):
        assert final(coarse_result, key) == pytest.approx(final(tight_result, key), rel=3e-5, abs=3e-5)


@pytest.mark.parametrize(
    "changes",
    [
        {"max_temperature_c": 30.0, "initial_collector_c": 20.0, "initial_tank_c": 20.0},
        {"min_temperature_c": 4.0, "ambient_c": 0.0, "initial_collector_c": 5.0, "initial_tank_c": 5.0},
    ],
)
def test_simulation_raises_on_temperature_domain_bound(changes):
    config = cfg(
        pump_mode="off",
        irradiance_profile="constant",
        constant_irradiance_w_m2=1000.0 if "max_temperature_c" in changes else 0.0,
        collector_area_m2=2.0,
        collector_loss_w_m2k=5.0,
        tank_loss_w_k=5.0,
        collector_capacity_j_k=1000.0,
        tank_volume_l=1.0,
        duration_s=20000.0,
        output_step_s=100.0,
        max_step_s=30.0,
        **changes,
    )
    with pytest.raises(ModelDomainError):
        simulate(config)
