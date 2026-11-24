using System;
using System.Linq;
using Terrasoft.Common;
using Terrasoft.Core;
using Terrasoft.Core.Entities;

/// <summary>
/// Demonstrates how to compute a sum or a count with EntitySchemaQuery in one round trip instead of loading the rows.
/// Add the aggregate with esq.AddColumn(esq.CreateAggregationFunction(AggregationTypeStrict.Sum, "UsrAmount")): the query
/// returns ONE row and the value sits in a column whose name the platform generates - read it by the returned column's
/// Name, never by "UsrAmount" (that name is not in the row). A count is AggregationTypeStrict.Count over "Id".
/// Whose rows are counted follows the query's rights setting (see HowToControlAdminRights): a total shown to a user counts
/// the user's rows; a system-wide figure (a limit check, a background job) runs on SystemUserConnection and says so in a
/// comment. UseAdminRights = false lifts the record rights (the default true checks them, P-3.13): a system-wide count
/// on the caller's connection is `false` with a comment saying why.
/// </summary>
class HowToAggregateWithESQ {

    // 1. Sum of a money column over the filtered rows
    public decimal SumOpenAmount(UserConnection userConnection, Guid accountId) {
        var esq = new EntitySchemaQuery(userConnection.EntitySchemaManager, "UsrOrder");
        EntitySchemaQueryColumn total = esq.AddColumn(esq.CreateAggregationFunction(AggregationTypeStrict.Sum, "UsrAmount"));
        esq.Filters.Add(esq.CreateFilterWithParameters(FilterComparisonType.Equal, "UsrAccount", accountId));
        Entity row = esq.GetEntityCollection(userConnection).FirstOrDefault();
        // The column's name is generated: total.Name, not "UsrAmount".
        return row == null ? 0m : row.GetTypedColumnValue<decimal>(total.Name);
    }

    // 2. Count of rows: Count over Id
    public int CountOrders(UserConnection userConnection, Guid accountId) {
        var esq = new EntitySchemaQuery(userConnection.EntitySchemaManager, "UsrOrder");
        EntitySchemaQueryColumn count = esq.AddColumn(esq.CreateAggregationFunction(AggregationTypeStrict.Count, "Id"));
        esq.Filters.Add(esq.CreateFilterWithParameters(FilterComparisonType.Equal, "UsrAccount", accountId));
        Entity row = esq.GetEntityCollection(userConnection).FirstOrDefault();
        return row == null ? 0 : row.GetTypedColumnValue<int>(count.Name);
    }

    // 3. A system-wide count for a limit check: on the system connection, never the caller's
    public int CountAllOrders(UserConnection systemUserConnection) {
        // why: a limit counts every order in the system, not the ones the current user happens to see
        var esq = new EntitySchemaQuery(systemUserConnection.EntitySchemaManager, "UsrOrder");
        EntitySchemaQueryColumn count = esq.AddColumn(esq.CreateAggregationFunction(AggregationTypeStrict.Count, "Id"));
        Entity row = esq.GetEntityCollection(systemUserConnection).FirstOrDefault();
        return row == null ? 0 : row.GetTypedColumnValue<int>(count.Name);
    }
}
