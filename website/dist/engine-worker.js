let ready;

async function startEngine() {
  const indexURL = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";
  importScripts(indexURL + "pyodide.js");
  const python = await loadPyodide({ indexURL });
  const modules = [
    "thermodynamic_feasibility_tester_MASTER.py", "run_mock_assignments.py", "scenario_input.py",
    "website/__init__.py", "website/local_scenarios.py", "website/dist/__init__.py", "website/dist/solver.py",
  ];
  python.FS.mkdirTree("website/dist");
  await Promise.all(modules.map(async (path) => {
    const response = await fetch("./python/" + path);
    if (!response.ok) throw new Error("Python source failed to load.");
    python.FS.writeFile(path, await response.text());
  }));
  python.runPython("from website.dist.solver import solve_json");
  return python;
}

self.onmessage = async ({data}) => {
  try {
    ready ??= startEngine().catch((error) => { ready = null; throw error; });
    const python = await ready;
    const solve = python.globals.get("solve_json");
    try {
      self.postMessage({id: data.id, result: JSON.parse(solve(JSON.stringify(data.request)))});
    } finally {
      solve.destroy();
    }
  } catch {
    self.postMessage({id: data.id, result: {
      error: "The Python engine could not load. Check your internet connection and try again.",
    }});
  }
};
