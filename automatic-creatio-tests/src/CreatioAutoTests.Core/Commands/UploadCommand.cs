using CreatioAutoTests.Frontend;
using CreatioAutoTests.Validation.Validators;

namespace CreatioAutoTests.Commands;

/// <summary>
/// Puts a file of <c>TestData/</c> into a file element: <c>upload AttachmentList "requisites-ok.xlsx"</c> (S34-T04).
/// A Button takes the file through the chooser its own handler opens (S45-T08). The path was resolved and its file found by the validator, before any browser opened.
/// </summary>
[Command("upload", Validator = typeof(UploadValidator), SupportedTargets = new[] { typeof(IUploadable) },
    Usage = "upload <code> \"<path under TestData>\"")]
public sealed class UploadCommand : ICommand
{
    /// <summary>Resolves the path under the test data directory and hands it to the element.</summary>
    public async Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default)
    {
        var target = context.Target<IUploadable>();
        await target.UploadAsync(
            UploadValidator.Resolve(context.Session.Settings.TestDataDirectory, context.ResolveValue(1), out _)!, cancellationToken).ConfigureAwait(false);
        if (target is Frontend.Controls.Button)
        {
            DevOnly.Note(context, "upload through the button's file chooser: " + target.Code);
        }
    }
}
