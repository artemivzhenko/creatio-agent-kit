using CreatioAutoTests.Execution;
using CreatioAutoTests.Validation.Validators;

namespace CreatioAutoTests.Commands;

/// <summary>
/// Waits for the pre-configured page task a UI line started (a host page's button or Save starts the process, the page opens over it)
/// and binds the page, scoped to the dialog it is shown in (S48-T11). The case did not 'start' the process, so the task is waited for;
/// the page is opened only when the application has not shown it itself. The rest is 'open process-task' (S45-T09).
///   wait-process-task UsrOrder_Process on UsrOrderTaskPage within 30 second
/// </summary>
[Command("wait-process-task", Validator = typeof(WaitProcessTaskValidator),
    Usage = "wait-process-task <process> on <page> [within <n> second|minute]")]
public sealed class WaitProcessTaskCommand : ICommand
{
    /// <summary>Finds the waiting task within the budget (the page check timeout without 'within') and binds its page.</summary>
    public Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default)
    {
        var budgetMs = WaitShapes.TrySplit(context.Command, "wait-process-task", out _, out var within, out _) ? within : (int?)null;
        return context.Session.WaitProcessTaskAsync(context.Command.ValueAt(0)!, context.Command.ValueAt(2)!, budgetMs, cancellationToken);
    }
}
