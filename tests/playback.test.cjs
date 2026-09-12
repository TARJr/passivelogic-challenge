const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {sampleScenario} = require('../solar_thermal/templates/playback.js');

const config = {
  collector_area_m2:4, optical_efficiency:.75, water_cp_j_kgk:4180,
  water_density_kg_m3:1000, tank_volume_l:200, initial_tank_c:20,
  collector_loss_w_m2k:5, tank_loss_w_k:2, ambient_c:20, mass_flow_kg_s:.03
};
const scenario = {
  config,
  samples:[[0,20,20,0],[10,40,30,800],[20,25,35,0]],
  events:[{time_s:0,pump_on:false},{time_s:5,pump_on:true},{time_s:18,pump_on:false}]
};

test('interpolates temperatures and solar forcing, with the correct heat rate', () => {
  const s=sampleScenario(scenario,7.5);
  assert.equal(s.tc,35); assert.equal(s.tt,27.5); assert.equal(s.radiation,600);
  assert.equal(s.absorbed,1800);
  assert.ok(Math.abs(s.transfer-940.5)<1e-9);
  assert.equal(s.collectorLoss,300); assert.equal(s.tankLoss,15);
});

test('pump switch is right-continuous and not smeared between samples',()=>{
  assert.equal(sampleScenario(scenario,4.999999).transfer,0);
  assert.equal(sampleScenario(scenario,5).on,true);
  assert.equal(sampleScenario(scenario,17.999).on,true);
  assert.equal(sampleScenario(scenario,18).on,false);
  assert.equal(sampleScenario(scenario,18).transfer,0);
});

test('reverse heat transfer retains forward water flow',()=>{
  const s=sampleScenario(scenario,17);
  assert.equal(s.flow,.03);
  assert.ok(s.transfer<0);
  assert.ok(Math.abs(s.transfer-(-501.6))<1e-9);
});

test('tank energy is computed from capacity, not its temperature colour',()=>{
  assert.equal(sampleScenario(scenario,10).tankEnergyKwh,836000*10/3600000);
  assert.equal(sampleScenario(scenario,0).tankEnergyKwh,0);
});

test('playback cannot extrapolate outside simulated time',()=>{
  assert.equal(sampleScenario(scenario,-100).time,0);
  assert.equal(sampleScenario(scenario,9999).time,20);
  assert.equal(sampleScenario(scenario,9999).tt,35);
});

test('generated real scenarios preserve exact pump events and temperatures',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../results/index.html'),'utf8');
  const match=html.match(/<script type="application\/json" data-payload>([\s\S]*?)<\/script>/);
  assert.ok(match,'Run python run.py to generate the playback data');
  const payload=JSON.parse(match[1]);
  for(const scenario of payload.scenarios){
    for(const event of scenario.events){
      const state=sampleScenario(scenario,event.time_s);
      assert.equal(state.on,event.pump_on);
      assert.equal(state.tc,event.collector_c);
      assert.equal(state.tt,event.tank_c);
    }
  }
});
