# Solar thermal challenge

This repository contains a small, auditable solar-thermal simulation. It models one mixed-temperature solar collector and one well-mixed hot-water tank over a configurable time interval. The default command runs illustrative clear and cloudy day scenarios with differential and continuous pump operation, then writes an animated system view and supporting plots under `results/`.

The model is intended for transparent comparison of controls, energy accounting, and numerical behavior. Its defaults are illustrative and are not calibrated manufacturer data. It is not a replacement for a detailed collector rating model, a plant-loop model, or a validated design calculation.

See the [model derivation](docs/model.md), [validation and example results](docs/validation.md), and [generated report](results/index.html).

## Quick preview — no installation

Download the repository using GitHub's **Code → Download ZIP**, then extract it. Open `results/index.html` in a modern browser. This is a saved simulation run: press **Play simulation** to animate it, or open **Graphs and data** to inspect the plots and CSV/JSON exports.

The preview requires no Python, Node.js, web server, account, API key, or internet connection. To calculate new results or change the inputs, follow the setup below.

## Run the simulation

Use **Python 3.12**, the version used for the checked-in results. Open a terminal in the extracted repository folder (the folder containing `run.py`). The following commands create an isolated environment and install the exact recorded dependency versions. Internet access is required for the initial dependency download.

### macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python run.py
```

Check `python3 --version` first; use `python3.12` in the first command if you have multiple Python versions installed.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe run.py
```

These commands do not require environment activation or PowerShell execution-policy changes. `requirements.txt` provides flexible version ranges for other environments; Python 3.12 with `requirements-lock.txt` is the reproducibility path.

Successful execution prints four scenario results with `convergence PASS`, followed by the report path. It regenerates `results/`; use `--output results/reviewer-run` to retain the original example files. Open or refresh the generated `index.html` after a run.

The command does not start a web server. Open `results/index.html` to see the solar collector, pump, circulating water, and storage tank. Press **Play simulation**, drag the time slider, or choose another scenario. Playback initially pauses at 9 AM; displayed values describe the simulated state at that time. The visual shows component temperatures, solar heat input, losses, and the signed heat transfer between collector and tank. **Graphs and data** opens the supporting report at `results/report.html`.

Playback uses the computed Python results, interpolating temperatures between output samples and preserving exact pump-switch times and temperatures. It does not run a separate JavaScript physics solver. Water dots illustrate circulation, not a modeled pipe transit time. Tank color is uniform because the tank is well mixed; color indicates temperature, not a changing water level. Edit a JSON configuration and rerun Python to change physical parameters.

All results are offline and require no external assets. The viewer uses JavaScript for playback; CSV, JSON, and static plots remain available separately.

For a web preview, select `results/index.html`. The `.html.in` source template is populated by the generator and cannot run on its own. The old `solar_thermal/templates/heat_flow.html` preview path now links to the complete simulator.

Run the Python test suite with:

```bash
.venv/bin/python -m pytest -q
```

On Windows, use `.\.venv\Scripts\python.exe -m pytest -q` instead. Optional playback tests require Node.js 20 or newer: `node --test tests/playback.test.cjs`. Node.js is not needed for the simulation or browser preview.

In the remaining examples, `python` means the environment's Python executable (`.venv/bin/python` on macOS/Linux or `.\.venv\Scripts\python.exe` on Windows).

## Technology choices

Python owns the physics and exports: NumPy stores numerical arrays, SciPy integrates the energy balances and controller events, and Matplotlib generates the charts. The viewer is plain HTML, CSS, SVG, and JavaScript with its data embedded in the page. There is no frontend build step or separate browser physics model. Pytest covers the Python implementation; Node's built-in test runner checks playback logic.

## Custom configuration

`run.py` accepts a flat JSON configuration and an output directory:

```bash
python run.py --config examples/clear_day.json --output results/custom
```

The JSON keys are the input fields of `SimulationConfig`; unknown keys are rejected. `tank_capacity_j_k` is a derived read-only property, computed from tank volume, density, and specific heat, so it is not a JSON key. A minimal constant-irradiance example is:

```json
{
  "irradiance_profile": "constant",
  "constant_irradiance_w_m2": 500.0,
  "duration_s": 43200.0,
  "output_step_s": 30.0,
  "pump_mode": "differential"
}
```

`SimulationConfig` is also available from the Python API:

```python
from solar_thermal.model import SimulationConfig, simulate

config = SimulationConfig(duration_s=12 * 3600, irradiance_profile="clear")
result = simulate(config)
print(result.summary["final_tank_c"])
```

The public API also exposes `SimulationResult`, `irradiance`, `load_config`, `config_from_dict`, and `ModelDomainError`.

## Code organization

- `solar_thermal/model.py`: validated inputs, weather profiles, energy balances, and event-driven integration.
- `solar_thermal/verification.py`: numerical refinement and explicit acceptance checks.
- `solar_thermal/reporting.py`: CSV/JSON exports, plots, and offline report.
- `solar_thermal/animation.py` and `solar_thermal/templates/`: animated system viewer and its embedded simulation data.
- `run.py`: configuration loading and orchestration of simulation, verification, and export.
- `tests/`: independent physical limits, configuration tests, and end-to-end checks.
- `examples/`: complete, editable inputs for the four demonstration scenarios.

## Configuration and units

All time values are seconds unless the name says otherwise. Temperatures are degrees Celsius, irradiance is incident solar power in W/m², heat rates are W, capacities are J/K, mass flow is kg/s, and energies are J in the series and kWh in the summary.

These SI units are retained in the machine-readable CSV, JSON, and configuration files. The animated simulator and human-facing reports convert displayed temperatures to °F, tank capacity to US gallons, and loop flow to US gallons per minute; irradiance, heat rates, and energy remain W/m², W, and kWh. One US gallon is 3.785411784 litres, so the default 200-litre tank displays as 52.8 US gallons.

| Field | Default | Meaning |
| --- | ---: | --- |
| `collector_area_m2` | 4.0 | Collector aperture/absorbing area. |
| `optical_efficiency` | 0.75 | Fraction of incident irradiance absorbed by the collector. |
| `collector_loss_w_m2k` | 5.0 | Collector loss coefficient per area and kelvin. |
| `collector_capacity_j_k` | 15000.0 | Lumped collector plus contained-fluid heat capacity. |
| `tank_volume_l` | 200.0 | Tank volume in litres. |
| `tank_loss_w_k` | 2.0 | Lumped tank loss coefficient to ambient. |
| `water_density_kg_m3` | 1000.0 | Water density used for tank capacity. |
| `water_cp_j_kgk` | 4180.0 | Constant water specific heat. |
| `mass_flow_kg_s` | 0.03 | Collector loop mass flow while the pump is on. |
| `pump_mode` | `differential` | `differential`, `continuous`, or `off`. |
| `pump_power_w` | 25.0 | Electrical pump power while on. This is tracked separately. |
| `pump_on_delta_k` | 6.0 | Differential controller turn-on threshold, collector minus tank. |
| `pump_off_delta_k` | 2.0 | Differential controller turn-off threshold. |
| `ambient_c` | 20.0 | Ambient temperature used by both loss terms. |
| `irradiance_profile` | `clear` | `clear`, `cloudy`, or `constant`. |
| `peak_irradiance_w_m2` | 800.0 | Clear-profile peak irradiance. |
| `constant_irradiance_w_m2` | 0.0 | Irradiance for the constant profile, day and night. |
| `sunrise_hour` / `sunset_hour` | 6.0 / 18.0 | Daily daylight interval in hours. |
| `initial_collector_c` / `initial_tank_c` | 20.0 / 20.0 | Initial lumped temperatures. |
| `duration_s` | 86400.0 | Simulation duration. |
| `output_step_s` | 60.0 | Uniform output spacing. The exact end time is included. |
| `max_step_s` | 60.0 | Maximum adaptive solver step. |
| `rtol` / `atol` | 1e-8 / 1e-8 | Relative and absolute ODE tolerances. |
| `min_temperature_c` / `max_temperature_c` | 0.0 / 95.0 | Physical-domain guard bounds. |

The clear profile repeats daily as a half sine wave between sunrise and sunset. The cloudy profile starts from the same clear curve and applies three smooth Gaussian attenuation dips. The constant profile is applied during both day and night.

Configuration validation rejects nonfinite values, booleans or other wrong types, unknown modes, invalid thresholds and bounds, initial temperatures outside the strict domain, and requests that would exceed one million output samples. Relative tolerance must be between `1e-13` and `1e-2`; absolute tolerance must be greater than zero and no larger than `1e-2`.

## What is simulated

The collector and tank are each represented by one well-mixed temperature. Let `T_c` and `T_t` be their temperatures, `T_a` the ambient temperature, and `C_c` and `C_t` their heat capacities. With incident irradiance `G(t)`, the model computes

\[
Q_{abs}=\eta A G(t),\quad
Q_{c,loss}=A U_c(T_c-T_a),\quad
Q_{t,loss}=U_t(T_t-T_a),
\]

and, when the pump is on,

\[
Q_{flow}=\dot m c_p(T_c-T_t).
\]

The two energy balances are

\[
C_c\frac{dT_c}{dt}=Q_{abs}-Q_{c,loss}-Q_{flow},
\qquad
C_t\frac{dT_t}{dt}=Q_{flow}-Q_{t,loss},
\]

where `C_t = (V/1000) * rho * c_p`. A negative loss means ambient is warming that component; signed transfer can also be negative when heat flows from tank to collector.

The differential controller turns on when `T_c - T_t` rises to `pump_on_delta_k` and turns off when it falls to `pump_off_delta_k`. The two thresholds provide hysteresis. `continuous` keeps the pump on, and `off` keeps it off. If flow is zero, the pump is forced off. Switches are located by solver events, so they are not limited to output sample times.

The solver uses SciPy's adaptive `solve_ivp` with the high-order DOP853 method, dense output, and terminal switch events. Integration also splits at sunrise and sunset, so a large solver step cannot skip an entire short daylight interval. It accumulates incident, absorbed, collector-loss, tank-loss, transfer, and pump electrical energies inside the ODE. Pump electrical energy is reported separately; pump heat is deliberately neglected in the thermal equations.

If either modeled temperature reaches a configured domain bound, the run aborts with `ModelDomainError`. Temperatures and energy are never clipped to make a run appear valid.

## Assumptions and limits

The collector outlet is its single mixed temperature, the return is the single mixed tank temperature, pipes are adiabatic with zero transport delay, and fluid properties are constant. There is no separate heat exchanger, pipe heat loss, thermosiphon flow when the pump is off, tank draw/load, auxiliary heater, weather file, shading model, or stratification. In particular, a 200 L tank is represented by one temperature, so the model cannot predict a hot upper layer, cold inlet plume, or mixing front. A future extension could use a multi-node tank with inter-node conduction/advection and explicit inlet/outlet connections; that is outside this challenge and is not implemented.

The solar collector is intentionally simpler than the full EnergyPlus flat-plate collector model. EnergyPlus documents collector performance using established rating equations and additional plant-loop behavior; this challenge uses a transparent constant optical efficiency and linear loss term so that the energy path and controller behavior remain easy to audit. The model should therefore be compared with the equations documented here, not described as an identical EnergyPlus implementation.

## Outputs

`SimulationResult.series` contains equal-length arrays for time, collector/tank temperatures, pump state, irradiance, signed heat rates, and cumulative energy channels. `summary` contains final and sampled peak temperatures, incident/absorbed/loss/transfer energies, stored and tank energy changes, pump electricity/runtime/start count, balance residual, relative balance error, and solver evaluation count. `events` records the initial state and subsequent pump switches with time and temperatures.

Before exporting a report, `run.py` independently reruns every scenario with half the configured `max_step_s` and ten-times-tighter tolerances. The baseline passes only when the refined run stays within 0.001 °C maximum sampled temperature difference, `max(10 J, 1 ppm)` of final tank-energy difference, 1 s maximum switch-time difference with the same switch sequence, and `1e-7` relative balance error. This convergence check is separate from the algebraic balance identity: agreement under refinement provides evidence that the numerical trajectory and event locations are resolved. A failed check aborts report export.

The report writer emits, beneath the selected output directory:

```text
index.html                         # animated heat-transfer system view
report.html                        # supporting comparison report and data links
comparison.png                     # cross-scenario plots
summary.json                       # combined scenario summaries
verification.json                  # refinement checks and acceptance margins
environment.json                   # Python/platform/package manifest
<scenario>/plots.png
<scenario>/results.csv
<scenario>/config.json
<scenario>/summary.json
<scenario>/pump_events.json
```

The exact scenario labels and generated numerical values belong to the run that produced the files. This README intentionally does not claim measured performance or fixed test counts.

## References

The physical framing follows the primary EnergyPlus engineering references for [solar collectors](https://bigladdersoftware.com/epx/docs/25-1/engineering-reference/solar-collectors.html) and [water thermal tanks](https://bigladdersoftware.com/epx/docs/25-1/engineering-reference/water-thermal-tanks-includes-water-heaters.html), including the distinction between mixed and stratified tank models. The numerical integration interface is documented by SciPy's [`solve_ivp`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.solve_ivp.html), including adaptive methods and event functions.
