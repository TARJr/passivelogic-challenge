# Model notes

This note gives the derivation behind the implementation. The user-facing setup and CLI guide is [`README.md`](../README.md).

## State and capacities

The state is two temperatures:

\[
y(t)=\begin{bmatrix}T_c(t)\\T_t(t)\end{bmatrix},
\]

where `T_c` is the collector's lumped absorber/contained-fluid temperature and `T_t` is the tank's single mixed temperature. The collector capacity is supplied directly as `collector_capacity_j_k`:

\[
C_c=\texttt{collector\_capacity\_j\_k}.
\]

The tank capacity is derived from litres converted to cubic metres:

\[
C_t=\left(\frac{V_L}{1000}\right)\rho c_p.
\]

The density and specific heat are constant configuration values. No temperature-dependent property correction is applied.

In the Python API, this value is exposed as the read-only `SimulationConfig.tank_capacity_j_k` property. It is derived rather than accepted as a separate configuration input, which prevents the volume and capacity from silently disagreeing.

## Heat rates

For incident irradiance `G(t)` in W/m², collector area `A`, and optical efficiency `eta`:

\[
Q_{abs}(t)=\eta A G(t).
\]

The collector loses heat to ambient according to a linear coefficient per area, while the tank uses a lumped coefficient:

\[
Q_{c,loss}=A U_c(T_c-T_a),
\qquad
Q_{t,loss}=U_t(T_t-T_a).
\]

The pump loop transfers heat based on mass flow and the collector-to-tank temperature difference:

\[
Q_{flow}=s\dot m c_p(T_c-T_t),
\]

where `s = 1` while the pump is on and `s = 0` while it is off. This rate is signed: it is positive when the collector heats the tank and negative if the tank is hotter.

Substitution into each control-volume balance gives the ODE:

\[
\frac{dT_c}{dt}=\frac{Q_{abs}-Q_{c,loss}-Q_{flow}}{C_c},
\qquad
\frac{dT_t}{dt}=\frac{Q_{flow}-Q_{t,loss}}{C_t}.
\]

The transfer term cancels when the two equations are added, leaving the total thermal storage change driven by solar absorption and both signed ambient-loss terms. The implementation therefore defines the total balance residual explicitly as

\[
R(t)=\Delta E_{stored}(t)-\left[E_{absorbed}(t)-E_{c,loss}(t)-E_{t,loss}(t)\right].
\]

`transfer_energy_j` is still integrated and reported as a signed diagnostic, but it does not appear in this total residual because it is internal exchange: it is subtracted from the collector balance and added to the tank balance. A small residual supports numerical/accounting consistency; it is not physical validation by itself.

## Irradiance profiles

The clear profile repeats each day. If `h` is time-of-day in hours, `h_r` is sunrise, and `h_s` is sunset:

\[
G_{clear}(h)=
\begin{cases}
G_{peak}\sin\left(\pi\frac{h-h_r}{h_s-h_r}\right),&h_r\le h\le h_s,\\
0,&\text{otherwise.}
\end{cases}
\]

The cloudy profile multiplies the clear value by three smooth attenuation factors. For each dip with center `mu_i`, width `sigma_i`, and attenuation `a_i`, the factor is

\[
1-a_i\exp\left[-\frac12\left(\frac{h-\mu_i}{\sigma_i}\right)^2\right].
\]

The configured dips are `(10, 0.45, 0.75)`, `(12.5, 0.6, 0.85)`, and `(15, 0.35, 0.65)` in hours. The constant profile returns `constant_irradiance_w_m2` in both daylight and darkness.

## Differential control and event handling

For differential mode, define \(\Delta=T_c-T_t\). The pump starts on a rising crossing of `pump_on_delta_k` and stops on a falling crossing of `pump_off_delta_k`. The thresholds must be ordered so the controller has a hysteresis band. The initial pump state is on if the initial difference is already at or above the on threshold; otherwise it is off.

Each ODE segment uses a fixed pump state. `solve_ivp` integrates that segment with DOP853 and a terminal event for the relevant threshold. At an event, the state is retained, the pump state changes, and integration resumes. Output arrays are then evaluated from dense solutions. At a switch sample, `pump_on` is right-continuous: it reports the state after the switch. This avoids making an output grid decide whether a narrow threshold crossing happened.

Continuous mode integrates with the pump on for the full interval. Off mode integrates with it off. A zero mass flow forces the state off even if differential logic would otherwise request on.

Integration also splits at each sunrise and sunset. This matters for configurable, very short daylight windows: adaptive steps through an otherwise constant nighttime state must not jump over all solar input. The regression suite checks this against the analytical sine-wave energy integral.

The runner checks numerical resolution independently of the residual identity. It reruns each baseline with half the maximum solver step and ten-times-tighter tolerances, then requires the same switch sequence, at most 0.001 °C maximum sampled temperature difference, at most `max(10 J, 1 ppm)` final tank-energy difference, and at most 1 s switch-time difference. The baseline relative balance error must also be no greater than `1e-7`; failed checks prevent report export.

## Energy accounting

The integrator carries cumulative energy states alongside the two temperatures. For each signed heat-rate channel `Q(t)`, its accumulated energy is

\[
E(t)=\int_0^t Q(\tau)\,d\tau.
\]

The implementation records incident solar energy, absorbed solar energy, collector loss energy, tank loss energy, transfer energy, and electrical pump energy. Pump electrical energy is

\[
E_{pump}=\int_0^t s(t)P_{pump}\,dt.
\]

It is kept separate from the thermal ODE: pump heat is explicitly neglected. The reported `stored_energy_change_j` follows the two modeled thermal capacities, while `tank_energy_change_j` follows the tank capacity alone. The total residual uses the explicit equation above; transfer remains available as its own signed channel for auditing. Analytic limits, convergence tests, and sensible parameter sweeps remain necessary for physical validation.

## Domain guard

The configuration defines `min_temperature_c` and `max_temperature_c`, with defaults 0 °C and 95 °C. Terminal temperature events stop the simulation and raise `ModelDomainError` when the model leaves that domain. The implementation does not clamp temperature, energy, or a plotted result to the bound, because clipping would hide an invalid or unsupported trajectory.

## Scope relative to detailed tools

This is a two-node teaching and audit model. It has no separate heat exchanger, no pipe volume or delay, no pipe or tank stratification, no draw-off/load, no auxiliary heater, no thermosiphon, and no weather-file or shading inputs. The collector uses a constant optical efficiency and a linear loss coefficient. EnergyPlus's primary references describe richer flat-plate collector performance and both mixed and stratified water thermal tank objects; this implementation is inspired by those physical categories but does not claim numerical or behavioral identity with the full EnergyPlus collector or plant-loop models.

If a later use case requires outlet-temperature quality, draw events, or top-of-tank delivery temperature, a stratified multi-node tank is the natural next extension. That extension would need defined node volumes, inter-node mixing/conduction, inlet/outlet locations, and a validated numerical/control treatment; it is intentionally outside the current implementation.

## Primary references

- [EnergyPlus 25.1 Solar Collectors Engineering Reference](https://bigladdersoftware.com/epx/docs/25-1/engineering-reference/solar-collectors.html)
- [EnergyPlus 25.1 Water Thermal Tanks Engineering Reference](https://bigladdersoftware.com/epx/docs/25-1/engineering-reference/water-thermal-tanks-includes-water-heaters.html)
- [SciPy `solve_ivp` reference](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.solve_ivp.html)
