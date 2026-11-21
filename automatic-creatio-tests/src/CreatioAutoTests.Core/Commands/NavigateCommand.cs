using CreatioAutoTests.Validation.Validators;

namespace CreatioAutoTests.Commands;

/// <summary>
/// Opens a configured page the way a user moves inside the application: through the Shell address (<c>location.hash</c>) of the page already
/// open in the current tab, without loading the application again (S34-T06). The card the tab stood on is left by the application itself,
/// so what it does on its way out (stops listening, <c>destroy</c>) is what a user's navigation does; <c>open</c> loads a URL and ends it differently.
///   navigate UsrOrderSection
///   navigate UsrOrderPage for $B
/// </summary>
[Command("navigate", Validator = typeof(NavigateValidator), Usage = "navigate <page> [for <recordId>]")]
public sealed class NavigateCommand : ICommand
{
    /// <summary>Moves the current tab to the page's Shell address and waits for the page to be ready.</summary>
    public Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default) =>
        context.Session.NavigatePageAsync(context.Command.ValueAt(0)!, context.Command.ArgumentCount == 3 ? context.ResolveValue(2) : null, cancellationToken);
}
