let ready;
let phase = "runtime script";

async function startEngine() {
  const indexURL = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";
  importScripts(indexURL + "pyodide.js");
  phase = "Python initialization";
  const python = await loadPyodide({ indexURL });
  /* build_pages.py writes this manifest, so the browser build can never fall
     behind the module list the solver actually imports. */
  phase = "module manifest";
  const manifestResponse = await fetch("./python/manifest.json");
  if (!manifestResponse.ok) throw new Error("Module manifest failed to load.");
  const modules = (await manifestResponse.json()).modules;
  if (!Array.isArray(modules) || !modules.length) throw new Error("Module manifest is empty.");

  const sourceRoot = "/home/pyodide/";
  for (const path of modules) {
    const slash = path.lastIndexOf("/");
    if (slash > 0) python.FS.mkdirTree(sourceRoot + path.slice(0, slash));
  }
  phase = "source loading";
  await Promise.all(modules.map(async (path) => {
    const response = await fetch("./python/" + path);
    if (!response.ok) throw new Error(`Python source failed to load: ${path}`);
    python.FS.writeFile(sourceRoot + path, await response.text());
  }));
  phase = "solver import";
  python.runPython("from website.dist.solver import solve_json");
  phase = "calculation";
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
  } catch (error) {
    console.error(error);
    self.postMessage({id: data.id, result: {
      error: "The Python engine could not load (" + phase + "). "
        + (error.message || JSON.stringify(error, Object.getOwnPropertyNames(error)) || String(error)).slice(0, 2000),
    }});
  }
};
