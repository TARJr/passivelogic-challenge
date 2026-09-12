# Validation and example results

Verified on 2026-09-11 with Python 3.12.14. Exact package versions are saved in
[`requirements-lock.txt`](../requirements-lock.txt) and the generated
[`environment.json`](../results/environment.json).

## Checks performed

`python -m pytest -q` completed with **46 tests passing**. The suite covers
analytical cooling, isolated-system equilibration, constant-sun steady state,
equilibrium at ambient, reverse heat flow, no flow, pump thresholds and initial
states, conservation, irradiance integrals, numerical convergence, model-domain
errors, invalid input, reporting-grid independence, CLI failure behavior, and
exported report/data consistency, and the animated-view payload.

The animated view also passes **6 JavaScript checks**, run with
`node --test tests/playback.test.cjs`. These check interpolation, exact switch
state, reverse heat transfer with forward water circulation, tank energy,
playback bounds, and exact event temperatures against all four generated runs.
Node is only needed to run these extra tests, not to run the Python simulation
or open its viewer.

The analytical cases matter because an energy ledger can balance even if the
underlying equations are wrong. Cooling is compared with exponential solutions,
isolated equilibration with the capacity-weighted equilibrium temperature, and
steady operation with the independently solved linear heat balance. The clear
day's total incident energy is checked against the integral of the half sine.

A regression test also uses a 0.36-second daylight window with a permitted
one-hour maximum solver step. Splitting the integration at sunrise and sunset
ensures this input is captured instead of silently skipped.

The default command completed all four scenarios and their refined reruns.
Refinement halves the maximum internal step and tightens both solver tolerances
by a factor of ten (subject to the documented relative-tolerance floor).
The largest sampled temperature difference was **5.83e-8 °C**, below the
0.001 °C acceptance limit. All event sequence/time, final tank energy and energy
balance checks passed. The largest absolute total balance residual across the
four runs was **1.12e-7 J**. These values demonstrate numerical consistency of
this model; they do not establish accuracy against real equipment.

Full numerical criteria and actual results are in
[`verification.json`](../results/verification.json). `python -m pip check`
reported no broken requirements. All 25 local links/image references in the
original static HTML report resolve. The comparison and scenario PNG plots were visually
inspected. The embedded browser blocked local HTML file URLs, so HTML browser
rendering was not verified; its files and links were checked directly.

## Illustrative 24-hour results

All runs start at midnight with collector and tank at 68 °F. The collector area
is 4 m², the tank holds 52.8 US gallons, and ambient stays at 68 °F. These are configurable
example assumptions, not measured or calibrated equipment data.

| Weather | Pump control | Final tank, °F | Tank energy gain, kWh | Pump runtime, h | Pump electricity, kWh |
| --- | --- | ---: | ---: | ---: | ---: |
| Clear | Differential | 143.44 | 9.732 | 9.67 | 0.242 |
| Clear | Continuous | 114.47 | 5.996 | 24.00 | 0.600 |
| Cloudy | Differential | 118.64 | 6.533 | 8.91 | 0.223 |
| Cloudy | Continuous | 100.00 | 4.129 | 24.00 | 0.600 |

Continuous pumping returns stored heat to the cooler collector after useful
sunlight declines; some of that heat then escapes to ambient. Differential
control prevents this circulation when the collector is not sufficiently warmer
than the tank. Cloud cover reduces input and introduces additional switches.
The tank still loses heat through its own insulation while the pump is off.

The tank energy gain is its final thermal energy minus its initial energy.
It is different from cumulative heat delivered to the tank, because the tank
also loses heat to ambient. Pump electricity is a separate electrical account;
its thermal contribution is deliberately neglected in this model.

Open [`results/index.html`](../results/index.html) for the animated system and
[`results/report.html`](../results/report.html) for the plots and raw data.
Regenerate everything with `python run.py` after activating the environment.
