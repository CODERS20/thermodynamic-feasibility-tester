const $ = (id) => document.getElementById(id);
const number = new Intl.NumberFormat(undefined, { maximumSignificantDigits: 5 });
const models = {
  mechanical_power: {
    name: "Walking generator — electricity from steps",
    fields: [["recoverable_mechanical_power_kw", "Mechanical power available (W)", 8, 0, undefined, .001],
      ["W_out_kw", "Claimed electrical output (W)", 5, 0, undefined, .001],
      ["heat_rejected_kw", "Measured heat loss (W, optional)", "", 0, undefined, .001],
      ["heat_rejection_temperature_K", "Heat rejection temperature (°C, optional)", "", -273.149, undefined, 1, 273.15]],
    note: "For full balances, treat the entered mechanical power as actual generator input. The steady generator rejects all remaining power as heat. Enter its heat-rejection temperature to calculate entropy generation, and measured heat loss to independently check energy conservation.",
  },
  mechanical_steps: {
    name: "Walking generator — energy per step and walking rate",
    engineModel: "mechanical_power",
    fields: [["recoverable_energy_per_event_j", "Energy recovered per step (J)", 4, 0],
      ["events_per_s", "Walking rate (steps/min)", 120, 0, undefined, 1/60],
      ["W_out_kw", "Claimed electrical output (W)", 5, 0, undefined, .001],
      ["heat_rejected_kw", "Measured heat loss (W, optional)", "", 0, undefined, .001],
      ["heat_rejection_temperature_K", "Heat rejection temperature (°C, optional)", "", -273.149, undefined, 1, 273.15]],
    note: "The input limit is recovered energy per step multiplied by the number of steps per second.",
  },
  finite_stream_engine: {
    name: "Heat recovery — cooling a hot stream and warming a cold stream",
    fields: [
      ["hot_stream.mass_flow_kg_s", "Hot-stream flow (kg/s)", .3, .000001],
      ["hot_stream.T_in_K", "Hot-stream inlet (°C)", 57.746972594, -273.149, undefined, 1, 273.15],
      ["hot_stream.T_out_K", "Hot-stream outlet (°C)", 45, -273.149, undefined, 1, 273.15],
      ["hot_stream.cp_kj_kg_k", "Hot-stream heat capacity (kJ/kg K)", 4.184, .000001],
      ["cold_stream.mass_flow_kg_s", "Cold-stream flow (kg/s)", .6, .000001],
      ["cold_stream.T_in_K", "Cold-stream inlet (°C)", 25, -273.149, undefined, 1, 273.15],
      ["cold_stream.T_out_K", "Cold-stream outlet (°C)", 30.975201983, -273.149, undefined, 1, 273.15],
      ["cold_stream.cp_kj_kg_k", "Cold-stream heat capacity (kJ/kg K)", 4.184, .000001],
      ["W_out_kw", "Claimed electrical output (kW)", .999852941176, 0],
    ],
    note: "Constant heat capacities, steady adiabatic boundary, negligible pressure loss. The effective-temperature comparison applies to these specified stream changes.",
  },
  fixed_reservoir_engine: {
    name: "Heat engine — fixed hot and cold temperatures",
    fields: [["T_hot_K", "Hot temperature (K)", 600, .001], ["T_cold_K", "Cold temperature (K)", 300, .001],
      ["Q_hot_kw", "Heat supplied (kW)", 100, .001], ["W_out_kw", "Claimed power (kW)", 30, 0]],
    note: "The Carnot ceiling uses absolute temperatures. Rejected heat is inferred from the First Law.",
  },
  assignment_base: {
    name: "Coffee from GPU waste heat — Base assignment",
    fields: [["suffix", "Roll-number suffix", 100, 0, 399]],
    note: "Computes both stream temperatures and the strict reversible ceiling for the coffee maker.",
  },
  assignment_modified: {
    name: "Coffee from an ORC and wax sink — Modified assignment",
    fields: [["suffix", "Roll-number suffix", 100, 1, 400]],
    note: "Uses the gas heat-capacity model and an isothermal melting-wax sink.",
  },
  solar_blackbody: {
    name: "Solar electricity — ideal radiation limit",
    fields: [["T_source_K", "Source temperature (K)", 6000, .001], ["T_ambient_K", "Ambient temperature (K)", 300, .001],
      ["irradiance_W_m2", "Irradiance (W/m²)", 1000, 0], ["collection_area_m2", "Collection area (m²)", 2, .0001],
      ["W_out_kw", "Claimed power (kW)", 1.8, 0]],
    note: "Uses the Petela–Landsberg limit for ideal radiation at the stated conditions.",
  },
  reaction_gibbs: {
    name: "Fuel cell — electricity from a chemical reaction",
    fields: [["reaction_direction", "Reaction direction", "H₂ + ½O₂ → H₂O(l)"],
      ["delta_G_kj_per_mol_rxn", "ΔG (kJ/mol reaction)", -237.141],
      ["reaction_rate_mol_rxn_s", "Forward rate (mol/s)", .01, .000001], ["W_out_kw", "Claimed power (kW)", 2, 0]],
    note: "Supply the signed Gibbs energy for the stated conditions and direction.",
  },
};
const examples = [
  ["01 · MECHANICAL", "Walking harvester", "Recoverable energy per step and electrical output.", "mechanical_power"],
  ["02 · THERMAL", "Heat engine", "Compare a power claim with the Carnot ceiling.", "fixed_reservoir_engine"],
  ["03 · CL 202", "GPU waste heat", "Base assignment with two finite water streams.", "assignment_base"],
  ["04 · CL 202", "ORC and wax sink", "Modified assignment with gas cooling and wax melting.", "assignment_modified"],
  ["05 · RADIATION", "Solar converter", "Find the upper limit for ideal blackbody radiation.", "solar_blackbody"],
  ["06 · CHEMICAL", "Hydrogen fuel cell", "Compare output with the signed Gibbs energy limit.", "reaction_gibbs"],
];
const engineLabels = {
  claimed_electrical_output_kw: "Claimed electrical power (kW)", reversible_power_limit_kw: "Ideal power limit (kW)",
  reversible_work_limit_kw: "Reversible work limit (kW)", S_gen_dot_kw_per_k: "Entropy generation (kW/K)",
  petela_landsberg_exergy_fraction: "Radiation exergy fraction", incident_radiation_kw: "Incident radiation (kW)",
  first_law: "First Law", second_law: "Second Law", process_classification: "Process classification",
  performance_limit: "Useful power limit", first_law_balance: "Energy accounting",
  entropy_balance: "Entropy accounting", input_energy_limit: "Input energy limit",
  heat_rejection_basis: "Heat-loss data",
};

let revision = 0;
const fromFile = location.protocol === "file:";
const hosted = location.hostname?.endsWith(".github.io") === true;
let browserWorker;
let browserRequest = 0;

function element(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}

function makeFields(blank = false) {
  const model = models[$("model").value];
  $("fields").replaceChildren(...model.fields.map(([key, label, value, min, max]) => {
    const group = element("label", label);
    const input = element("input");
    input.name = key;
    input.value = blank ? "" : value;
    input.placeholder = String(value);
    const optional = value === "";
    input.required = !optional;
    if (typeof value === "number" || optional) {
      input.type = "number";
      input.step = key === "suffix" ? "1" : "any";
      if (min !== undefined) input.min = min;
      if (max !== undefined) input.max = max;
    } else input.maxLength = 300;
    group.append(input);
    return group;
  }));
  $("model-note").textContent = model.note;
}

function setStatus(label, type = "") {
  $("status").textContent = label;
  $("status").className = "badge " + type;
}

function clearOutput() {
  revision++;
  setStatus("Ready");
  const empty = element("div", undefined, "empty");
  empty.append(element("span", "◎", "empty-icon"), element("h3", "Your results appear here"),
    element("p", "Run a scenario to compare claimed output with the ideal limit and see which checks apply."));
  $("result").replaceChildren(empty);
}

function setMode(isText, preserveResult = false) {
  $("text-form").hidden = !isText;
  $("model-form").hidden = isText;
  $("text-tab").setAttribute("aria-pressed", isText);
  $("model-tab").setAttribute("aria-pressed", !isText);
  if (!preserveResult) clearOutput();
}

function fillValues(route, values) {
  if (!models[route]) return;
  $("model").value = route;
  makeFields(true);
  for (const [key, , , , , scale = 1, offset = 0] of models[route].fields) {
    const value = key in values ? values[key] : key.split(".").reduce((item, part) => item?.[part], values);
    if (value === undefined || value === null) continue;
    const input = [...$("fields").querySelectorAll("input")].find((item) => item.name === key);
    if (input) input.value = typeof value === "number" ? Number(((value - offset) / scale).toPrecision(12)) : value;
  }
}

async function runEngine(request) {
  if (fromFile) throw new Error("Start the site with python website/serve.py, then open http://127.0.0.1:8000.");
  if (hosted) {
    browserWorker ??= new Worker("engine-worker.js?v=20261111-3");
    const worker = browserWorker;
    const id = ++browserRequest;
    return new Promise((resolve, reject) => {
      const finish = (action, value) => {
        clearTimeout(timer);
        worker.removeEventListener("message", receive);
        worker.removeEventListener("error", failed);
        action(value);
      };
      const receive = ({data}) => { if (data.id === id) finish(resolve, data.result); };
      const failed = () => {
        worker.terminate();
        if (browserWorker === worker) browserWorker = null;
        finish(reject, new Error("The browser Python engine did not start. Check your connection and retry."));
      };
      const timer = setTimeout(failed, 90000);
      worker.addEventListener("message", receive);
      worker.addEventListener("error", failed);
      worker.postMessage({id, request});
    });
  }
  const response = await fetch("./api/solve", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(request), signal: AbortSignal.timeout(10000)});
  if (!response.headers.get("content-type")?.includes("application/json")) {
    throw new Error("Open the site using python website/serve.py. This page needs the local calculation server.");
  }
  return response.json();
}

function outputValues(result, cases) {
  const calc = result.calculations || result;
  const input = Object.values(cases).at(-1);
  const claimed = calc["Claimed electrical output (kW)"] ?? calc.claimed_electrical_output_kw ?? input?.W_out_kw;
  const limit = calc["Strict reversible power ceiling (kW)"] ?? calc["Reversible power ceiling (kW)"]
    ?? calc.reversible_power_limit_kw ?? calc.reversible_work_limit_kw ?? calc.effective_temperature_work_reference_kw;
  return { calc, claimed, limit };
}

function pretty(value) {
  if (typeof value === "number") return number.format(value);
  if (value === null || value === undefined) return "Unavailable";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function details(title, body) {
  const section = element("details");
  section.append(element("summary", title), body);
  return section;
}

function dataList(data) {
  const list = element("dl");
  for (const [name, value] of Object.entries(data)) {
    list.append(element("dt", engineLabels[name] || name.replaceAll("_", " ")), element("dd", pretty(value)));
  }
  return list;
}

function render(data) {
  const output = $("result");
  output.replaceChildren();
  if (data.error) {
    setStatus("Check input", "fail");
    const message = element("div", undefined, "verdict");
    message.append(element("h3", "Could not run the calculation"), element("p", data.error));
    output.append(message);
    return;
  }
  if (data.status === "needs_values") {
    const route = data.route;
    setMode(false);
    if (models[route]) $("model").value = route;
    makeFields(true);
    fillValues(route, data.prefill || {});
    setStatus("Enter values", "wait");
    const message = element("div", undefined, "verdict");
    message.append(element("h3", "Enter the numbers for your scenario"),
      element("p", route ? "Suggested model: " + models[route].name + ". Review the model, fill in the labeled fields, and click Calculate result." : "Choose the model that matches your process, then enter its values."));
    output.replaceChildren(message);
    if (data.issues?.length) output.append(element("p", data.issues.join(" "), "form-note"));
    $("model").focus({preventScroll: true});
    return;
  }
  const { result, cases } = data;
  if (Object.keys(data.source_quotes || {}).length) {
    const populated = Object.values(cases).at(-1);
    let route = data.route;
    if (route === "mechanical_power" && populated?.events_per_s !== undefined) route = "mechanical_steps";
    if (data.route.startsWith("assignment_")) {
      fillValues(route, {suffix: Number(data.source_quotes.suffix)});
    } else fillValues(route, populated);
  }
  const code = result.verdict?.status || result.Verdict;
  const feasible = code === "FEASIBLE / NOT REJECTED";
  const rejected = code === "NOT FEASIBLE";
  setStatus(feasible ? "Feasible" : rejected ? "Not feasible" : code === "PROPERTY CALCULATION ONLY" ? "Properties only" : "Model required",
    feasible ? "pass" : rejected ? "fail" : "wait");
  const verdict = element("div", undefined, "verdict");
  verdict.append(element("h3", result.title || models[data.route]?.name || data.route.replaceAll("_", " ")));
  const reason = result.verdict?.reasons?.[0] || result.Reason;
  if (reason) verdict.append(element("p", reason));
  output.append(verdict);
  if (Object.keys(data.source_quotes || {}).length) {
    const review = element("button", "Review automatically filled values", "quiet");
    review.type = "button";
    review.addEventListener("click", () => setMode(false, true));
    output.append(review);
  }
  const { calc, claimed, limit } = outputValues(result, cases);
  if (Number.isFinite(claimed) && Number.isFinite(limit)) {
    const watts = Math.max(Math.abs(claimed), Math.abs(limit)) < 1;
    const power = (value) => number.format(value * (watts ? 1000 : 1)) + (watts ? " W" : " kW");
    const metrics = element("div", undefined, "metrics");
    for (const [label, value] of [["Claimed output", claimed], ["Ideal ceiling", limit]]) {
      const card = element("div", label, "metric");
      card.append(element("strong", power(value)));
      metrics.append(card);
    }
    output.append(metrics);
    const chart = element("div", undefined, "comparison");
    for (const [label, value] of [["Ceiling", limit], ["Claim", claimed]]) {
      const row = element("div", undefined, "bar-row");
      const track = element("div", undefined, "track");
      const bar = element("i");
      bar.style.width = (100 * Math.max(0, value) / Math.max(claimed, limit, Number.MIN_VALUE)) + "%";
      track.append(bar);
      row.append(element("span", label), track, element("span", power(value)));
      chart.append(row);
    }
    output.append(chart);
  }
  if (result.checks) output.append(details("Balance and limit checks", dataList(result.checks)));
  output.append(details("All calculated values", dataList(calc)));
  if (result.assumptions?.length) {
    const assumptions = element("ul");
    for (const assumption of result.assumptions) assumptions.append(element("li", assumption));
    output.append(details("Model assumptions", assumptions));
  }
  if (Object.keys(data.source_quotes || {}).length) output.append(details("What the tester extracted", dataList(data.source_quotes)));
  const jsonBody = element("div");
  const files = Object.entries(cases);
  jsonBody.append(element("pre", JSON.stringify(files.length === 1 ? files[0][1] : cases, null, 2)));
  for (const [name, content] of files) {
    const download = element("button", files.length === 1 ? "Download case JSON" : "Download " + name.replaceAll("_", " "), "quiet");
    download.type = "button";
    download.addEventListener("click", () => {
      const url = URL.createObjectURL(new Blob([JSON.stringify(content, null, 2)], {type: "application/json"}));
      const link = element("a");
      link.href = url;
      link.download = name + ".json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    jsonBody.append(download);
  }
  output.append(details("Engine input JSON", jsonBody));
  if (data.calculation_code?.length) {
    const codeBody = element("div");
    codeBody.append(element("p", "These functions come from the local Python engine. The inputs are shown in Engine input JSON."));
    for (const item of data.calculation_code) {
      codeBody.append(element("h4", item.name), element("pre", item.source));
    }
    for (const [file, label] of [["engine", "Download full calculation engine"],
      ["parser", "Download local scenario parser"], ["assignments", "Download assignment calculations"]]) {
      const link = element("a", label, "quiet");
      const paths = {engine: "thermodynamic_feasibility_tester_MASTER.py",
        parser: "website/local_scenarios.py", assignments: "run_mock_assignments.py"};
      link.href = hosted ? "./python/" + paths[file] : "./api/source/" + file;
      link.download = "";
      codeBody.append(link);
    }
    output.append(details("View calculation code", codeBody));
  }
}

async function analyze(request) {
  const current = ++revision;
  const submits = document.querySelectorAll("form button[type=submit]");
  submits.forEach((button) => button.disabled = true);
  const originalLabels = [...submits].map((button) => button.innerHTML);
  submits.forEach((button) => button.textContent = "Analyzing…");
  setStatus("Calculating…", "wait");
  $("result").replaceChildren(element("p", hosted
    ? "Running Python in your browser. The first calculation downloads the engine and may take a moment."
    : "Running the thermodynamics engine…", "form-note"));
  try {
    const response = await runEngine(request);
    if (current === revision) render(response);
  } catch (error) {
    if (current === revision) {
      render({error: error.name === "TimeoutError" ? "The local server took too long to respond. Restart python website/serve.py and retry." : error.message});
    }
  } finally {
    submits.forEach((button, index) => { button.disabled = false; button.innerHTML = originalLabels[index]; });
  }
}

for (const [id, spec] of Object.entries(models)) {
  const option = element("option", spec.name);
  option.value = id;
  $("model").append(option);
}
makeFields(true);
function openModel(model) {
  setMode(false);
  $("model").value = model;
  makeFields();
  $("model").focus({ preventScroll: true });
  $("workbench").scrollIntoView();
}

for (const [kicker, title, description, model] of examples) {
  const card = element("button", undefined, "example");
  card.type = "button";
  card.append(element("span", kicker, "eyebrow"), element("strong", title), element("small", description));
  card.addEventListener("click", () => openModel(model));
  $("example-list").append(card);
}
$("text-tab").addEventListener("click", () => setMode(true));
$("model-tab").addEventListener("click", () => setMode(false));
$("model").addEventListener("change", () => { makeFields(true); clearOutput(); });
$("reset").addEventListener("click", () => { $("scenario").value = ""; clearOutput(); $("scenario").focus(); });
$("text-form").addEventListener("submit", (event) => {
  event.preventDefault();
  analyze({scenario: $("scenario").value.trim()});
});
$("model-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const model = $("model").value;
  const inputs = new FormData(event.target);
  const spec = models[model];
  const caseData = {model: spec.engineModel || model};
  for (const [key, , value, , , scale = 1, offset = 0] of spec.fields) {
    const raw = inputs.get(key);
    if (value === "" && (raw === null || String(raw).trim() === "")) continue;
    if (raw === null || String(raw).trim() === "") {
      render({error: "Fill in every labeled value before calculating."});
      return;
    }
    const parsed = typeof value === "number" || value === "" ? Number(raw) * scale + offset : raw.trim();
    if (key.includes(".")) {
      const [group, field] = key.split(".");
      caseData[group] ??= {name: group.replace("_", " "), cp_model: "constant"};
      caseData[group][field] = parsed;
    } else caseData[key] = parsed;
  }
  if (model === "finite_stream_engine") caseData.apply_effective_temperature_limit = true;
  analyze({case: caseData});
});
$("interface-loading").hidden = true;
$("analyze-button").disabled = false;
