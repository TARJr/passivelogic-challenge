from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from solar_thermal import animation
from solar_thermal.model import SimulationConfig


@dataclass
class FakeResult:
    config: SimulationConfig
    series: dict[str, np.ndarray]
    events: list[dict[str, object]]


def _result(name: str = "demo") -> FakeResult:
    config = SimulationConfig(
        irradiance_profile="constant",
        constant_irradiance_w_m2=123.4567,
        duration_s=10,
        output_step_s=10,
        max_step_s=10,
    )
    return FakeResult(
        config,
        {
            "time_s": np.array([0.0, 10.0]),
            "collector_c": np.array([20.0, 30.0]),
            "tank_c": np.array([20.0, 25.0]),
            "irradiance_w_m2": np.array([123.4567, 123.4567]),
        },
        [
            {"time_s": 0.0, "pump_on": False, "collector_c": 20.0, "tank_c": 20.0},
            {"time_s": 5.0, "pump_on": True, "collector_c": 27.123456789, "tank_c": 23.654321987},
        ],
    )


def test_build_payload_merges_events_and_preserves_event_state() -> None:
    payload = animation.build_payload({"demo / <clear>": _result()})
    scenario = payload["scenarios"][0]

    assert payload["initialScenario"] == scenario["id"]
    assert scenario["config"]["constant_irradiance_w_m2"] == 123.4567
    assert [row[0] for row in scenario["samples"]] == [0.0, 5.0, 10.0]
    assert scenario["samples"][1] == [5.0, 27.123456789, 23.654321987, 123.457]
    assert scenario["events"][1]["pump_on"] is True
    assert scenario["events"][1]["time_s"] == 5.0


def test_render_fragment_escapes_script_terminators_and_inlines_playback(tmp_path, monkeypatch) -> None:
    template = tmp_path / "heat_flow.html"
    script = tmp_path / "playback.js"
    template.write_text("<script type='application/json'>__SOLAR_PAYLOAD__</script>__SOLAR_SCRIPT__", encoding="utf-8")
    script.write_text("window.playbackLoaded = true;", encoding="utf-8")
    monkeypatch.setattr(animation, "_TEMPLATE_PATH", template)
    monkeypatch.setattr(animation, "_SCRIPT_PATH", script)

    fragment = animation.render_fragment({"</script><x>": _result()})
    assert "\\u003c/script\\u003e" in fragment
    assert "window.playbackLoaded = true;" in fragment
    assert "NaN" not in fragment
    assert "__SOLAR_PAYLOAD__" not in fragment
    assert "__SOLAR_SCRIPT__" not in fragment


def test_write_animation_is_standalone_and_has_navigation(tmp_path, monkeypatch) -> None:
    template = tmp_path / "heat_flow.html"
    script = tmp_path / "playback.js"
    template.write_text("<section class='viz-controls'>__SOLAR_PAYLOAD__</section>__SOLAR_SCRIPT__", encoding="utf-8")
    script.write_text("window.playbackLoaded = true;", encoding="utf-8")
    monkeypatch.setattr(animation, "_TEMPLATE_PATH", template)
    monkeypatch.setattr(animation, "_SCRIPT_PATH", script)

    output = tmp_path / "output"
    animation.write_animation({"demo": _result()}, output)
    document = (output / "index.html").read_text(encoding="utf-8")
    assert 'href="report.html"' in document
    assert 'href="verification.json"' in document
    assert ".form-range" in document
    assert "window.playbackLoaded = true;" in document
