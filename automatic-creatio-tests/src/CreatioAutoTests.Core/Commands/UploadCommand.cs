using CreatioAutoTests.Frontend;
using CreatioAutoTests.Validation.Validators;

namespace CreatioAutoTests.Commands;

/// <summary>
/// Puts a file of <c>TestData/</c> into a file element: <c>upload AttachmentList "requisites-ok.xlsx"</c> (S34-T04).
/// The path was resolved and its file found by the validator, before any browser opened.
/// </summary>
[Command("upload", Validator = typeof(UploadValidator), SupportedTargets = new[] { typeof(IUploadable) },
    Usage = "upload <code> \"<path under TestData>\"")]
public sealed class UploadCommand : ICommand
{
    /// <summary>Resolves the path under the test data directory and hands it to the element.</summary>
    public Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default) =>
        context.Target<IUploadable>().UploadAsync(
            UploadValidator.Resolve(context.Session.Settings.TestDataDirectory, context.ResolveValue(1), out _)!, cancellationToken);
}
