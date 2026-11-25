using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Validation.Validators;

namespace CreatioAutoTests.Commands;

/// <summary>
/// Clicks an element. Reference implementation of a command: the attribute states the keyword, the
/// validator and the capability required, and the body does exactly one thing.
/// Declaring <see cref="IClickable"/> rather than a concrete class is what will let a future Tab
/// element work with 'click' without this file changing.
/// </summary>
[Command("click",
    Validator = typeof(SingleTargetValidator),
    SupportedTargets = new[] { typeof(IClickable) },
    Usage = "click <code> [no-answer | expect error \"<text>\"]")]
public sealed class ClickCommand : ICommand
{
    /// <summary>Delegates clicking to the resolved target's declared capability.</summary>
    public async Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default)
    {
        var expect = DataShapes.ExpectError(context.Command);
        if (!expect.Expected)
        {
            await context.Target<IClickable>().ClickAsync(cancellationToken).ConfigureAwait(false);
            return;
        }

        // S46-T06: the refusal is the pass; a save that went through (nothing shown) or another text fails the line.
        var shown = await context.Target<IRefusable>().ClickReadingRefusalAsync(expect.Text!, cancellationToken).ConfigureAwait(false);
        if (!shown.Contains(expect.Text!, StringComparison.OrdinalIgnoreCase))
        {
            throw new CommandFailedException("expected the refusal \"" + expect.Text + "\", the page showed: " +
                                             (shown.Length == 0 ? "nothing (the save went through, or no message appeared)" : shown));
        }
    }
}
