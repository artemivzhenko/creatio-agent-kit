using CreatioAutoTests.Execution;
using CreatioAutoTests.Validation.Validators;
using Microsoft.Extensions.Logging;

namespace CreatioAutoTests.Commands;

/// <summary>
/// Repeats a <c>check-record</c> over OData until it holds or the budget ends: an asynchronous process changes the record a
/// second or twenty after the click, and a fixed 'wait' is slow when it is fast and flaky when it is slow (S34-T03).
///   wait-record UsrOrder Id=$B has UsrStatus eq Done within 30 second
/// </summary>
[Command("wait-record", Validator = typeof(WaitRecordValidator),
    Usage = "wait-record <object> <filter> [not] exists|has <column> <op> <value> within <n> second|minute")]
public sealed class WaitRecordCommand : ICommand
{
    /// <summary>Polls the check; on failure the message says how long it waited and what the last read showed.</summary>
    public Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default) =>
        WaitPolling.RunAsync(context, "check-record", new CheckRecordCommand(), cancellationToken);
}

/// <summary>
/// Repeats a <c>check-count</c> until it holds or the budget ends.
///   wait-count UsrQueue Order/Id=$B ge 2 within 60 second
/// </summary>
[Command("wait-count", Validator = typeof(WaitCountValidator), Usage = "wait-count <object> Column=Value;... eq|ne|gt|ge|lt|le <number> within <n> second|minute")]
public sealed class WaitCountCommand : ICommand
{
    /// <summary>Polls the check; on failure the message says how long it waited and what the last count was.</summary>
    public Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default) =>
        WaitPolling.RunAsync(context, "check-count", new CheckCountCommand(), cancellationToken);
}

/// <summary>The polling both wait commands share: a check that fails because the condition is false is read again, nothing else is.</summary>
public static class WaitPolling
{
    internal static async Task RunAsync(CommandContext context, string checkKeyword, ICommand check, CancellationToken cancellationToken)
    {
        WaitShapes.TrySplit(context.Command, checkKeyword, out var line, out var budgetMs, out _);
        var inner = new CommandContext(context.Step with { Command = line }, context.Targets, context.Session, context.Logger);
        await PollAsync(() => check.ExecuteAsync(inner, cancellationToken), budgetMs, context, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>Runs <paramref name="attempt"/> until it stops throwing <see cref="CommandFailedException"/> or the budget ends (then the last message is the failure).</summary>
    public static async Task PollAsync(Func<Task> attempt, int budgetMs, CommandContext context, CancellationToken cancellationToken)
    {
        var started = DateTime.UtcNow;
        var polls = 0;
        while (true)
        {
            polls++;
            try
            {
                await attempt().ConfigureAwait(false);
                context.Logger.LogDebug("'{Line}' held after {Seconds:0.0} s ({Polls} read(s)).", context.Command.RawText, (DateTime.UtcNow - started).TotalSeconds, polls);
                return;
            }
            catch (CommandFailedException failure)
            {
                // A false condition is read again; an error of the read itself (a bad column, the service down) is not a condition.
                var waited = DateTime.UtcNow - started;
                var pause = waited.TotalSeconds < 10 ? context.Session.Settings.PollIntervalMs : context.Session.Settings.PollIntervalMs * 2;
                var remaining = budgetMs - waited.TotalMilliseconds;
                if (remaining <= 0)
                {
                    throw new CommandFailedException("gave up after " + Math.Round(waited.TotalSeconds) + " s (" + polls + " read(s), " + budgetMs / 1000 + " s allowed): " + failure.Message);
                }

                // The last read is taken at the end of the budget, not a pause before it.
                await Task.Delay((int)Math.Min(pause, remaining), cancellationToken).ConfigureAwait(false);
            }
        }
    }
}
