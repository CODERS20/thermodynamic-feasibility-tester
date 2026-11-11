const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const test = require("node:test");

class Element {
  constructor() {
    this.children = [];
    this.handlers = {};
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.style = {};
    this.textContent = "";
    this.innerHTML = "";
  }
  append(...children) {
    for (const child of children) {
      child.parentElement = this;
      this.children.push(child);
    }
  }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  focus() {}
  scrollIntoView() {}
  querySelectorAll() { return this.children.flatMap((child) => child.children); }
  fire(name) { return this.handlers[name]({ preventDefault() {}, target: this }); }
}

/* Boot app.js against a bare DOM and return the pieces a test needs. */
function boot(responder) {
  const html = fs.readFileSync(__dirname + "/dist/index.html", "utf8");
  const elements = Object.fromEntries(
    [...html.matchAll(/id="([^"]+)"/g)].map((match) => [match[1], new Element()]));
  const submitted = [];
  const submits = [new Element(), new Element()];
  const response = (value) => ({
    ok: true, headers: {get: () => "application/json"}, json: async () => value,
  });
  const context = vm.createContext({
    document: {getElementById: (id) => elements[id], createElement: () => new Element(),
      querySelectorAll: () => submits},
    location: {protocol: "http:"}, Intl, setTimeout, clearTimeout, AbortSignal,
    FormData: class {
      get(name) {
        const inputs = elements.fields.children.flatMap((label) => label.children);
        return inputs.find((input) => input.name === name)?.value ?? null;
      }
    },
    fetch: async (url, options) => {
      assert.equal(url, "./api/solve");
      const request = JSON.parse(options.body);
      submitted.push(request);
      return response(responder(request));
    },
  });
  vm.runInContext(fs.readFileSync(__dirname + "/dist/app.js", "utf8"), context);
  return {elements, submitted, submits, context};
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 5));
const inputsOf = (elements) => elements.fields.children.flatMap((label) => label.children);
const setField = (elements, name, value) => {
  const input = inputsOf(elements).find((item) => item.name === name);
  assert.ok(input, `no input named ${name}`);
  input.value = value;
};

const evaluated = (result) => ({
  status: "evaluated", route: "flowchart_mechanical_generic",
  cases: {flowchart: {}}, result,
});
const WORK_RESULT = {
  title: "Work - generic work input",
  verdict: {status: "FEASIBLE"},
  calculations: {E_in_W: 8, W_actual_W: 5, S_gen_W_per_K: 0.01, second_law_efficiency_fraction: 0.625},
};

test("the app boots straight into the guided wizard", async () => {
  const {elements, submitted} = boot(() => evaluated(WORK_RESULT));
  assert.equal(elements["model-form"].hidden, false,
    "guided mode is the only input surface and must be visible on load");
  assert.ok(inputsOf(elements).length > 0, "fields must be built on boot");
  assert.equal(submitted.length, 0, "booting must not call the engine");
});

test("guided mode posts flowchart parameters, not legacy model cases", async () => {
  const {elements, submitted, context} = boot(() => evaluated(WORK_RESULT));

  vm.runInContext('openModel("work_generic")', context);
  setField(elements, "W_input", "8");
  setField(elements, "W_actual", "5");
  setField(elements, "T_0", "300");
  elements["model-form"].fire("submit");
  await settle();

  const request = submitted.at(-1);
  assert.ok(request.flowchart, "guided mode must post a flowchart payload");
  assert.equal(request.case, undefined, "the legacy case payload must be gone");
  assert.deepEqual(request.flowchart,
    {domain: "mechanical", work_type: "generic", W_input: 8, W_actual: 5, T_0: 300});
  assert.equal(elements.status.textContent, "Feasible");
});

test("each flowchart domain carries its own routing keys", async () => {
  const cases = [
    ["thermal_cycle", {domain: "thermal", process_type: "cycle"},
      {Q_in: "1000", T_source: "800", W_actual: "400", T_0: "300"}],
    ["chemical_gibbs", {domain: "chemical", data_type: "gibbs"},
      {delta_G: "-237141", delta_H: "-285830", W_actual: "200000", T_0: "298.15"}],
    ["work_shaft", {domain: "mechanical", work_type: "shaft"},
      {torque: "5", omega: "20", W_actual: "80", T_0: "300"}],
    ["solar_radiative", {domain: "solar"},
      {Q_sun: "1000", T_sun: "5778", W_actual: "800", T_0: "300"}],
  ];
  for (const [model, routing, values] of cases) {
    const {elements, submitted, context} = boot(() => evaluated(WORK_RESULT));
    vm.runInContext(`openModel(${JSON.stringify(model)})`, context);
    for (const [name, value] of Object.entries(values)) setField(elements, name, value);
    elements["model-form"].fire("submit");
    await settle();
    const sent = submitted.at(-1).flowchart;
    for (const [key, value] of Object.entries(routing)) {
      assert.equal(sent[key], value, `${model} must send ${key}=${value}`);
    }
    for (const name of Object.keys(values)) {
      assert.equal(typeof sent[name], "number", `${model}.${name} must be numeric`);
    }
  }
});

test("nested state fields group without legacy engine keys", async () => {
  const {elements, submitted, context} = boot(() => evaluated(WORK_RESULT));
  vm.runInContext('openModel("thermal_steady_flow")', context);
  for (const [name, value] of Object.entries({
    mass_flow: "1", cp: "1005", "state1.T": "800", "state2.T": "500",
    W_actual: "100000", T_0: "300",
  })) setField(elements, name, value);
  elements["model-form"].fire("submit");
  await settle();

  const sent = submitted.at(-1).flowchart;
  assert.deepEqual(sent.state1, {T: 800});
  assert.deepEqual(sent.state2, {T: 500});
  assert.equal(sent.cp_model, undefined, "cp_model belonged to the old engine");
  assert.equal(sent.apply_effective_temperature_limit, undefined);
});

test("optional fields are omitted when left blank", async () => {
  const {elements, submitted, context} = boot(() => evaluated(WORK_RESULT));
  vm.runInContext('openModel("thermal_steady_flow")', context);
  for (const [name, value] of Object.entries({
    mass_flow: "1", cp: "1005", "state1.T": "800", "state2.T": "500",
    W_actual: "100000", T_0: "300",
  })) setField(elements, name, value);
  elements["model-form"].fire("submit");
  await settle();
  let sent = submitted.at(-1).flowchart;
  assert.equal(sent.sink_T_in, undefined, "a blank optional field must not be sent");

  setField(elements, "sink_T_in", "298.15");
  setField(elements, "sink_T_out", "304.13");
  elements["model-form"].fire("submit");
  await settle();
  sent = submitted.at(-1).flowchart;
  assert.equal(sent.sink_T_in, 298.15);
  assert.equal(sent.sink_T_out, 304.13);
});
