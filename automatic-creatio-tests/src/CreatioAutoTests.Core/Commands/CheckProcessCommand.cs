using System.Globalization;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Validation.Validators;
using Microsoft.Extensions.Logging;

namespace CreatioAutoTests.Commands;

/// <summary>
/// Reads the process log for a process the case did not start - one a signal or a timer started (S34-T07).
///   check-process UsrOrder_Process for $B started within 30 second
///   check-process UsrOrder_Process for $B step "Status" completed within 2 minute
///   check-process UsrOrder_Process running
/// The runs are those that started after the line before this one began (the platform links a run to a record only in binary
/// process data, so the time is the link); steps come from the element log. A site that logs no process at all fails with
/// "process logging is off", not "step not found". `within` polls like 'wait-record'.
/// </summary>
[Command("check-process", Validator = typeof(CheckProcessValidator),
    Usage = "check-process <process> [for $record] started | running | step \"<caption>\" completed|running [within <n> second|minute]")]
public sealed class CheckProcessCommand : ICommand
{
    /// <summary>Checks once, or polls within the budget.</summary>
    public async Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default)
    {
        CheckProcessShapes.TryParse(context.Command, out var check, out _);
        var since = context.Session.PreviousLineStartedUtc;
        var any = await context.Session.QueryRecordsAsync("SysProcessLog", new[] { "Id" }, "StartDate ge 2000-01-01T00:00:00.000Z", 1, cancellationToken).ConfigureAwait(false);
        if (any.Count == 0)
        {
            throw new CommandFailedException("process logging is off for " + check.Process + ": the site's process log is empty; switch the logging on in the process settings.");
        }

        if (check.BudgetMs == 0)
        {
            await OnceAsync(context, check, since, cancellationToken).ConfigureAwait(false);
            return;
        }

        await WaitPolling.PollAsync(() => OnceAsync(context, check, since, cancellationToken), check.BudgetMs, context, cancellationToken).ConfigureAwait(false);
    }

    private static async Task OnceAsync(CommandContext context, ProcessCheck check, DateTime since, CancellationToken cancellationToken)
    {
        var literal = since.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'", CultureInfo.InvariantCulture);
        // The run this case started itself counts whenever it began (S45-T09: a page task completes long after its 'start').
        var own = context.Session.LastProcess is { Success: true } last && string.Equals(last.Process, check.Process, StringComparison.OrdinalIgnoreCase) &&
                  Guid.TryParse(last.ProcessId, out _)
            ? " or Id eq " + last.ProcessId
            : string.Empty;
        var runs = await context.Session.QueryRecordsAsync("SysProcessLog", new[] { "Id", "CompleteDate", "ErrorDescription" },
            ProcessFilter(check.Process) + " and (StartDate ge " + literal + own + ")", 50, cancellationToken).ConfigureAwait(false);
        context.Logger.LogDebug("{Process}: {Count} run(s) since {Since}: {Ids}", check.Process, runs.Count, literal, string.Join(",", runs.Select(r => r["Id"])));
        if (runs.Count == 0)
        {
            throw new CommandFailedException("no run of " + check.Process + " started since " + literal + " (the line before this one began).");
        }

        switch (check.Kind)
        {
            case "started":
                return;
            case "running":
                if (runs.All(r => Done(r["CompleteDate"])))
                {
                    throw new CommandFailedException(runs.Count + " run(s) of " + check.Process + " since " + literal + ", none is running: " + Describe(runs) + ".");
                }

                return;
        }

        var wantComplete = check.Kind == "step-completed";
        var elements = await context.Session.QueryRecordsAsync("SysProcessElementLog", new[] { "Caption", "CompleteDate", "ErrorDescription" },
            string.Join(" or ", runs.Select(r => "SysProcess/Id eq " + r["Id"])), 500, cancellationToken).ConfigureAwait(false);
        var steps = elements.Where(e => string.Equals(e["Caption"], check.Caption, StringComparison.OrdinalIgnoreCase)).ToArray();
        if (steps.Any(e => Done(e["CompleteDate"]) == wantComplete))
        {
            return;
        }

        var seen = string.Join(", ", elements.Select(e => "\"" + e["Caption"] + "\" (" + (Done(e["CompleteDate"]) ? "completed" : "running") + ")").Distinct());
        throw new CommandFailedException("step \"" + check.Caption + "\" of " + check.Process + " is not " + (wantComplete ? "completed" : "running") + "; " +
                                         (steps.Length == 0 ? "no such step; steps seen: " + (seen.Length == 0 ? "(none)" : seen) : "it is " + (wantComplete ? "running" : "completed")) + ".");
    }

    /// <summary>The runs of the process or of a replacing version of it (a replacing schema has another name and the replaced one as its parent).</summary>
    internal static string ProcessFilter(string process) => "(SysSchema/Name eq '" + process + "' or SysSchema/Parent/Name eq '" + process + "')";

    /// <summary>OData answers a date a row has not got yet as <c>0001-01-01T00:00:00Z</c>, not as null.</summary>
    internal static bool Done(string completeDate) => !string.IsNullOrEmpty(completeDate) && !completeDate.StartsWith("0001-01-01", StringComparison.Ordinal);

    private static string Describe(IReadOnlyList<IReadOnlyDictionary<string, string>> runs) =>
        string.Join(", ", runs.Take(5).Select(r => r["Id"] + (string.IsNullOrEmpty(r["ErrorDescription"]) ? " completed" : " failed: " + r["ErrorDescription"].Split('\n')[0])));
}
