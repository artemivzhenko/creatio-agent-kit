using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Validation.Validators;

namespace CreatioAutoTests.Commands;

/// <summary>
/// Presses a button of the visible dialog by its caption (<c>answer "No"</c>), case-blind: Classic shows captions upper-cased by CSS.
/// The dialog is the one a <c>set ... no-answer</c>, a <c>click</c> or the page itself left open (S34-T02).
/// </summary>
[Command("answer", Validator = typeof(AnswerValidator), Usage = "answer \"<button caption>\"")]
public sealed class AnswerCommand : ICommand
{
    /// <summary>Waits for the dialog and its button within the element timeout; fails naming the buttons that were there.</summary>
    public async Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default)
    {
        var caption = context.ResolveValue(0);
        var buttons = await DialogProbe.AnswerAsync(context.Session.RequirePage(), caption, context.Session.Settings.ElementTimeoutMs, cancellationToken)
            .ConfigureAwait(false);
        if (buttons is not null)
        {
            throw new CommandFailedException(buttons.Count == 0
                ? "'answer \"" + caption + "\"': no dialog is shown."
                : "'answer \"" + caption + "\"': the dialog has no such button; its buttons are " + string.Join(", ", buttons.Select(b => "\"" + b + "\"")) + ".");
        }
    }
}
