using System;
using System.Collections.Generic;
using Terrasoft.Core;
using Terrasoft.Core.Entities;

/// <summary>
/// Pattern: a queue table drained by a scheduled job, with an attempt limit and a terminal state.
/// A queue with no attempt limit, drained by a one-minute timer, retried the same few thousand rows forever:
/// tens of millions of attempts and millions of calls a day to the external system (seen on 8.3). Every row
/// therefore carries UsrAttempts and a status: Pending -> Done, or Failed when UsrAttempts reaches the maximum,
/// or Rejected at once for an error no retry fixes (a recipient that cannot be matched, a record that is gone).
/// The job reads only Pending rows under the limit, in batches, oldest first.
/// An in-memory queue (a static ConcurrentQueue in a class) dies with every application restart and is filled
/// again by whatever re-sends - a Quartz worker over it de-duplicates by a business key and a time window
/// (60 s); prefer the table when the work must survive a restart.
/// UsrSyncQueue (UsrRecordId, UsrStatus lookup, UsrAttempts, UsrLastError) is a placeholder object.
/// </summary>
class HowToDrainQueueTableWithAttemptLimit {

    const int MaxAttempts = 5;
    const int BatchSize = 100;
    static readonly Guid StatusPending = new Guid("00000000-0000-0000-0000-0000000000a1");
    static readonly Guid StatusDone = new Guid("00000000-0000-0000-0000-0000000000a2");
    static readonly Guid StatusFailed = new Guid("00000000-0000-0000-0000-0000000000a3");
    static readonly Guid StatusRejected = new Guid("00000000-0000-0000-0000-0000000000a4");

    /// <summary>An error the next attempt cannot fix: the row goes to Rejected at once.</summary>
    public class PermanentException : Exception {
        public PermanentException(string message) : base(message) { }
    }

    // 1. One run of the job: a batch of pending rows, each sent once, its state written back
    public void Drain(UserConnection userConnection, Action<Guid> send) {
        foreach (var row in ReadBatch(userConnection)) {
            int attempts = row.GetTypedColumnValue<int>("UsrAttempts") + 1;
            row.SetColumnValue("UsrAttempts", attempts);
            try {
                send(row.GetTypedColumnValue<Guid>("UsrRecordId"));
                row.SetColumnValue("UsrStatusId", StatusDone);
            } catch (PermanentException e) {
                row.SetColumnValue("UsrStatusId", StatusRejected);
                row.SetColumnValue("UsrLastError", e.Message);
            } catch (Exception e) {
                row.SetColumnValue("UsrStatusId", attempts >= MaxAttempts ? StatusFailed : StatusPending);
                row.SetColumnValue("UsrLastError", e.Message);
            }
            row.Save(false);
        }
    }

    // 2. Pending rows under the limit, oldest first, one batch
    IEnumerable<Entity> ReadBatch(UserConnection userConnection) {
        var esq = new EntitySchemaQuery(userConnection.EntitySchemaManager, "UsrSyncQueue") { RowCount = BatchSize };
        esq.PrimaryQueryColumn.IsAlwaysSelect = true;
        esq.AddColumn("UsrRecordId");
        esq.AddColumn("UsrAttempts");
        esq.AddColumn("CreatedOn").OrderByAsc();
        esq.Filters.Add(esq.CreateFilterWithParameters(FilterComparisonType.Equal, "UsrStatus", StatusPending));
        esq.Filters.Add(esq.CreateFilterWithParameters(FilterComparisonType.Less, "UsrAttempts", MaxAttempts));
        return esq.GetEntityCollection(userConnection);
    }
}
