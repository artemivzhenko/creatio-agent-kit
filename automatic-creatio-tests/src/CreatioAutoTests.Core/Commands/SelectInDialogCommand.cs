using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Frontend.Controls;
using CreatioAutoTests.Validation.Validators;

namespace CreatioAutoTests.Commands;

/// <summary>
/// Ticks the rows of a record selection window by their display value (<c>select-in-dialog "Supervisor; Sales"</c>); the window's own
/// buttons are then pressed with <c>answer "Select"</c> (S44-T08). A value that is not a row fails the step with the rows the window showed.
/// </summary>
[Command("select-in-dialog", Validator = typeof(SelectInDialogValidator), Usage = "select-in-dialog \"<value>; <value>\"")]
public sealed class SelectInDialogCommand : ICommand
{
    /// <summary>Waits for the window and its rows within the element timeout, then ticks them.</summary>
    public async Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default)
    {
        var wanted = QuickFilter.ParseValues(context.ResolveValue(0));
        var failed = await DialogProbe.TickRowsAsync(context.Session.RequirePage(), wanted, context.Session.Settings.ElementTimeoutMs, cancellationToken)
            .ConfigureAwait(false);
        if (failed is { } f)
        {
            throw new CommandFailedException(!f.WindowShown
                ? "'select-in-dialog': no dialog is shown."
                : "'select-in-dialog': the window has no row " + string.Join(", ", f.Missing.Select(m => "\"" + m + "\"")) + ". It shows " +
                  (f.Rows.Count == 0 ? "no rows." : string.Join("; ", f.Rows.Select(r => "{" + r + "}")) + "."));
        }
    }
}
