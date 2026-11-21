using System.Collections.Generic;
using Terrasoft.Core;
using Terrasoft.Core.Entities;

/// <summary>
/// Demonstrates how to keep one missing column from failing a whole EntitySchemaQuery.
/// esq.AddColumn("UsrTerms.Name") on an environment whose UsrOrder has no UsrTerms column throws
/// Terrasoft.Common.ItemNotFoundException ("column at path UsrTerms.Name not found in schema UsrOrder"), and
/// everything built from that ESQ fails - also the rows and messages that never read the column.
/// The usual cause: a column added in the designer on one environment, in a package nobody exported, so it
/// is in no repository and on no other site (`describe.py index -e <env>` lists such columns per object).
/// Guard: esq.RootSchema.FindSchemaColumnByPath(path) returns null for a missing path (one level or a lookup
/// path), GetSchemaColumnByPath throws ItemNotFoundException - verified 2026-11-21 against the 8.3.2
/// Terrasoft.Core.dll (an EntitySchema with no such column, both forms of the path).
/// Add the optional columns only when the schema has them, and read them back only when they were added.
/// </summary>
class HowToGuardESQAgainstMissingColumn {

    // 1. Add a column only when this environment's schema has it; returns the ESQ column or null
    public EntitySchemaQueryColumn AddColumnIfExists(EntitySchemaQuery esq, string path) {
        return esq.RootSchema.FindSchemaColumnByPath(path) == null ? null : esq.AddColumn(path);
    }

    // 2. Read rows with an optional column: the query never names a column the site does not have
    public List<string> ReadOrderTerms(UserConnection userConnection) {
        var esq = new EntitySchemaQuery(userConnection.EntitySchemaManager, "UsrOrder");
        esq.AddColumn("UsrNumber");
        var terms = AddColumnIfExists(esq, "UsrTerms.Name");
        var result = new List<string>();
        foreach (var order in esq.GetEntityCollection(userConnection)) {
            var text = terms == null ? string.Empty : order.GetTypedColumnValue<string>(terms.Name);
            result.Add(order.GetTypedColumnValue<string>("UsrNumber") + " " + text);
        }
        return result;
    }
}
