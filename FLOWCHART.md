# Thermodynamic Feasibility Tester

```mermaid
flowchart TD
    Text["Plain-language scenario"] --> Extract["Select a model and quote supplied quantities"]
    Extract --> Validate{"Enough unambiguous data?"}
    Validate -->|No| Followup["Ask for the specific missing data or clarify the model"]
    Followup --> Extract
    Validate -->|Yes| Normalize["Convert units in Python"]
    Normalize --> Start
    Start["Structured scenario with a system boundary, claimed output and units"] --> Select{"Which model fits?"}
    Select -->|Thermal| Thermal{"Thermal route"}
    Select -->|Mechanical| Mech["Use recoverable input power or multiply event energy by event rate"]
    Select -->|Ideal blackbody radiation| Solar["Multiply irradiance by effective area and the Petela–Landsberg fraction"]
    Select -->|Isothermal and isobaric reaction| Chem["Use signed Gibbs energy for the stated reaction direction and molar rate"]
    Select -->|Outside implemented scope| Missing["Insufficient data or model required"]

    Thermal -->|Fixed reservoirs| Fixed["Use given temperatures and calculate the Carnot bound"]
    Thermal -->|General finite streams| Streams["Use supplied stream states. Check claimed work against enthalpy changes, or derive work and label it as inferred."]
    Thermal -->|Base assignment| Base["Derive both missing stream temperatures and claimed electrical power. Solve zero entropy generation for the strict ceiling."]
    Thermal -->|Modified assignment| Wax["Calculate gas enthalpy and entropy changes and wax melting temperature. Apply the equivalent-temperature engine."]
    Thermal -->|Open or closed balance| General["Evaluate supplied mass, energy and entropy terms where applicable"]
    Thermal -->|Properties only| Prop["Report property changes without a device verdict"]

    Fixed --> Heat{"Was rejected heat supplied independently?"}
    Wax --> Heat
    Heat -->|Yes| Independent["Check the First Law using the supplied heat and work"]
    Heat -->|No| Derived["Derive rejected heat from the First Law and label it as inferred"]
    Base --> Derived
    Independent --> Entropy["Evaluate entropy generation for the selected boundary"]
    Derived --> Entropy
    Streams --> Entropy
    Entropy --> Review{"What do the applicable checks and limits show?"}
    General --> Review
    Mech --> Resource{"Required resource data and output supplied?"}
    Solar --> Resource
    Chem --> Resource
    Resource -->|No| Missing
    Resource -->|Yes| Limit["Compare output with the resource ceiling. Report balance status separately."]
    Limit --> Review
    Review -->|Violation or forward reaction requires work| Fail["Not feasible under the selected model"]
    Review -->|Checks pass and valid limit is available| Pass["Feasible within the model"]
    Review -->|No valid limit or insufficient data| Missing
```

For a general finite-stream engine, the effective-temperature comparison is optional and tied to the supplied states. The Base assignment runner also solves for the reversible cold outlet at the same hot-side duty, cold inlet and cold flow. Inferred heat or work closes the First Law by construction. A positive signed reaction Gibbs energy requires input work even for a claim of zero electrical output.
