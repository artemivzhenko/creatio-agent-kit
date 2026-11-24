---
name: creatio-merge
description: The layer merge of Creatio objects (and the pages that go with them) as one procedure with evidence - the plan, a backup of the packages, tests before, snapshots, the merge, the push of the packages, the verification, snapshots after, the same tests after, a report. Use for "merge the layers", "collapse the replacing schemas", "merge objects", "fold the layers into one package". A child package folded into its parent is `describe.py merge-run`, not this skill.
version: 1
---

# Layer merge of objects

You collapse the replacing layers of an object (several packages each holding a `Schemas/<Object>` copy) into one layer
of the target package, and prove that the site did not change: the same columns, the same table, the same rows, the same
tests green. Every step leaves a file in one evidence folder outside every repository; the last line of the report is
`merged <Object>: N layers into <target>, tests K/K before and after, compare same` or the first stop.

Tools: the describe toolkit (`no-code/tools/describe/describe.py`; its README sections "Merge plan", "Merge of an object"),
`push/push.py`, `ci-cd/pipeline.py backup`, `env/data.py fixture`, the UI test utility (`automatic-creatio-tests`, the
backend cases over OData). Read `describe/README.md` "Merge of an object" once before the first merge: it says what the
fold does with UIds, `DependsOn`, resources and removed layers.

## Inputs (ask when missing, once)

- the clio workspace that holds every package of the fold (`<workspace>/packages/<Pkg>`), and the objects - or none, and
  `merge-plan` lists every object replaced by more than one package;
- the environment `-e <env>` (a clio environment name). Never merge without it: the layer order is the site's
  `SysPackage.HierarchyLevel`, and the references check needs the database;
- the UI test utility root whose `Configuration/creatio.env.config.json` points at the same site (check the `BaseUrl`
  host against the clio environment's url; a different host is a stop: the tests would prove another database);
- the evidence folder (`<somewhere outside the repositories>/merge-<date>-<Object>`).

## Procedure

Run from `creatio-knowledge-base/no-code/tools`. `E` is the evidence folder.

1. **Plan.** `python describe.py merge-plan <workspace> [<Object>...] -e <env> > E/plan.txt`. Read it whole: the target
   per object, `layer <pkg>: +n columns`, `siblings`, `depends:`. A `conflict` line or `exit code 1` is a stop: write it
   in the report and hand the plan to the human. A conflict is never settled by editing a layer's files by hand.
   From the plan list the **packages of the fold**: the target and every package that loses a layer.
2. **Backup.** `python ../../../ci-cd/pipeline.py backup --package <Pkg1,Pkg2,...> -e <env> --out E/backup`: `clio pull-pkg`
   of each package of the fold into `E/backup/Pkg-<stamp>.zip`; the printed `rollback:` line goes into the report as is.
   No zip, no merge.
3. **Tests before.** One backend case per merged object under the utility's `Cases/Merge/Merge-<Object>.act`: an insert that
   sets a column of EVERY layer of the plan (`python env/data.py fixture -e <env> <Object> --columns <the layers' columns>`
   prints the `insert` and `delete` lines; a lookup column takes the value the fixture resolved), `check-record` of each
   of those columns (a value with a space is quoted: `has UsrMrgA1 eq "UsrMrgA1 A"`; the fixture's `set` line takes it bare), `update` of one of them, `check-record`, the `delete` lines. A page merged alongside gets its
   `.act` from the utility's `analyse` of the live page. Name the files `Merge-<Object>.act`: `--filter` matches the file
   name. Then `dotnet run --project src/CreatioAutoTests.Cli -- --filter Merge-` (from the utility root, or `--root <utility root>` from anywhere); the report files
   from `Reports/` are copied to `E/before/`; the passed count is
   `E/before/passed.txt`. A red case before the merge is a stop (the baseline is broken, not the merge).
4. **Snapshots before.** Per object: `python describe.py snapshot <Object> --workspace <workspace> -e <env> --out
   E/before/<Object>.snapshot` (the effective columns on disk, the table, the rows, a checksum per column, the copies).
   A big table: `--columns` names the columns of the layers.
5. **Merge.** `python describe.py merge <workspace> <Object> -e <env>` prints the plan, the `write` / `delete` lines and
   the references check; read it, then the same line with `--apply`. `stopped: ... - nothing written` is a stop. Repeat
   per object; `E/merge.txt` holds every print.
6. **Push.** The target package first with `python push/push.py <Pkg> -e <env>` (it clears `IsChanged`, pushes, checks the
   compilation), then every package that lost a layer with `python push/push.py <Pkg> -e <env> --allow-removed <Object,...>`
   (the objects the plan removes from it): the flag lifts the delete stop for exactly those schemas after its own references
   check, and `compilation log: FAILED` names the package whose code failed - errors in a package outside the fold are the
   site's: write that line in the report and go on only when step 7's `layers` answers. Any other failed push is a stop:
   roll back with the `rollback:` line of step 2 and report (`deploy --artifact` may fail once with `installation log
   could not be attributed`, run it again; its closing compile may hit `another compilation is in progress` right after an
   install - wait a minute and compile again, then check with `layers`).
7. **Verify.** `python push/push.py verify <Pkg> -e <env>` per pushed package -> `E/verify.txt` (every schema `same`);
   `python describe.py layers <Object> -e <env>` -> `E/layers-after.txt`: one copy per object, in the target.
8. **Snapshots after and compare.** Step 4 again into `E/after/`; `python describe.py compare E/before/<Object>.snapshot
   E/after/<Object>.snapshot --ignore-layers > E/compare.txt` per object. Anything but `same` is the bug report: roll
   back (step 2's line), keep the evidence, stop.
9. **Tests after.** Step 3's run again into `E/after/`; the passed count must equal `E/before/passed.txt`.
10. **Report.** `E/merge-report.md`: the objects and the target, the packages pushed in order, the backup zip and its
    rollback line, tests K/K before and after, `compare same` per object, `verify` N same; or the step that stopped and
    its line. The merged packages are the human's to pull back and commit (`describe.py review <package>` sorts a pulled
    package before a commit); you commit nothing.

## Never

- merge without `-e`, without the backup zip, or with the test utility pointed at another site;
- settle a `conflict` or a `stopped:` by editing schema files by hand, or by removing a layer that is not in the plan;
- skip the tests before because "nothing changed yet": they are what makes the tests after a proof;
- push the removed layers' packages before the target;
- touch processes, DCM or rule addons: the toolkit refuses them (`merge writes objects and pages only`); they stay as they are;
- read or copy a client's record values into a case: the fixture's values are made up; `sample_records` is for looking;
- commit, branch or push to git.

No tool answers a step? Call `report_gap(kind="missing"|"misbehaved"|"by-hand", need, instead, script=<the file you wrote>)`
before going on; a merge step done by hand that is not recorded does not become a tool.
