# CL 202 Thermodynamic Feasibility Tester

The GitHub Pages version runs the original Python engine in the visitor's browser using Pyodide. Its first calculation downloads the Python runtime from jsDelivr. The project requires no API key for calculations.

To rebuild the static site after editing the engine or website, run `python build_pages.py`. Publish the `docs` directory through GitHub Pages. The calculation code and downloaded JSON remain available in the shared version.

## Interactive website

Double-click `Start_ThermoLab.cmd` to open the local website on an available port. Keep the terminal open while using it. You can also start it from this folder with:

```powershell
python website/serve.py --port 0 --open
```

Paste a complete supported scenario and click **Analyze scenario**. The local parser selects a model, extracts quantities with their original source phrases, converts units, and runs the Python solver directly. **Review automatically filled values** opens the populated form. If data is missing or ambiguous, the form retains the recognized values for completion.

Automatic local extraction supports explicitly stated quantities for walking generators, fixed-reservoir engines, constant-heat-capacity hot and cold streams, ideal blackbody radiation, signed Gibbs-energy reactions, and the named CL 202 assignments. For other phrasing or models, use the numeric forms. Values are never filled from unrelated worked-example defaults.

Expand **View calculation code** beneath a result to show the actual Python calculation functions and verdict logic. Download the full calculation engine, parser, or assignment code from that panel. The **Engine input JSON** panel lets your professor reproduce the same case directly with `python thermodynamic_feasibility_tester_MASTER.py --input case.json`.

For walking, enter mechanical input and claimed electrical output in watts. Alternatively, choose the energy-per-step model and enter joules per step, steps per minute, and electrical output in watts. For the CL 202 coffee assignments, choose the Base or Modified example and enter your roll-number suffix.

The walking model always checks the input energy limit and reports the power left after electrical output. For a steady generator that rejects all remaining power as heat, supply the optional heat-rejection temperature to compute entropy generation. Supplying measured heat loss adds an independent First Law balance. Inferred heat loss is labeled in the result.

The website runs entirely on your computer using the original Python engine. All website assets are local. The website serves fresh assets on each page load.

Run the two mock assignments with Python 3.9 or newer. No packages need to be installed.

```powershell
python run_mock_assignments.py 100 --output-dir generated_cases
```

Replace `100` with the last three digits of your roll number. Base accepts `000` through `399`. Modified accepts `001` through `400`. The command runs both where their ranges overlap. Use `--case base` or `--case modified` to select one, and omit `--output-dir` for a terminal report alone.

The output directory contains one Base input and two Modified inputs. For Modified, the gas and wax property results feed the equivalent-temperature engine calculation. You can run any generated input directly through the original engine:

```powershell
python thermodynamic_feasibility_tester_MASTER.py --input generated_cases/base_x100.json
```

Use the assignment runner for the strict Base ceiling. It solves the cold outlet at zero entropy generation with the same hot-stream duty and cold-stream inlet and flow. The standalone engine also reports an effective-temperature reference using the cold outlet implied by the claim.

The Modified result assumes the wax sink can absorb heat at the melting temperature. For a separate supply-side check, pass a server heat budget in kW. The runner rejects a scenario whose specified gas states release more than the supplied budget.

```powershell
python run_mock_assignments.py 100 --case modified --server-heat-kw 12
```

## Verification

```powershell
python -m unittest -v
python thermodynamic_feasibility_tester_MASTER.py --self-test
```

At `X = 100`, Base requires 1.000 kW against a strict ceiling of 1.153 kW, and Modified requires 1.333 kW against a ceiling of 2.584 kW. The default cases assume no separate Modified server heat budget. Base first fails at `291`. Modified first passes at `012`.

## Step 2 model coverage

The original CLI, its interactive menu, and the Python `run_case` entry point use the same routes. Generate editable examples and try the walking case:

```powershell
python thermodynamic_feasibility_tester_MASTER.py --make-templates
python thermodynamic_feasibility_tester_MASTER.py --input thermo_case_templates/mechanical_power.json
```

Every power claim uses `W_out_kw`. The routes below compare it with an ideal resource ceiling. A full energy or entropy balance requires additional boundary data.

| Route | Other JSON inputs | Scope |
|---|---|---|
| `mechanical_power` | `recoverable_mechanical_power_kw` **or** `recoverable_energy_per_event_j` and `events_per_s` | Recoverable work at the converter input, averaged over the same interval as the electrical output. The example uses illustrative step energy. |
| `solar_blackbody` | `T_source_K`, `T_ambient_K`, `irradiance_W_m2`, `collection_area_m2` | Ideal Petela–Landsberg radiative exergy bound. Irradiance and effective area refer to the same beam at the aperture. |
| `reaction_gibbs` | `reaction_direction`, `delta_G_kj_per_mol_rxn`, `reaction_rate_mol_rxn_s` | Isothermal, isobaric forward reaction with signed Gibbs energy supplied at the operating conditions. The energy and rate use the same stoichiometric mole of reaction. Positive Gibbs energy requires external work input. |

Missing model inputs return **INSUFFICIENT DATA / MODEL REQUIRED** and name the missing quantities. For scenarios outside these routes, use `unsupported_domain`. Examples include wind without a supplied recoverable work limit, solar radiation needing a diffuse or spectral model, and chemical reactions without a Gibbs energy model.

The [implementation flowchart](FLOWCHART.md) shows the balance checks, derivations, and verdict paths. The ideal radiation and signed cell-work relations follow [Petela's radiation exergy analysis](https://www.sciencedirect.com/science/article/pii/S0038092X03002263) and the [IUPAC definition of standard electromotive force](https://goldbook.iupac.org/terms/view/S05913).

## Step 3 plain-language input

Start the offline terminal demo:

```powershell
python scenario_input.py "Can I generate electricity by walking?" --interactive
```

When asked for details, enter `Recoverable energy is 4 J per step, at 120 steps per minute. Electrical output is 5 W.` The tester quotes the quantities it found, shows the normalized inputs, and compares the 5 W claim with an 8 W ceiling. The step energy is illustrative. For a single scripted run, use `--reply` followed by the additional details. Add `--output-json walking_case.json` to save the case for the original tester.

Use `--json` with a scenario argument for a machine-readable response. The response contains the selected route, original quotes, follow-up questions, normalized engine cases, and the result. If input is missing, it returns `needs_input` and leaves `cases` empty. Use repeated `--reply` options to supply additional details. The same interface is available in Python through `analyze_scenario(text, replies=...).as_dict()`.

```powershell
python scenario_input.py --json "Generating electricity by walking" --reply "Recoverable energy is 4 J per step at 120 steps per minute. Electrical output is 5 W."
```

The offline parser recognizes the walking demo and explicit CL 202 Assignment 1 Base or Modified requests with a suffix, such as `Run CL 202 Assignment 1 Modified for suffix 100.` If it cannot interpret a phrase, label the quantities explicitly or use the original structured inputs.

The website uses numeric forms after suggesting a model. The command-line text parser above remains available for labeled demo inputs.

## Step 4 manuscript and benchmarks

The [Word manuscript](CL202_Thermodynamic_Feasibility_Manuscript.docx) includes the assumptions, coffee-case results, and independent or published comparisons for all four model domains. Reproduce its numerical comparison table with:

```powershell
python validate_benchmarks.py
```

The differences are computed as program value minus reference value. The mechanical row compares a calculated ideal ceiling with a measured output. Its difference is the margin below the ceiling.
