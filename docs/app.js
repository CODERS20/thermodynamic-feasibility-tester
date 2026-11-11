const $ = (id) => document.getElementById(id);
const number = new Intl.NumberFormat(undefined, { maximumSignificantDigits: 5 });
const models = {
  // Every leaf of the project flowchart. Quantities are SI: W, J/K, K, kg/s.
  // `flow` carries the fixed routing the flowchart decides before any input.
  thermal_cycle: {
    name: "Thermal fluid \u2014 full thermodynamic cycle",
    flow: {domain: "thermal", process_type: "cycle"},
    fields: [["Q_in", "Heat input Q_in (W)", 1000, 0],
      ["T_source", "Source temperature T_source (K)", 800, .001],
      ["W_actual", "Claimed work output W_actual (W)", 400, 0],
      ["T_0", "Ambient sink temperature T_0 (K)", 300, .001]],
    note: "The fluid returns to its initial state, so \u0394S_sys = 0. E_in = Q_in and Entropy_in = Q_in / T_source.",
  },
  thermal_steady_flow: {
    name: "Thermal fluid \u2014 steady flow component",
    flow: {domain: "thermal", process_type: "steady_flow"},
    fields: [["mass_flow", "Mass flow rate (kg/s)", 1, .000001],
      ["cp", "Specific heat Cp (J/kg\u00b7K)", 1005, .000001],
      ["state1.T", "Inlet temperature T\u2081 (K)", 800, .001],
      ["state2.T", "Outlet temperature T\u2082 (K)", 500, .001],
      ["W_actual", "Claimed work output W_actual (W)", 100000, 0],
      ["T_0", "Ambient sink temperature T_0 (K)", 300, .001],
      ["sink_T_in", "Sink stream inlet (K, optional)", "", .001],
      ["sink_T_out", "Sink stream outlet (K, optional)", "", .001]],
    note: "\u0394S_sys = \u1e41(s\u2082 \u2212 s\u2081) and E_in = \u1e41(h\u2081 \u2212 h\u2082). Entropy_in = 0 for an adiabatic device. Supplying the sink stream's own inlet and outlet replaces the infinite-reservoir assumption with its true entropy rise.",
  },
  thermal_closed: {
    name: "Thermal fluid \u2014 closed system process",
    flow: {domain: "thermal", process_type: "closed"},
    fields: [["mass", "Mass (kg)", 2, .000001],
      ["Q_in", "Heat input Q_in (W)", 50000, 0],
      ["T_source", "Source temperature T_source (K)", 700, .001],
      ["state1.T", "Initial temperature T\u2081 (K)", 700, .001],
      ["state2.T", "Final temperature T\u2082 (K)", 400, .001],
      ["cp", "Specific heat Cp (J/kg\u00b7K)", 1005, .000001],
      ["R", "Gas constant R (J/kg\u00b7K)", 287, 0],
      ["W_actual", "Claimed work output W_actual (W)", 100000, 0],
      ["T_0", "Ambient sink temperature T_0 (K)", 300, .001]],
    note: "\u0394S_sys = m(s\u2082 \u2212 s\u2081) and E_in = m(u\u2081 \u2212 u\u2082) + Q_in, with Entropy_in = Q_in / T_source. R gives the internal-energy term for an ideal gas.",
  },
  chemical_hs: {
    name: "Chemical reaction \u2014 standard enthalpy and entropy",
    flow: {domain: "chemical", data_type: "enthalpy_entropy"},
    fields: [["delta_H", "Enthalpy of reaction \u0394H (J)", -285830],
      ["delta_S", "Entropy of reaction \u0394S (J/K)", -163.3],
      ["W_actual", "Claimed work output W_actual (W)", 200000, 0],
      ["T_0", "Ambient sink temperature T_0 (K)", 298.15, .001]],
    note: "\u0394S_sys = \u0394S and E_in = |\u0394H|. Chemical potential is stored internally, so Entropy_in = 0.",
  },
  chemical_gibbs: {
    name: "Chemical reaction \u2014 Gibbs free energy",
    flow: {domain: "chemical", data_type: "gibbs"},
    fields: [["delta_G", "Gibbs energy \u0394G (J)", -237141],
      ["delta_H", "Enthalpy of reaction \u0394H (J)", -285830],
      ["W_actual", "Claimed work output W_actual (W)", 200000, 0],
      ["T_0", "Ambient sink temperature T_0 (K)", 298.15, .001]],
    note: "\u0394S_sys = (\u0394H \u2212 \u0394G) / T_0 and E_in = |\u0394H|, with Entropy_in = 0.",
  },
  work_electrical: {
    name: "Work \u2014 electrical",
    flow: {domain: "mechanical", work_type: "electrical"},
    fields: [["V", "Voltage (V)", 120],
      ["I", "Current (A)", 10],
      ["W_actual", "Claimed work output W_actual (W)", 1000, 0],
      ["T_0", "Ambient sink temperature T_0 (K)", 300, .001]],
    note: "E_in = V \u00d7 I. Pure work carries no entropy, so \u0394S_sys = 0 and Entropy_in = 0.",
  },
  work_kinetic: {
    name: "Work \u2014 kinetic fluid",
    flow: {domain: "mechanical", work_type: "kinetic"},
    fields: [["mass_flow", "Mass flow rate (kg/s)", 1.2, .000001],
      ["v", "Velocity (m/s)", 10, 0],
      ["W_actual", "Claimed work output W_actual (W)", 40, 0],
      ["T_0", "Ambient sink temperature T_0 (K)", 300, .001]],
    note: "E_in = \u00bd \u1e41 v\u00b2. Pure work carries no entropy.",
  },
  work_potential: {
    name: "Work \u2014 potential gravity",
    flow: {domain: "mechanical", work_type: "potential"},
    fields: [["mass_flow", "Mass flow rate (kg/s)", 2, .000001],
      ["height", "Height drop z (m)", 30, 0],
      ["W_actual", "Claimed work output W_actual (W)", 400, 0],
      ["T_0", "Ambient sink temperature T_0 (K)", 300, .001]],
    note: "E_in = \u1e41 g z, with g = 9.80665 m/s\u00b2. Pure work carries no entropy.",
  },
  work_shaft: {
    name: "Work \u2014 shaft rotational",
    flow: {domain: "mechanical", work_type: "shaft"},
    fields: [["torque", "Torque \u03c4 (N\u00b7m)", 5],
      ["omega", "Angular velocity \u03c9 (rad/s)", 20],
      ["W_actual", "Claimed work output W_actual (W)", 80, 0],
      ["T_0", "Ambient sink temperature T_0 (K)", 300, .001]],
    note: "E_in = \u03c4 \u03c9. Pure work carries no entropy.",
  },
  work_boundary: {
    name: "Work \u2014 boundary pressure",
    flow: {domain: "mechanical", work_type: "boundary"},
    fields: [["P", "Pressure (Pa)", 2000],
      ["delta_V", "Volume change \u0394V (m\u00b3)", .05],
      ["W_actual", "Claimed work output W_actual (W)", 80, 0],
      ["T_0", "Ambient sink temperature T_0 (K)", 300, .001]],
    note: "E_in = P \u0394V. Pure work carries no entropy.",
  },
  work_generic: {
    name: "Work — generic work input",
    flow: {domain: "mechanical", work_type: "generic"},
    fields: [["W_input", "Recoverable work input (W)", 8, 0],
      ["W_actual", "Claimed work output W_actual (W)", 5, 0],
      ["T_0", "Ambient sink temperature T_0 (K)", 300, .001]],
    note: "E_in is the recoverable work rate you supply. Pure work carries no entropy, so ΔS_sys = 0 and Entropy_in = 0.",
  },
  solar_radiative: {
    name: "Solar \u2014 radiative",
    flow: {domain: "solar"},
    fields: [["Q_sun", "Incident solar power Q_sun (W)", 1000, 0],
      ["T_sun", "Sun temperature T_sun (K)", 5778, .001],
      ["W_actual", "Claimed work output W_actual (W)", 800, 0],
      ["T_0", "Ambient sink temperature T_0 (K)", 300, .001]],
    note: "E_in = Q_sun and Entropy_in = Q_sun / T_sun, because radiation is treated as heat from a reservoir at the sun temperature.",
  },
};
const domains = [
  ["thermal", "Thermal fluid", "Heat from a cycle, a flowing stream, or a fixed mass",
    "What is the process type?", [
      ["thermal_cycle", "Full thermodynamic cycle", "The working fluid returns to its initial state each cycle."],
      ["thermal_steady_flow", "Steady flow component", "Fluid flows through continuously, like a turbine."],
      ["thermal_closed", "Closed system process", "A fixed mass, like gas in a piston."]]],
  ["chemical", "Chemical reaction", "Fuel cells, batteries, combustion",
    "What reaction data do you have?", [
      ["chemical_hs", "Standard enthalpy and entropy", "You know \u0394H and \u0394S of reaction."],
      ["chemical_gibbs", "Gibbs free energy", "You know \u0394G together with \u0394H."]]],
  ["mechanical", "Work \u2014 mechanical or electrical", "Organised energy that carries no entropy",
    "What type of work input?", [
      ["work_electrical", "Electrical", "Voltage and current."],
      ["work_kinetic", "Kinetic fluid", "Moving air or water."],
      ["work_potential", "Potential gravity", "Falling water or a descending mass."],
      ["work_shaft", "Shaft rotational", "Torque and angular velocity."],
      ["work_boundary", "Boundary pressure", "A fluid expanding against a moving boundary."],
      ["work_generic", "Already-known work rate", "You already know the recoverable work in watts."]]],
  ["solar", "Solar radiative", "Incident radiation on a collector", null,
    [["solar_radiative", "Radiation from the sun", ""]]],
];
// The plain-language parser still answers with the original model names, so map
// them onto the flowchart leaf that asks for the same physics.
const nlpRouteToLeaf = {
  fixed_reservoir_engine: "thermal_cycle",
  finite_stream_engine: "thermal_steady_flow",
  solar_blackbody: "solar_radiative",
  reaction_gibbs: "chemical_gibbs",
  mechanical_power: "work_generic",
  mechanical_steps: "work_generic",
};
const engineLabels = {
  E_in_W: "Energy input E_in (W)", delta_S_sys_W_per_K: "System entropy change \u0394S_sys (W/K)",
  entropy_in_W_per_K: "Entropy in (W/K)", Q_out_W: "Rejected heat Q_out (W)",
  entropy_out_W_per_K: "Entropy out (W/K)", S_gen_W_per_K: "Entropy generation S_gen (W/K)",
  W_actual_W: "Claimed work W_actual (W)", lost_work_W: "Lost work W_lost (W)",
  reversible_work_limit_W: "Reversible work limit (W)",
  reversible_efficiency_fraction: "Reversible efficiency \u03b7_rev",
  second_law_efficiency_fraction: "Second-law efficiency \u03b7_II",
  T_0_K: "Ambient sink T_0 (K)", T_H_eff_K: "Effective source temperature (K)",
  T_sink_eff_K: "Effective sink temperature (K)", sink_basis: "Sink basis",
  reversible_limit_basis: "Reversible limit basis",
  first_law: "First Law", second_law: "Second Law (Clausius)",
  process_classification: "Verdict", decision_path: "Decision path",
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

/* "(W, optional)" -> ["Mechanical power available", "W", true] */
function readLabel(label, value) {
  const match = /^(.*?)\s*\(([^)]*)\)\s*$/.exec(label);
  const name = match ? match[1] : label;
  const parts = match ? match[2].split(",").map((part) => part.trim()) : [];
  const optional = value === "" || parts.some((part) => /^optional$/i.test(part));
  return [name, parts.filter((part) => !/^optional$/i.test(part)).join(", "), optional];
}

const defaultModel = Object.keys(models)[0];
function currentModel() {
  return models[$("model").value] ? $("model").value : defaultModel;
}
function makeFields(blank = false) {
  const model = models[currentModel()];
  $("fields").replaceChildren(...model.fields.map(([key, label, value, min, max]) => {
    const [, unit, optional] = readLabel(label, value);
    const group = element("label", undefined, "field-row");
    group.setAttribute("data-unit", unit);
    const input = element("input");
    input.name = key;
    input.value = blank ? "" : value;
    input.placeholder = String(value);
    input.setAttribute("aria-label", label);
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

/* The guided wizard is the only input surface; the argument is kept so the
   existing call sites read unchanged. */
function setMode(_unused, preserveResult = false) {
  $("model-form").hidden = false;
  renderStep();
  if (!preserveResult) clearOutput();
}

/* Guided mode: one question per screen ----------------------------------- */
const wizard = {domain: null, model: null, step: 0};

const domainSpec = (id) => domains.find(([key]) => key === id);
const domainOf = (model) => (domains.find(([, , , , options]) => options.some(([id]) => id === model)) || [null])[0];

function wizardSteps() {
  const steps = [{kind: "domain"}];
  const spec = domainSpec(wizard.domain);
  if (spec && spec[4].length > 1) steps.push({kind: "variant"});
  if (models[wizard.model]) {
    models[wizard.model].fields.forEach((field, index) => steps.push({kind: "field", index}));
    steps.push({kind: "review"});
  }
  return steps;
}

const stepOfField = (index) => wizardSteps().findIndex((step) => step.kind === "field" && step.index === index);
const fieldRow = (index) => [...$("fields").children][index];
const fieldInput = (index) => fieldRow(index)?.children?.[0];

function syncWizardModel(model) {
  if (!models[model]) return;
  wizard.model = model;
  wizard.domain = domainOf(model);
}

function chooseModel(model) {
  if (wizard.model !== model) {
    wizard.model = model;
    $("model").value = model;
    makeFields();
  }
  wizard.domain = domainOf(model);
  const first = wizardSteps().findIndex((step) => step.kind === "field");
  goToStep(first > 0 ? first : 0);
}

function choiceButton(title, description, pressed, action) {
  const choice = element("button", undefined, "choice");
  choice.type = "button";
  choice.setAttribute("aria-pressed", pressed);
  choice.append(element("span", title, "choice-title"));
  if (description) choice.append(element("span", description, "choice-note"));
  choice.addEventListener("click", action);
  return choice;
}

function askQuestion(title, hint) {
  const heading = element("h3", title);
  const block = [heading];
  if (hint) block.push(element("p", hint, "wizard-hint"));
  $("wizard-question").replaceChildren(...block);
}

function stepError(message) {
  $("wizard-error").textContent = message;
  $("wizard-error").hidden = false;
}

function validateField(index) {
  const [, label, value, min, max] = models[wizard.model].fields[index];
  const [, , optional] = readLabel(label, value);
  const raw = String(fieldInput(index)?.value ?? "").trim();
  if (!raw) return optional ? null : "Enter a value to continue.";
  if (typeof value !== "number" && !optional) return null;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return "Enter a number.";
  if (min !== undefined && parsed < min) return "Enter a value of at least " + min + ".";
  if (max !== undefined && parsed > max) return "Enter a value no greater than " + max + ".";
  return null;
}

function reviewList() {
  const list = element("dl", undefined, "review-list");
  const spec = models[wizard.model];
  const modelRow = element("dd", undefined, "review-value");
  modelRow.append(element("span", spec.name, "review-text"));
  const change = element("button", "Change", "quiet");
  change.type = "button";
  change.setAttribute("aria-label", "Change the model");
  change.addEventListener("click", () => goToStep(0));
  modelRow.append(change);
  list.append(element("dt", "Model"), modelRow);
  spec.fields.forEach(([, label, value], index) => {
    const [name, unit] = readLabel(label, value);
    const raw = String(fieldInput(index)?.value ?? "").trim();
    const row = element("dd", undefined, "review-value");
    row.append(element("span", raw ? (unit ? raw + " " + unit : raw) : "Skipped", raw ? "review-text" : "review-text muted"));
    const edit = element("button", "Edit", "quiet");
    edit.type = "button";
    edit.setAttribute("aria-label", "Edit " + name);
    edit.addEventListener("click", () => goToStep(stepOfField(index)));
    row.append(edit);
    list.append(element("dt", name), row);
  });
  return list;
}

function renderStep(moveFocus = false) {
  const steps = wizardSteps();
  wizard.step = Math.min(Math.max(wizard.step, 0), steps.length - 1);
  const step = steps[wizard.step];
  const total = models[wizard.model] ? steps.length : 0;
  $("wizard-progress").textContent = total ? "Step " + (wizard.step + 1) + " of " + total : "Step " + (wizard.step + 1);
  $("wizard-bar").style.width = (total ? Math.round((wizard.step + 1) / total * 100) : 8) + "%";
  $("wizard-error").hidden = true;
  $("wizard-error").textContent = "";
  $("choices").hidden = step.kind !== "domain" && step.kind !== "variant";
  $("fields").hidden = step.kind !== "field";
  $("review").hidden = step.kind !== "review";
  $("model-note").hidden = step.kind !== "review";
  $("wizard-back").hidden = wizard.step === 0;
  $("wizard-next").hidden = step.kind !== "field";
  $("wizard-submit").hidden = step.kind !== "review";
  $("wizard-skip").hidden = true;
  let focusTarget = $("wizard-question");
  if (step.kind === "domain") {
    askQuestion("What is the primary energy source?", "Pick the closest match. You can change it later.");
    const buttons = domains.map(([id, title, note, , options]) => choiceButton(title, note, wizard.domain === id, () => {
      wizard.domain = id;
      if (options.length === 1) chooseModel(options[0][0]);
      else goToStep(1);
    }));
    $("choices").replaceChildren(...buttons);
    focusTarget = buttons[0];
  } else if (step.kind === "variant") {
    const spec = domainSpec(wizard.domain);
    askQuestion(spec[3], "Choose the description that matches your process.");
    const buttons = spec[4].map(([id, title, note]) => choiceButton(title, note, wizard.model === id, () => chooseModel(id)));
    $("choices").replaceChildren(...buttons);
    focusTarget = buttons[0];
  } else if (step.kind === "field") {
    const [, label, value] = models[wizard.model].fields[step.index];
    const [name, unit, optional] = readLabel(label, value);
    askQuestion(name, [models[wizard.model].name, unit ? "Answer in " + unit : "", optional ? "Optional" : ""]
      .filter(Boolean).join(" · "));
    [...$("fields").children].forEach((row, index) => { row.hidden = index !== step.index; });
    $("wizard-skip").hidden = !optional;
    focusTarget = fieldInput(step.index);
  } else {
    askQuestion("Review your answers", "Change anything before the engine runs.");
    $("review").replaceChildren(reviewList());
  }
  if (moveFocus && focusTarget) focusTarget.focus({preventScroll: true});
}

function goToStep(step) {
  wizard.step = step;
  renderStep(true);
}

function advanceStep() {
  const steps = wizardSteps();
  const step = steps[wizard.step];
  if (step.kind === "field") {
    const message = validateField(step.index);
    if (message) {
      stepError(message);
      fieldInput(step.index)?.focus({preventScroll: true});
      return;
    }
  }
  if (wizard.step < steps.length - 1) goToStep(wizard.step + 1);
}

function skipStep() {
  const step = wizardSteps()[wizard.step];
  if (step.kind === "field") {
    const input = fieldInput(step.index);
    if (input) input.value = "";
  }
  advanceStep();
}

function reviewAnswers() {
  setMode(false, true);
  const review = wizardSteps().findIndex((step) => step.kind === "review");
  goToStep(review > 0 ? review : 0);
}

function startOver() {
  wizard.domain = null;
  wizard.model = null;
  wizard.step = 0;
  setMode(false);
  renderStep(true);
}


async function runEngine(request) {
  if (fromFile) throw new Error("Start the site with python website/serve.py, then open http://127.0.0.1:8000.");
  if (hosted) {
    browserWorker ??= new Worker("engine-worker.js?v=20261111-4");
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
  const input = Object.values(cases || {}).at(-1);
  /* The flowchart engine works in watts and names its own variables. */
  if (Number.isFinite(calc.W_actual_W) && Number.isFinite(calc.reversible_work_limit_W)) {
    return { calc, claimed: calc.W_actual_W, limit: calc.reversible_work_limit_W, unit: "W" };
  }
  const claimed = calc["Claimed electrical output (kW)"] ?? calc.claimed_electrical_output_kw ?? input?.W_out_kw;
  const limit = calc["Strict reversible power ceiling (kW)"] ?? calc["Reversible power ceiling (kW)"]
    ?? calc.reversible_power_limit_kw ?? calc.reversible_work_limit_kw ?? calc.effective_temperature_work_reference_kw;
  return { calc, claimed, limit, unit: "kW" };
}

function pretty(value) {
  if (typeof value === "number") return number.format(value);
  if (value === null || value === undefined) return "Unavailable";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const verdictGlyphs = {pass: "✓", fail: "✕", wait: "!"};

function verdictBlock(tone, status, title) {
  const block = element("div", undefined, tone ? "verdict " + tone : "verdict");
  const mark = element("div", verdictGlyphs[tone] || "◎", "verdict-mark");
  mark.setAttribute("aria-hidden", "true");
  const body = element("div", undefined, "verdict-body");
  if (status) body.append(element("p", status, "verdict-status"));
  body.append(element("h3", title));
  block.append(mark, body);
  block.body = body;
  return block;
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
    const message = verdictBlock("fail", "Calculation not run", "Could not run the calculation");
    message.body.append(element("p", data.error));
    output.append(message);
    return;
  }
  const { result, cases = {} } = data;
  const code = result.verdict?.status || result.Verdict;
  /* The flowchart engine and the original engine word their verdicts
     differently; both reduce to pass / fail / needs-more. */
  const feasible = code === "FEASIBLE / NOT REJECTED" || code === "FEASIBLE"
    || code === "REVERSIBLE LIMIT";
  const rejected = code === "NOT FEASIBLE" || code?.startsWith("IMPOSSIBLE")
    || code?.startsWith("REJECT");
  setStatus(feasible ? "Feasible" : rejected ? "Not feasible" : code === "PROPERTY CALCULATION ONLY" ? "Properties only" : "Model required",
    feasible ? "pass" : rejected ? "fail" : "wait");
  const verdict = verdictBlock(feasible ? "pass" : rejected ? "fail" : "wait", code || "Result",
    result.title || models[data.route]?.name || data.route.replaceAll("_", " "));
  const reason = result.verdict?.reasons?.[0] || result.Reason;
  if (reason) verdict.body.append(element("p", reason));
  output.append(verdict);
  const again = element("div", undefined, "result-actions");
  for (const [label, action] of [
    ["Change an answer", reviewAnswers],
    ["Start over", startOver]]) {
    const button = element("button", label, "quiet");
    button.type = "button";
    button.addEventListener("click", action);
    again.append(button);
  }
  output.append(again);
  const { calc, claimed, limit, unit } = outputValues(result, cases);
  if (Number.isFinite(claimed) && Number.isFinite(limit)) {
    const watts = unit === "W" || Math.max(Math.abs(claimed), Math.abs(limit)) < 1;
    const scale = unit === "W" ? 1 : (watts ? 1000 : 1);
    const power = (value) => number.format(value * scale) + (watts ? " W" : " kW");
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
if (!models[$("model").value]) $("model").value = defaultModel;
makeFields(true);
function openModel(model) {
  setMode(false);
  wizard.model = null;
  chooseModel(model);
  $("workbench").scrollIntoView();
}

/* Hero chart ---------------------------------------------------------------
   Real engine output, not illustration: claimed electrical power against the
   reversible ceiling across roll-number suffixes for both CL 202 coffee
   assignments (Figure 1 of the manuscript). Each row is [X, claim_kW, ceiling_kW].

   Regenerate from the repository root with:
   python -c "import json;from run_mock_assignments import base_assignment as b, modified_assignment as m;f=lambda s,k:[round(s['Claimed electrical output (kW)'],4),round(s[k],4)];print(json.dumps({'base':[[x]+f(b(x)[1],'Strict reversible power ceiling (kW)') for x in sorted(set(list(range(0,400,20))+[291,399]))],'modified':[[x]+f(m(x)[1],'Reversible power ceiling (kW)') for x in sorted(set(list(range(20,401,20))+[1,12,400]))]}))"
*/
const heroChartData = {
  base: {
    title: "Base assignment",
    caption: "Two finite water streams · X = 000–399",
    mark: {x: 291, tone: "fail", label: "X = 291 · first infeasible",
      aria: "The claim first exceeds the ceiling at X = 291"},
    points: [[0, .8888, 1.1737], [20, .911, 1.1632], [40, .9332, 1.1567], [60, .9554, 1.1532],
      [80, .9776, 1.1522], [100, .9999, 1.1531], [120, 1.0221, 1.1555], [140, 1.0443, 1.1592],
      [160, 1.0665, 1.164], [180, 1.0887, 1.1696], [200, 1.1109, 1.176], [220, 1.1332, 1.1831],
      [240, 1.1554, 1.1907], [260, 1.1776, 1.1987], [280, 1.1998, 1.2072], [291, 1.212, 1.212],
      [300, 1.222, 1.216], [320, 1.2443, 1.2252], [340, 1.2665, 1.2346], [360, 1.2887, 1.2443],
      [380, 1.3109, 1.2542], [399, 1.332, 1.2638]],
  },
  modified: {
    title: "Modified assignment",
    caption: "ORC with an isothermal wax sink · X = 001–400",
    mark: {x: 12, tone: "pass", label: "X = 012 · first feasible",
      aria: "The claim first falls below the ceiling at X = 012"},
    points: [[1, 1.1132, .9965], [12, 1.1376, 1.1453], [20, 1.1554, 1.258], [40, 1.1998, 1.5562],
      [60, 1.2443, 1.8771], [80, 1.2887, 2.22], [100, 1.3331, 2.5839], [120, 1.3776, 2.9683],
      [140, 1.422, 3.3725], [160, 1.4665, 3.7958], [180, 1.5109, 4.2377], [200, 1.5553, 4.6977],
      [220, 1.5998, 5.1751], [240, 1.6442, 5.6695], [260, 1.6886, 6.1805], [280, 1.7331, 6.7076],
      [300, 1.7775, 7.2505], [320, 1.822, 7.8086], [340, 1.8664, 8.3818], [360, 1.9108, 8.9695],
      [380, 1.9553, 9.5716], [400, 1.9997, 10.1876]],
  },
};

function chartPanel(series) {
  const W = 460, H = 196, L = 54, R = 448, T = 18, B = 150;
  const steps = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
  const peak = Math.max(...series.points.flatMap(([, claim, ceiling]) => [claim, ceiling]));
  const half = peak * 1.06 / 2;
  const decade = 10 ** Math.floor(Math.log10(half));
  const step = decade * steps.find((candidate) => candidate * decade >= half - 1e-12);
  const top = step * 2;
  const x = (value) => (L + value / 400 * (R - L)).toFixed(1);
  const y = (value) => (B - value / top * (B - T)).toFixed(1);
  const line = (index) => series.points.map((point, i) => (i ? "L" : "M") + x(point[0]) + " " + y(point[index])).join("");
  const tick = (value) => value.toFixed(step < 1 ? 1 : 0);
  const at = series.points.find((point) => point[0] === series.mark.x);
  const anchor = series.mark.x > 200 ? "end" : "start";
  const markX = Number(x(series.mark.x));
  return `<figure class="chart">
  <figcaption><span class="chart-title">${series.title}</span><span class="chart-note">${series.caption}</span></figcaption>
  <svg viewBox="0 0 ${W} ${H}" role="img" preserveAspectRatio="xMidYMid meet"
    aria-label="${series.title}: claimed electrical power and the reversible power ceiling in kilowatts, for roll-number suffixes 0 to 400. ${series.mark.aria}.">
    <path class="axis" d="M${L} ${T}V${B}H${R}"/>
    ${[0, step, top].map((value) => `<path class="axis" d="M${L - 4} ${y(value)}h4"/><text class="tick" x="${L - 9}" y="${Number(y(value)) + 3.5}" text-anchor="end">${tick(value)}</text>`).join("")}
    ${[0, 100, 200, 300, 400].map((value) => `<path class="axis" d="M${x(value)} ${B}v4"/><text class="tick" x="${x(value)}" y="${B + 17}" text-anchor="middle">${value}</text>`).join("")}
    <text class="axis-caption" x="${(L + R) / 2}" y="${H - 6}" text-anchor="middle">Roll-number suffix X</text>
    <text class="axis-caption" transform="rotate(-90 15 ${(T + B) / 2})" x="15" y="${(T + B) / 2}" text-anchor="middle">Electrical power (kW)</text>
    <path class="series ceiling" d="${line(2)}"/>
    <path class="series claim" d="${line(1)}"/>
    <path class="marker ${series.mark.tone}" d="M${markX} ${T - 6}V${y(at[1])}"/>
    <circle class="marker-dot ${series.mark.tone}" cx="${markX}" cy="${y(at[1])}" r="3.5"/>
    <text class="mark-label ${series.mark.tone}" x="${markX + (anchor === "end" ? -7 : 7)}" y="${T - 8}" text-anchor="${anchor}">${series.mark.label}</text>
  </svg>
</figure>`;
}

function drawHeroChart() {
  const host = $("hero-chart");
  if (!host) return;
  host.innerHTML = chartPanel(heroChartData.base) + chartPanel(heroChartData.modified) +
    `<ul class="chart-legend">
      <li><svg viewBox="0 0 22 8" aria-hidden="true"><path class="series claim" d="M1 4H21"/></svg>Claimed output</li>
      <li><svg viewBox="0 0 22 8" aria-hidden="true"><path class="series ceiling" d="M1 4H21"/></svg>Reversible ceiling</li>
    </ul>`;
}
try { drawHeroChart(); } catch (error) { /* chart is decoration-free but optional */ }

$("model").addEventListener("change", () => { makeFields(true); clearOutput(); });
$("model-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const model = currentModel();
  const inputs = new FormData(event.target);
  const spec = models[model];
  const caseData = {...spec.flow};
  for (const [index, [key, label, value, , , scale = 1, offset = 0]] of spec.fields.entries()) {
    const raw = inputs.get(key);
    const blank = raw === null || String(raw).trim() === "";
    const [, , optional] = readLabel(label, value);
    if (optional && blank) continue;
    if (blank) {
      const step = stepOfField(index);
      if (step > 0) {
        goToStep(step);
        stepError("Enter a value to continue.");
      } else render({error: "Fill in every labeled value before calculating."});
      return;
    }
    const parsed = typeof value === "number" || value === "" ? Number(raw) * scale + offset : raw.trim();
    if (key.includes(".")) {
      const [group, field] = key.split(".");
      caseData[group] ??= {};
      caseData[group][field] = parsed;
    } else caseData[key] = parsed;
  }
  analyze({flowchart: caseData});
});
$("wizard-next").addEventListener("click", advanceStep);
$("wizard-back").addEventListener("click", () => { if (wizard.step > 0) goToStep(wizard.step - 1); });
$("wizard-skip").addEventListener("click", skipStep);
$("fields").addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  advanceStep();
});
renderStep();
