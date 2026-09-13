/* Presentation of computed trajectories. This does not integrate a second model. */
(function () {
  "use strict";

  const displayUnits = {
    fahrenheit: celsius => celsius * 9 / 5 + 32,
    usGallons: liters => liters / 3.785411784,
    usGpm: (kgPerSecond, densityKgM3) => kgPerSecond / densityKgM3 * 1000 * 60 / 3.785411784
  };

  function beforeOrAt(rows, time, getTime) {
    let low = 0, high = rows.length;
    while (low < high) {
      const mid = (low + high) >>> 1;
      if (getTime(rows[mid]) <= time) low = mid + 1;
      else high = mid;
    }
    return Math.max(0, low - 1);
  }

  function sampleScenario(scenario, requestedTime) {
    const rows = scenario.samples, c = scenario.config;
    const t = Math.min(rows[rows.length - 1][0], Math.max(rows[0][0], requestedTime));
    const i = beforeOrAt(rows, t, r => r[0]);
    const a = rows[i], b = rows[Math.min(i + 1, rows.length - 1)];
    const f = b[0] > a[0] ? (t - a[0]) / (b[0] - a[0]) : 0;
    const tc = a[1] + f * (b[1] - a[1]);
    const tt = a[2] + f * (b[2] - a[2]);
    const radiation = a[3] + f * (b[3] - a[3]);
    const eventIndex = beforeOrAt(scenario.events, t, e => e.time_s);
    const on = Boolean(scenario.events[eventIndex].pump_on);
    const flow = on ? c.mass_flow_kg_s : 0;
    const absorbed = radiation * c.collector_area_m2 * c.optical_efficiency;
    const transfer = on ? flow * c.water_cp_j_kgk * (tc - tt) : 0;
    const collectorLoss = c.collector_area_m2 * c.collector_loss_w_m2k * (tc - c.ambient_c);
    const tankLoss = c.tank_loss_w_k * (tt - c.ambient_c);
    const capacity = c.tank_volume_l / 1000 * c.water_density_kg_m3 * c.water_cp_j_kgk;
    return {time: t, tc, tt, radiation, on, flow, absorbed, transfer, collectorLoss, tankLoss,
      tankNetW: transfer - tankLoss,
      tankEnergyKwh: capacity * (tt - c.initial_tank_c) / 3.6e6};
  }

  if (typeof document === "undefined") {
    if (typeof module !== "undefined") module.exports = {sampleScenario, displayUnits};
    return;
  }
  const root = document.getElementById("solar-heat-view");
  if (!root) return;
  const payload = JSON.parse(root.querySelector("[data-payload]").textContent);
  const q = selector => root.querySelector(selector);
  const picker = q("[data-scenario]"), slider = q("[data-time]"), playButton = q("[data-play]");
  const svg = q(".heat-schematic");
  const ns = "http://www.w3.org/2000/svg";
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let scenario = payload.scenarios.find(s => s.id === payload.initialScenario) || payload.scenarios[0];
  let time = Math.min(9 * 3600, scenario.config.duration_s * 0.65);
  let playing = false, speed = 1800, lastFrame = 0, phase = 0, frameId = 0;
  let parts = {}, layout = {};

  const node = (tag, attrs, parent = svg) => {
    const el = document.createElementNS(ns, tag);
    Object.entries(attrs || {}).forEach(([key, value]) => el.setAttribute(key, value));
    parent.appendChild(el);
    return el;
  };
  const label = (x, y, value, css = "", anchor = "middle") => {
    const el = node("text", {x, y, "text-anchor": anchor, class: css});
    el.textContent = value;
    return el;
  };
  const path = (d, color, width = 9, parent = svg) => node("path", {
    d, fill: "none", stroke: color, "stroke-width": width,
    "stroke-linecap": "round", "stroke-linejoin": "round"
  }, parent);
  const temperatureColor = temp => `color-mix(in oklab, var(--blue), var(--orange) ${Math.min(100, Math.max(0, (temp - 20) / 60 * 100))}%)`;
  const watts = w => Math.abs(w) >= 1000 ? `${(Math.abs(w) / 1000).toFixed(2)} kW` : `${Math.abs(w).toFixed(0)} W`;
  function clock(t) {
    if (t > 0 && t % 86400 === 0) {
      const day = t / 86400;
      return `End of day${day > 1 ? ` ${day}` : ""} · ${t / 3600} hours elapsed`;
    }
    const minutes = Math.floor(t / 60), hours = Math.floor(minutes / 60) % 24;
    return `${hours % 12 || 12}:${String(minutes % 60).padStart(2, "0")} ${hours < 12 ? "AM" : "PM"}`;
  }

  function durationLabel(seconds) {
    if (seconds < 1) return "less than 1 sec";
    const rounded = Math.round(seconds);
    const hours = Math.floor(rounded / 3600);
    const minutes = Math.floor((rounded % 3600) / 60);
    const remainder = rounded % 60;
    return [hours ? `${hours} ${hours === 1 ? "hour" : "hours"}` : "",
      minutes ? `${minutes} min` : "", remainder ? `${remainder} sec` : ""].filter(Boolean).join(" ");
  }

  function updatePlaybackLabels() {
    for (const option of q("[data-speed]").options) {
      option.textContent = `${durationLabel(scenario.config.duration_s)} in ${durationLabel(scenario.config.duration_s / Number(option.value))}`;
    }
  }

  function buildDiagram() {
    const w = Math.max(280, Math.round(q(".heat-stage").getBoundingClientRect().width));
    const mobile = w < 550, h = mobile ? 475 : 425;
    const cx = mobile ? 62 : w * .19, tx = mobile ? w - 64 : w * .81;
    const cw = mobile ? 72 : 106, tw = mobile ? 82 : 120;
    const top = 159, bottom = 328, mid = (cx + cw / 2 + tx - tw / 2) / 2;
    layout = {w, h, mobile, cx, tx, cw, tw, top, bottom, mid};
    svg.replaceChildren();
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    svg.setAttribute("height", h);
    node("desc", {}).textContent = "Water flows from the solar collector through the pump into the tank, returning along the lower pipe. Temperatures are Fahrenheit, tank volume is US gallons, and flow is US gallons per minute. The tank is a uniform mixed volume.";
    const defs = node("defs");
    const marker = node("marker", {id:"heat-arrow-head", viewBox:"0 0 8 8", refX:7, refY:4,
      markerWidth:14, markerHeight:14, orient:"auto-start-reverse", markerUnits:"userSpaceOnUse"}, defs);
    node("path", {d:"M0 0 L8 4 L0 8 Z", fill:"var(--blue)"}, marker);

    parts.sun = node("circle", {cx:cx, cy:36, r:17, fill:"var(--orange)"});
    parts.sunText = label(cx + 30, 32, "", "value", "start");
    parts.solarText = label(cx + 30, 52, "", "sub", "start");
    parts.rays = [];
    for (let n = -1; n <= 1; n++) {
      parts.rays.push(path(`M${cx+n*13} 63 L${cx+n*20} 89`, "var(--orange)", 2));
    }
    label(cx, 113, "Collector");
    parts.collectorTemp = label(cx, 135, "", "value");
    label(tx, 113, "Storage tank");
    parts.tankTemp = label(tx, 135, "", "value");

    parts.panel = node("rect", {x:cx-cw/2, y:148, width:cw, height:196, rx:6,
      fill:"var(--blue)", "fill-opacity":.16, stroke:"var(--border)", "stroke-width":2});
    parts.hot = path(`M${cx+cw*.32} ${top} H${tx-tw/2}`, "var(--orange)", 10);
    parts.returnPipe = path(`M${tx-tw/2} ${bottom} H${cx-cw*.32} V313`, "var(--blue)", 10);
    const xl = cx-cw*.32, xr=cx+cw*.32;
    parts.coil = path(`M${xl} 313 H${xr} V287 H${xl} V261 H${xr} V235 H${xl} V209 H${xr} V183 H${xl} V${top} H${xr}`, "var(--orange)", 6);

    parts.tank = node("rect", {x:tx-tw/2, y:148, width:tw, height:196, rx:tw*.23,
      fill:"var(--blue)", "fill-opacity":.4, stroke:"var(--border)", "stroke-width":3});
    label(tx, 248, `${displayUnits.usGallons(scenario.config.tank_volume_l).toFixed(1)} gal`, "value");
    label(tx, 270, "Mixed", "sub");
    parts.collectorLoss = label(cx, 368, "", "sub");
    parts.tankLoss = label(tx, 368, "", "sub");
    parts.collectorAirLabel = label(cx, 391, "", "sub");
    parts.tankAirLabel = label(tx, 391, "", "sub");

    parts.dots = [];
    for (const line of [parts.hot, parts.returnPipe, parts.coil]) {
      for (let i=0; i<6; i++) parts.dots.push({line, index:i,
        el:node("circle", {r:2.8, fill:"var(--background)", stroke:"var(--foreground)", "stroke-width":.4})});
    }
    const pumpRadius = mobile ? 17 : 23;
    node("circle", {cx:mid, cy:top, r:pumpRadius+4, fill:"var(--background)", stroke:"var(--border)", "stroke-width":3});
    parts.rotor = node("g", {});
    for (let i=0; i<3; i++) {
      node("ellipse", {cx:mid, cy:top-8, rx:4, ry:8, fill:"var(--green)",
        transform:`rotate(${i*120} ${mid} ${top})`}, parts.rotor);
    }
    node("circle", {cx:mid, cy:top, r:3, fill:"var(--foreground)"});
    parts.pumpText = label(mid, top-39, "", "value");
    parts.flowText = label(mid, top+43, "", "sub");
    label(mid, bottom+23, "← Return water", "sub");

    const heatY = mobile ? 424 : 257;
    parts.heatTitle = label(w/2, heatY-20, "", "value");
    parts.heatValue = label(w/2, heatY+1, "", "value");
    const half = mobile ? Math.min(88,w*.25) : Math.max(45, (tx-cx-cw-tw)/2);
    const gradient = node("linearGradient", {id:"heat-flow-gradient", gradientUnits:"userSpaceOnUse",
      x1:w/2-half, y1:heatY+16, x2:w/2+half, y2:heatY+16}, defs);
    parts.heatLeft = node("stop", {offset:"0%"}, gradient);
    parts.heatRight = node("stop", {offset:"100%"}, gradient);
    parts.heatPath = path(`M${w/2-half} ${heatY+16} H${w/2+half}`, "url(#heat-flow-gradient)", 5);
    parts.heatDot = node("circle", {r:5, fill:"url(#heat-flow-gradient)"});
    layout.heatY = heatY+16; layout.heatHalf = half;
    render();
  }

  function render() {
    const s = sampleScenario(scenario, time);
    q("[data-playback-state]").textContent = `Playback ${playing ? "running" : time >= scenario.config.duration_s ? "complete" : "paused"} · ${clock(time)} · ${s.radiation.toFixed(0)} W/m² sunlight`;
    q("[data-clock]").textContent = clock(time);
    slider.value = time;
    slider.setAttribute("aria-valuetext", clock(time));
    parts.collectorTemp.textContent = `${displayUnits.fahrenheit(s.tc).toFixed(1)} °F`;
    parts.tankTemp.textContent = `${displayUnits.fahrenheit(s.tt).toFixed(1)} °F`;
    parts.sunText.textContent = `${s.radiation.toFixed(0)} W/m² sunlight`;
    parts.solarText.textContent = `${watts(s.absorbed)} absorbed`;
    parts.sun.setAttribute("opacity", .12 + .88 * Math.min(1, s.radiation / 800));
    parts.rays.forEach(ray => ray.setAttribute("opacity", Math.min(1, s.radiation / 300)));
    const tcColor = temperatureColor(s.tc), ttColor = temperatureColor(s.tt);
    parts.panel.setAttribute("fill", tcColor);
    parts.coil.setAttribute("stroke", tcColor);
    parts.hot.setAttribute("stroke", tcColor);
    parts.returnPipe.setAttribute("stroke", ttColor);
    parts.tank.setAttribute("fill", ttColor);
    parts.collectorLoss.textContent = `${watts(s.collectorLoss)} ${s.collectorLoss >= 0 ? "to air" : "from air"}`;
    parts.tankLoss.textContent = `${watts(s.tankLoss)} ${s.tankLoss >= 0 ? "to air" : "from air"}`;
    parts.collectorAirLabel.textContent = s.collectorLoss >= 0 ? "Direct heat loss" : "Direct heat gain";
    parts.tankAirLabel.textContent = s.tankLoss >= 0 ? "Direct heat loss" : "Direct heat gain";
    q("[data-tank-net-label]").textContent = s.tankNetW > 0 ? "Total tank heating now" : s.tankNetW < 0 ? "Total tank cooling now" : "Tank energy steady now";
    q("[data-tank-net]").textContent = watts(s.tankNetW);
    q("[data-tank-energy]").textContent = `${s.tankEnergyKwh >= 0 ? "+" : ""}${s.tankEnergyKwh.toFixed(2)} kWh`;
    parts.pumpText.textContent = s.on ? (playing ? "Pump ON" : time >= scenario.config.duration_s ? "Pump ON · ended" : "Paused") : "Pump OFF";
    parts.flowText.textContent = s.on ? `${displayUnits.usGpm(s.flow, scenario.config.water_density_kg_m3).toFixed(2)} gpm →` : "No flow";
    const heatActive = Math.abs(s.transfer) >= .5;
    parts.heatTitle.textContent = !s.on ? "Loop stopped" : !heatActive ? "Negligible heat flow" : s.transfer > 0 ? "Heat → tank" : "Heat → collector";
    parts.heatValue.textContent = `${watts(s.transfer)} flowing now`;
    const warm = "var(--red, #e16d60)", cool = "var(--blue)";
    const equal = "color-mix(in srgb, var(--red, #e16d60), var(--blue))";
    parts.heatLeft.setAttribute("stop-color", s.tc === s.tt ? equal : s.tc > s.tt ? warm : cool);
    parts.heatRight.setAttribute("stop-color", s.tc === s.tt ? equal : s.tc > s.tt ? cool : warm);
    parts.heatPath.setAttribute("opacity", heatActive ? 1 : .2);
    parts.heatPath.removeAttribute("marker-start"); parts.heatPath.removeAttribute("marker-end");
    if (heatActive) parts.heatPath.setAttribute(s.transfer>0 ? "marker-end" : "marker-start", "url(#heat-arrow-head)");
    const direction = s.transfer>=0 ? 1 : -1;
    const progress = direction>0 ? phase%1 : 1-phase%1;
    parts.heatDot.setAttribute("cx",layout.w/2-layout.heatHalf+2*layout.heatHalf*progress);
    parts.heatDot.setAttribute("cy",layout.heatY);
    parts.heatDot.setAttribute("opacity",heatActive ? 1 : 0);
    for (const dot of parts.dots) {
      const p = dot.line.getPointAtLength(((dot.index/6+phase*.15)%1) * dot.line.getTotalLength());
      dot.el.setAttribute("cx", p.x); dot.el.setAttribute("cy", p.y);
      dot.el.setAttribute("opacity", s.on ? 1 : 0);
    }
    parts.rotor.setAttribute("transform",`rotate(${s.on ? phase*180 : 0} ${layout.mid} ${layout.top})`);
    const status = !s.on ? "Pump stopped · no loop heat transfer" : s.transfer<-.5 ? "Tank is losing heat through the collector" : s.transfer>.5 ? "Heat flows from collector to tank" : "Water circulating · negligible loop heat transfer";
    q("[data-state]").textContent = status;
    return s;
  }

  function announce() {
    const s = sampleScenario(scenario,time);
    q("[data-announcement]").textContent = `${clock(time)}. Collector ${displayUnits.fahrenheit(s.tc).toFixed(1)} degrees Fahrenheit. Tank ${displayUnits.fahrenheit(s.tt).toFixed(1)} degrees Fahrenheit. Pump ${s.on?"on":"off"}. Flow ${displayUnits.usGpm(s.flow, scenario.config.water_density_kg_m3).toFixed(2)} US gallons per minute. ${watts(s.transfer)} flowing ${s.transfer<0?"to collector":"to tank"} now. ${q("[data-tank-net-label]").textContent}: ${q("[data-tank-net]").textContent}. Tank energy change since start: ${q("[data-tank-energy]").textContent}.`;
  }
  function stop() {
    playing=false; playButton.textContent="Play simulation";
    if (frameId) cancelAnimationFrame(frameId);
    frameId=0; render(); announce();
  }
  function tick(now) {
    if (!playing || !root.isConnected) return;
    const delta = Math.min(.1, (now-lastFrame)/1000);
    lastFrame=now;
    time=Math.min(scenario.config.duration_s,time+delta*speed);
    if (!reducedMotion.matches && sampleScenario(scenario,time).on) phase+=delta;
    render();
    if (time>=scenario.config.duration_s) stop();
    else frameId=requestAnimationFrame(tick);
  }
  function play() {
    if(time>=scenario.config.duration_s) time=0;
    playing=true; playButton.textContent="Pause simulation";
    lastFrame=performance.now(); frameId=requestAnimationFrame(tick); render(); announce();
  }

  payload.scenarios.forEach(s => {
    const option=document.createElement("option"); option.value=s.id; option.textContent=s.name;
    picker.appendChild(option);
  });
  picker.value=scenario.id;
  picker.addEventListener("change",()=>{
    scenario=payload.scenarios.find(s=>s.id===picker.value);
    time=Math.min(time,scenario.config.duration_s); slider.max=scenario.config.duration_s;
    updatePlaybackLabels(); buildDiagram(); announce();
  });
  slider.max=scenario.config.duration_s;
  updatePlaybackLabels();
  slider.addEventListener("input",()=>{stop();time=Number(slider.value);render();});
  slider.addEventListener("change",announce);
  playButton.addEventListener("click",()=>playing?stop():play());
  q("[data-speed]").addEventListener("change",e=>{speed=Number(e.target.value);});
  new ResizeObserver(buildDiagram).observe(q(".heat-stage"));
  buildDiagram();
  root.heatPlayback={sample:()=>sampleScenario(scenario,time),seek:t=>{stop();time=Math.max(0,Math.min(t,scenario.config.duration_s));render();},play,pause:stop};
}());
