"""Build a static GitHub Pages site using the same Python calculation engine."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build(output=None):
    output = Path(output) if output else ROOT / "docs"
    output.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "style.css", "app.js", "engine-worker.js"):
        shutil.copyfile(ROOT / "website" / "dist" / name, output / name)
    for path in ("thermodynamic_feasibility_tester_MASTER.py", "run_mock_assignments.py", "scenario_input.py",
                 "website/local_scenarios.py", "website/dist/solver.py"):
        target = output / "python" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    for path in ("website/__init__.py", "website/dist/__init__.py"):
        (output / "python" / path).write_text("", encoding="utf-8")
    (output / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Static website built in {output}")


if __name__ == "__main__":
    build()
