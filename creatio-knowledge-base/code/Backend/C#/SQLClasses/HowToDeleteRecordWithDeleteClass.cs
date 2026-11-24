using System;
using Terrasoft.Core;
using Terrasoft.Core.DB;

/// <summary>
/// Demonstrates how to delete records using the Delete query builder (raw SQL layer).
/// Use this approach instead of the Entity model when:
///   - you need maximum performance (no entity event handlers are triggered);
///   - you are doing a mass delete and don't need business logic to run.
/// WARNING: Delete bypasses all entity event handlers (Deleting, Deleted, etc.).
/// A parameter that must carry its type (a text compared on a column the engine would otherwise cast) is
/// Column.Parameter(value, (DBDataValueType)userConnection.DataValueTypeManager.GetInstanceByName("Text")); a
/// date-only compare on a DateTime column is Func.Cast("CreatedOn", <the "Date" type>) against a Date parameter -
/// comparing the DateTime to midnight misses every row with a time (method 3).
/// </summary>
class HowToDeleteRecordWithDeleteClass {

    // 1. Delete a single record by Id
    public void DeleteSingleRecord(UserConnection userConnection, Guid recordId) {
        var delete = new Delete(userConnection)
            .From("MyEntity")
            .Where("Id").IsEqual(Column.Parameter(recordId)) as Delete;

        // Execute returns the number of affected rows
        int affectedRows = delete.Execute();

        if (affectedRows != 1) {
            // Handle failure: log, throw, or return false to the caller
            throw new InvalidOperationException(
                $"Expected to delete 1 row in MyEntity, but {affectedRows} rows were affected.");
        }
    }

    // 2. Mass-delete records older than X days — wrapped in an explicit transaction
    public int PurgeOldRecords(UserConnection userConnection, int daysBack) {
        using (DBExecutor dbExecutor = userConnection.EnsureDBConnection()) {
            dbExecutor.StartTransaction();

            var delete = new Delete(userConnection)
                .From("MyEntity")
                .Where("CreatedOn").IsLess(Column.Parameter(DateTime.UtcNow.AddDays(-daysBack))) as Delete;

            int affectedRows = delete.Execute(dbExecutor);

            dbExecutor.CommitTransaction();
            return affectedRows;
        }
    }

    // 3. One day's rows of one kind: the date-only compare (a cast) and a typed text parameter
    public int DeleteOneDay(UserConnection userConnection, DateTime day, string kind) {
        var date = (DBDataValueType)userConnection.DataValueTypeManager.GetInstanceByName("Date");
        var text = (DBDataValueType)userConnection.DataValueTypeManager.GetInstanceByName("Text");
        var delete = new Delete(userConnection)
            .From("UsrOrderLog")
            .Where(Func.Cast("CreatedOn", date)).IsEqual(Column.Parameter(day.Date, date))
            .And("UsrKind").IsEqual(Column.Parameter(kind, text)) as Delete;
        return delete.Execute();
    }
}
