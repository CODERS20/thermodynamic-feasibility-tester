"""Build a static GitHub Pages site using the same Python calculation engine.

The browser build has to carry every module the solver imports. That list used
to be written out twice, here and again in engine-worker.js, and the two drifted
the moment a module was added. The worker now reads the manifest this script
writes, so there is one list and it cannot go stale.
"""

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

ASSETS = ("index.html", "style.css", "app.js", "engine-worker.js")

# Copied verbatim, in the order the browser should write them.
MODULES = (
    "thermodynamic_feasibility_tester_MASTER.py",
    "feasibility_tester.py",
    "run_mock_assignments.py",
    "scenario_input.py",
    "website/local_scenarios.py",
    "website/dist/solver.py",
)

# Created empty so the website package imports cleanly under Pyodide.
PACKAGE_MARKERS = ("website/__init__.py", "website/dist/__init__.py")


def module_order():
    """Every file the browser must place, packages before the modules in them."""
    ordered = list(PACKAGE_MARKERS)
    for path in MODULES:
        if path not in ordered:
            ordered.append(path)
    return ordered


def build(output=None):
    output = Path(output) if output else ROOT / "docs"
    output.mkdir(parents=True, exist_ok=True)

    for name in ASSETS:
        shutil.copyfile(ROOT / "website" / "dist" / name, output / name)

    for path in MODULES:
        source = ROOT / path
        if not source.exists():
            raise FileNotFoundError(f"{path} is listed in MODULES but is not in the repository.")
        target = output / "python" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    for path in PACKAGE_MARKERS:
        marker = output / "python" / path
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("", encoding="utf-8")

    manifest = output / "python" / "manifest.json"
    manifest.write_text(json.dumps({"modules": module_order()}, indent=2) + "\n", encoding="utf-8")

    (output / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Static website built in {output} ({len(module_order())} Python modules)")


if __name__ == "__main__":
    build()
