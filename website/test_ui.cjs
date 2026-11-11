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

test("local scenario opens empty numeric fields and submits engine JSON", async () => {
  const html = fs.readFileSync(__dirname + "/dist/index.html", "utf8");
  const elements = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map((match) => [match[1], new Element()]));
  elements.model.value = "mechanical_power";
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
      if (request.scenario) return response({
        status: "needs_values", route: "mechanical_power", cases: {}, result: null,
      });
      return response({
        status: "evaluated", route: "mechanical_power", cases: {mechanical_power: request.case},
        result: {title: "Walking", verdict: {status: "FEASIBLE / NOT REJECTED"},
          calculations: {claimed_electrical_output_kw: .005, reversible_power_limit_kw: .008}},
      });
    },
  });
  vm.runInContext(fs.readFileSync(__dirname + "/dist/app.js", "utf8"), context);
  elements.scenario.value = "Generating electricity by walking";
  elements["text-form"].fire("submit");
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(elements.status.textContent, "Enter values");
  assert.equal(elements["model-form"].hidden, false);
  const inputs = elements.fields.children.flatMap((label) => label.children);
  assert.ok(inputs.every((input) => input.value === ""));
  inputs.find((input) => input.name === "recoverable_mechanical_power_kw").value = "8";
  inputs.find((input) => input.name === "W_out_kw").value = "5";
  elements["model-form"].fire("submit");
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(submitted.length, 2);
  assert.deepEqual(submitted[1].case, {model: "mechanical_power",
    recoverable_mechanical_power_kw: .008, W_out_kw: .005});
  assert.equal(elements.status.textContent, "Feasible");
  assert.equal(submits[0].disabled, false);
  vm.runInContext('openModel("mechanical_steps")', context);
  elements["model-form"].fire("submit");
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(submitted[2].case.events_per_s, 2);
  assert.equal(submitted[2].case.W_out_kw, .005);
  const optionalInputs = elements.fields.children.flatMap((label) => label.children);
  optionalInputs.find((input) => input.name === "heat_rejected_kw").value = "3";
  optionalInputs.find((input) => input.name === "heat_rejection_temperature_K").value = "26.85";
  elements["model-form"].fire("submit");
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(submitted[3].case.heat_rejected_kw, .003);
  assert.equal(submitted[3].case.heat_rejection_temperature_K, 300);
  context.fetch = async () => response({
    status: "evaluated", route: "mechanical_power",
    cases: {mechanical_power: {model: "mechanical_power", recoverable_mechanical_power_kw: .008, W_out_kw: .005}},
    source_quotes: {W_out_kw: "5 W", recoverable_mechanical_power_kw: "8 W"},
    result: {title: "Automatic walking result", verdict: {status: "FEASIBLE / NOT REJECTED"},
      calculations: {claimed_electrical_output_kw: .005, reversible_power_limit_kw: .008}},
    calculation_code: [{name: "analyse_mechanical_power", source: "def analyse_mechanical_power(case):"}],
  });
  elements["text-form"].fire("submit");
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(elements.status.textContent, "Feasible");
  const populated = elements.fields.querySelectorAll();
  assert.equal(populated.find((input) => input.name === "W_out_kw").value, 5);
  const textOf = (el) => el.textContent + el.children.map(textOf).join(" ");
  assert.match(textOf(elements.result), /View calculation code/);
  assert.match(textOf(elements.result), /def analyse_mechanical_power/);
});
