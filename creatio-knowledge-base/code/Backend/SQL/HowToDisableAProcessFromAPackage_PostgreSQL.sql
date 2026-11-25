-- Disable a business process from a package: a package SQL script that writes the Process Library's own row (PostgreSQL).
--
-- Use when:
--   - Every site the package installs on must have a process switched off (signal and manual starts).
--   - The process schema's metadata flag (Enabled) is not enough: the install ignores it.
--
-- How it works (verified on 8.2.3, the test site, S45-T04):
--   - The Process Library's "Enabled" column is `VwProcessLib.Enabled` = no `SysProcessDisabled` row whose
--     `SysSchemaId` is the schema's `SysSchema.Id` or its `ParentId`. `SysSchema.Id` differs per site, so the
--     script finds it by the schema's UId, which the package carries.
--   - The library's Deactivate (`ProcessEngineService.svc/DisableProcess?sysSchemaId=<SysSchema.Id>`) writes the
--     same row (Name '', ProcessListeners 0) and nothing in `SysSchema`; it also refreshes the engine's memory.
--   - A row written by SQL is read only when the site starts: until a restart the process still starts by its
--     signal and by Execute; after `clio restart-web-app` both are refused ("The process is not active").
--     Whether the package install alone restarts the engine was not checked: restart the site after the install,
--     or call DisableProcess once.
--     From the kit: `python no-code/tools/env/site.py -e <env> restart` or `process-off <ProcessName>`.
--
-- Customize:
--   - '5d2a1c3e-0000-4000-8000-000000000001' -> the process schema's UId (descriptor.json of the process).
--
-- Install as: `sqlscripts.py new <package> UsrDisableOrderSignalProcess --file this.sql --engine postgresql
--   --install after-package` (the schema row must exist). Idempotent: one row per copy of the schema, never two.
-- To switch the process back on: delete the rows (an uninstall script, or the library's Activate) and restart.

INSERT INTO "SysProcessDisabled" ("Id", "Name", "ProcessListeners", "SysSchemaId", "CreatedOn", "ModifiedOn")
SELECT gen_random_uuid(), '', 0, s."Id", now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC'
FROM "SysSchema" s
WHERE s."UId" = '5d2a1c3e-0000-4000-8000-000000000001'
  AND s."ManagerName" = 'ProcessSchemaManager'
  AND NOT EXISTS (SELECT 1 FROM "SysProcessDisabled" d WHERE d."SysSchemaId" = s."Id");
