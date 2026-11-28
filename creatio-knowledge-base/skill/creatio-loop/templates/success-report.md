# 012 Success report

Tester, 2026-11-06 16:10. Plan read: `plan.md` as of 2026-11-06 12:05. Every criterion passed;
the task is done. Earlier rounds: `report-1.md`, `report-2.md`.

| AC | Result | Evidence |
|---|---|---|
| AC-01 | pass | `objects.py probe UsrPkg UsrShipment`: `UsrLabel Text 250 ok` |
| AC-02 | pass | `dotnet test tests/UsrPkg`: 6 passed |
| AC-03 | pass | `tests/UsrPkg/integration/012-AC-03.act`: `check-record UsrShipment Id=$Shipment has UsrLabel eq "PARCEL-0007"` |
| AC-04 | pass | same case: `PARCEL-0008` after the update |
| AC-05 | pass | same case: `check-result Label eq "PARCEL-0008"` |
| AC-06 | pass | `tests/UsrPkg/e2e/012-AC-06.act`: PASS, 7.9 s |

## Tests kept

- `tests/UsrPkg/integration/012-AC-03.act`, `tests/UsrPkg/e2e/012-AC-06.act` in the project workspace
- `tests/UsrPkg/unit/ShipmentLabelTests.cs` (author's)

## Coverage

From `cases_from_package(UsrPkg, report=True)`: one line per schema of `schemas.json`, every `not covered` one with its reason.
A report with an unexplained `not covered` line is not a success report.

- UsrShipment (object): unit 0 | integration 2 | e2e 0
- UsrShipmentPage (page): unit 0 | integration 0 | e2e 1
- not covered: UsrShipmentStatus (object) - probe only: a lookup value
- not covered: UsrShipmentLabel_Process (process) - framework gap 1
