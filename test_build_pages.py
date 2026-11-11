"""The browser build must carry every module the solver imports.

A missing entry does not fail the build or any other test: it only shows up as
ModuleNotFoundError inside Pyodide, in a browser, after deployment. These tests
catch it here instead.
"""

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

import build_pages

ROOT = Path(__file__).resolve().parent


def local_imports(path):
    """Top-level module names imported by a file that are modules in this repo."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return {name for name in names
            if (ROOT / f"{name}.py").exists() or (ROOT / name / "__init__.py").exists()
            or (ROOT / name).is_dir()}


class BrowserBuildTests(unittest.TestCase):
    def test_solver_imports_are_all_shipped(self):
        shipped = set()
        for path in build_pages.MODULES:
            shipped.add(Path(path).stem)
            shipped.add(Path(path).parts[0])
        for source in ("website/dist/solver.py", "run_mock_assignments.py",
                       "scenario_input.py", "website/local_scenarios.py"):
            for name in local_imports(ROOT / source):
                with self.subTest(source=source, imports=name):
                    self.assertIn(name, shipped,
                                  f"{source} imports {name!r}, which the browser build does not ship")

    def test_feasibility_tester_is_shipped(self):
        """It was missing once and only broke in the browser."""
        self.assertIn("feasibility_tester.py", build_pages.MODULES)

    def test_build_writes_every_listed_module_and_a_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            build_pages.build(folder)
            out = Path(folder)
            manifest = json.loads((out / "python" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["modules"], build_pages.module_order())
            for path in manifest["modules"]:
                written = out / "python" / path
                self.assertTrue(written.exists(), f"{path} is in the manifest but was not written")
            for name in build_pages.ASSETS:
                self.assertTrue((out / name).exists(), f"{name} missing from the build")
            self.assertTrue((out / ".nojekyll").exists())

    def test_packages_precede_their_modules(self):
        """Pyodide writes files in order; a package dir must exist first."""
        order = build_pages.module_order()
        for marker in build_pages.PACKAGE_MARKERS:
            package = str(Path(marker).parent).replace("\\", "/")
            for path in order:
                normalised = path.replace("\\", "/")
                if normalised.startswith(package + "/") and normalised != marker:
                    self.assertLess(order.index(marker), order.index(path),
                                    f"{marker} must be written before {path}")

    def test_missing_module_is_reported_at_build_time(self):
        original = build_pages.MODULES
        build_pages.MODULES = original + ("definitely_not_here.py",)
        try:
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(FileNotFoundError):
                    build_pages.build(folder)
        finally:
            build_pages.MODULES = original


if __name__ == "__main__":
    unittest.main()
