using CreatioAutoTests.Execution;
using Microsoft.Extensions.Logging;
using Microsoft.Playwright;

namespace CreatioAutoTests.Frontend.Controls;

/// <summary>
/// Freedom UI button (crt-button). Save behaviour is data driven through <see cref="ButtonOptions"/>
/// rather than a hard-coded type enum, so a project can describe its own buttons in configuration.
/// </summary>
[UiElement("Button", HostTag = "crt-button", Options = typeof(ButtonOptions))]
public sealed class Button : FreedomElementBase, IRefusable, IUploadable
{
    private const string NotificationSelector = "output[data-qa=\"notificationPopup\"].crt-notify-message";

    private const string ValidationSelector = "mat-error, .mat-mdc-form-field-error, [role=\"alert\"], [class*=\"validation-message\"], [class*=\"error-message\"]";

    private readonly ButtonOptions _options;

    /// <summary>Initializes a button using behavior supplied by its configuration options.</summary>
    public Button(ElementRuntimeContext context) : base(context)
    {
        _options = context.Definition.BindOptions<ButtonOptions>();
    }


    /// <summary>Supports the caption variants used by Freedom UI button implementations.</summary>
    protected override ILocator LabelLocator =>
        Root.Locator(".crt-button-caption, .btn-reversible-content, .mdc-button__label");

    private ILocator Clickable => Root.Locator("button, .mdc-button, .mat-mdc-unelevated-button");

    /// <summary>
    /// Performs the <c>click</c> command and applies configured save confirmation behavior. A
    /// configured second Save click is a workaround for Creatio dropping the first click, not a
    /// timing guess.
    /// </summary>
    public async Task ClickAsync(CancellationToken cancellationToken = default)
    {
        if (!await ExistsAsync(cancellationToken).ConfigureAwait(false))
        {
            throw NotFound();
        }

        await EnsureEnabledAsync().ConfigureAwait(false);

        var target = await ResolveClickTargetAsync().ConfigureAwait(false);
        await target.ClickAsync(new LocatorClickOptions { Timeout = TimeoutMs }).ConfigureAwait(false);

        if (_options.SettleMs > 0)
        {
            await Page.WaitForTimeoutAsync(_options.SettleMs).ConfigureAwait(false);
        }

        if (!_options.IsSave)
        {
            return;
        }

        await CompleteSaveAsync(target, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>
    /// <c>click X expect error "text"</c>: the click without the save wait, then the page's refusal read from the three places a
    /// Freedom UI page shows one - the message under a control, the error toast, a dialog.
    /// </summary>
    public async Task<string> ClickReadingRefusalAsync(string expected, CancellationToken cancellationToken = default)
    {
        if (!await ExistsAsync(cancellationToken).ConfigureAwait(false))
        {
            throw NotFound();
        }

        await EnsureEnabledAsync().ConfigureAwait(false);
        var target = await ResolveClickTargetAsync().ConfigureAwait(false);
        await target.ClickAsync(new LocatorClickOptions { Timeout = TimeoutMs }).ConfigureAwait(false);

        var until = DateTime.UtcNow.AddMilliseconds(Math.Min(_options.DisappearTimeoutMs, 8000));
        var shown = string.Empty;
        while (true)
        {
            shown = await ReadRefusalAsync().ConfigureAwait(false);
            if (shown.Contains(expected, StringComparison.OrdinalIgnoreCase) || DateTime.UtcNow >= until)
            {
                return shown;
            }

            await Task.Delay(250, cancellationToken).ConfigureAwait(false);
        }
    }

    private async Task<string> ReadRefusalAsync()
    {
        var parts = new List<string>();
        try
        {
            parts.AddRange(await Page.Locator(ValidationSelector).AllInnerTextsAsync().ConfigureAwait(false));
            parts.AddRange(await Page.Locator(NotificationSelector).AllInnerTextsAsync().ConfigureAwait(false));
        }
        catch (PlaywrightException)
        {
            // the page is moving: the next poll reads again
        }

        parts.AddRange((await DialogProbe.ReadAsync(Page).ConfigureAwait(false)).Select(d => d.Text));
        return string.Join(" | ", parts.Select(p => p.Trim()).Where(p => p.Length > 0).Distinct());
    }

    /// <summary>
    /// <c>upload Button "file"</c> (S45-T08): a button whose handler opens its own file chooser. The click is made inside the chooser event,
    /// the file is set, and the page is given time to go idle. A button that opens no chooser fails with the button's code.
    /// </summary>
    public async Task UploadAsync(string path, CancellationToken cancellationToken = default)
    {
        if (!await ExistsAsync(cancellationToken).ConfigureAwait(false))
        {
            throw NotFound();
        }

        await EnsureEnabledAsync().ConfigureAwait(false);
        var target = await ResolveClickTargetAsync().ConfigureAwait(false);
        await UploadThroughChooserAsync(
            Code,
            path,
            async () => await Page.RunAndWaitForFileChooserAsync(
                () => target.ClickAsync(new LocatorClickOptions { Timeout = TimeoutMs }),
                new PageRunAndWaitForFileChooserOptions { Timeout = TimeoutMs }).ConfigureAwait(false)).ConfigureAwait(false);
        try
        {
            await Page.WaitForLoadStateAsync(LoadState.NetworkIdle, new PageWaitForLoadStateOptions { Timeout = TimeoutMs }).ConfigureAwait(false);
        }
        catch (TimeoutException)
        {
            Logger.LogDebug("The page did not go idle after {Code} took the file.", Code);
        }
    }

    /// <summary>Waits for the chooser the click opens and gives it the file; no chooser within the timeout is a failed line.</summary>
    internal static async Task UploadThroughChooserAsync(string code, string path, Func<Task<IFileChooser>> openChooser)
    {
        IFileChooser chooser;
        try
        {
            chooser = await openChooser().ConfigureAwait(false);
        }
        catch (TimeoutException)
        {
            throw new CommandFailedException("no file chooser opened by " + code);
        }

        await chooser.SetFilesAsync(path).ConfigureAwait(false);
    }

    private async Task<ILocator> ResolveClickTargetAsync()
    {
        return await Clickable.CountAsync().ConfigureAwait(false) > 0 ? Clickable.First : Root;
    }

    private async Task EnsureEnabledAsync()
    {
        var ariaDisabled = await SafeAttributeAsync(Root, "aria-disabled").ConfigureAwait(false);
        var disabled = await SafeAttributeAsync(Root, "disabled").ConfigureAwait(false);

        if (string.Equals(ariaDisabled, "true", StringComparison.OrdinalIgnoreCase) || disabled is not null)
        {
            throw new InvalidOperationException("Button '" + Code + "' is disabled and cannot be clicked.");
        }
    }

    /// <summary>Verifies a save actually went through: no error popup and the button is gone.</summary>
    private async Task CompleteSaveAsync(ILocator target, CancellationToken cancellationToken)
    {
        var error = await ReadErrorNotificationAsync().ConfigureAwait(false);
        if (error is not null)
        {
            throw new InvalidOperationException("Save failed. Creatio reported: " + error);
        }

        if (_options.DoubleClick)
        {
            try
            {
                await target.ClickAsync(new LocatorClickOptions { Timeout = TimeoutMs }).ConfigureAwait(false);
            }
            catch (PlaywrightException ex)
            {
                // Expected when the first click already saved and the button went away.
                Logger.LogDebug(ex, "Second Save click on {Code} was not needed.", Code);
            }
        }

        try
        {
            // Hidden rather than detached: some pages remove the Save button from the DOM once the
            // record is stored, others keep the host and collapse it. Waiting for removal reports a
            // save that plainly worked as a failure on every page of the second kind.
            await Root.WaitForAsync(new LocatorWaitForOptions
            {
                State = WaitForSelectorState.Hidden,
                Timeout = _options.DisappearTimeoutMs
            }).ConfigureAwait(false);

            return;
        }
        catch (TimeoutException)
        {
        }

        var lateError = await ReadErrorNotificationAsync().ConfigureAwait(false);
        if (lateError is not null)
        {
            throw new InvalidOperationException("Save failed. Creatio reported: " + lateError);
        }

        throw new InvalidOperationException(
            "Save button '" + Code + "' was still showing after " + _options.DisappearTimeoutMs +
            " ms and no error was shown; the record was probably not saved.");
    }

    private async Task<string?> ReadErrorNotificationAsync()
    {
        try
        {
            var popup = Page.Locator(NotificationSelector);
            if (await popup.CountAsync().ConfigureAwait(false) == 0)
            {
                return null;
            }

            var text = await popup.First.InnerTextAsync().ConfigureAwait(false);
            return string.IsNullOrWhiteSpace(text) ? null : text.Trim();
        }
        catch (PlaywrightException)
        {
            return null;
        }
    }
}
