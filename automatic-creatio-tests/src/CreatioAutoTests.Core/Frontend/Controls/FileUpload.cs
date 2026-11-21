using Microsoft.Playwright;

namespace CreatioAutoTests.Frontend.Controls;

/// <summary>Extra members a file upload declares in its page file.</summary>
public sealed class FileUploadOptions
{
    /// <summary>
    /// The <c>element-name</c> of the button that opens the file chooser, when it is not inside the list itself
    /// (the Freedom attachments list has its <c>AttachmentAddButton</c> beside it). Empty: the first button inside the element.
    /// </summary>
    public string Trigger { get; set; } = string.Empty;
}

/// <summary>
/// A place a file is put into: the Freedom UI file list (<c>crt-file-list</c>) and the pages built around a file input (S34-T04).
/// <c>upload X "file"</c> sets the files of the element's own <c>input[type=file]</c> when there is one, otherwise it clicks the
/// trigger button and answers the file chooser it opens. Nothing here reads the file: the path was checked before the browser opened.
/// </summary>
[UiElement("FileUpload", HostTag = "crt-file-list", Options = typeof(FileUploadOptions))]
public sealed class FileUpload : FreedomElementBase, IUploadable
{
    private readonly FileUploadOptions _options;

    /// <summary>Initializes the element against its configured page control.</summary>
    public FileUpload(ElementRuntimeContext context) : base(context)
    {
        _options = context.Definition.BindOptions<FileUploadOptions>();
    }

    /// <summary>Puts the file into the element, through its input or through the chooser its trigger opens.</summary>
    public async Task UploadAsync(string path, CancellationToken cancellationToken = default)
    {
        if (!await ExistsAsync(cancellationToken).ConfigureAwait(false))
        {
            throw NotFound();
        }

        var input = Root.Locator("input[type=file]");
        if (await input.CountAsync().ConfigureAwait(false) > 0)
        {
            await input.First.SetInputFilesAsync(path).ConfigureAwait(false);
            return;
        }

        var trigger = string.IsNullOrWhiteSpace(_options.Trigger)
            ? Root.Locator("button").First
            : Page.Locator("[element-name=\"" + _options.Trigger + "\"] button").First;
        var chooser = await Page.RunAndWaitForFileChooserAsync(
            () => trigger.ClickAsync(new LocatorClickOptions { Timeout = TimeoutMs }),
            new PageRunAndWaitForFileChooserOptions { Timeout = TimeoutMs }).ConfigureAwait(false);
        await chooser.SetFilesAsync(path).ConfigureAwait(false);
    }
}
