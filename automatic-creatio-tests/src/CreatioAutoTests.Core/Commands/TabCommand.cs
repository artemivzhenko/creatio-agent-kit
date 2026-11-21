using CreatioAutoTests.Validation.Validators;

namespace CreatioAutoTests.Commands;

/// <summary>Opens a second tab of the session or switches between the open ones; pages stay open until the case ends.</summary>
[Command("tab", Validator = typeof(TabValidator), Usage = "tab new [as <name>] | tab <number|name>")]
public sealed class TabCommand : ICommand
{
    /// <summary>Opens a blank tab (the next 'open' loads into it) or makes the named one the active tab.</summary>
    public Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default)
    {
        var command = context.Command;
        return command.ArgumentAt(0)!.IsQuoted || !string.Equals(command.ValueAt(0), "new", StringComparison.OrdinalIgnoreCase)
            ? context.Session.SwitchTabAsync(command.ValueAt(0)!, cancellationToken)
            : context.Session.NewTabAsync(command.ArgumentCount == 3 ? command.ValueAt(2) : null, cancellationToken);
    }
}
