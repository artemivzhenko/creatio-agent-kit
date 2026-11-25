using CreatioAutoTests.Execution;
using CreatioAutoTests.Validation.Validators;

namespace CreatioAutoTests.Commands;

/// <summary>
/// Opens a configured page, optionally an existing record; or, with <c>process-task</c>, the page of a running pre-configured page task
/// of a process (S45-T09): such a page has no address of its own, the application opens it from the task's element id.
/// </summary>
[Command("open", Validator = typeof(PageValidator), Usage = "open <page> [for <recordId>] | open process-task <process> on <page>")]
public sealed class OpenCommand : ICommand
{
    /// <summary>Whether the line is the <c>open process-task</c> form.</summary>
    internal static bool IsProcessTask(ParsedCommand command) =>
        command.ArgumentCount > 0 && string.Equals(command.ValueAt(0), "process-task", StringComparison.OrdinalIgnoreCase);

    /// <summary>Opens the validated configured page, optionally using the supplied record identifier.</summary>
    public Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default)
    {
        if (IsProcessTask(context.Command))
        {
            return context.Session.OpenProcessTaskAsync(context.Command.ValueAt(1)!, context.Command.ValueAt(3)!, cancellationToken);
        }

        var pageName = context.Command.ValueAt(0)!;
        var recordId = context.Command.ArgumentCount == 3 ? context.ResolveValue(2) : null;

        return context.Session.OpenPageAsync(pageName, recordId, cancellationToken);
    }
}
