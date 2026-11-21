using Microsoft.Playwright;

namespace CreatioAutoTests.Frontend;

/// <summary>One visible modal dialog: everything it says and the captions of its buttons.</summary>
public sealed record DialogSnapshot(string Text, IReadOnlyList<string> Buttons);

/// <summary>
/// "The current modal dialog" of S34-T02, one reading for both generations: Classic's message box (<c>.ts-messagebox-box</c>),
/// Freedom UI's Material dialog (<c>mat-dialog-container</c>, <c>crt-dialog</c>) and the modal overlay pane. A dialog nested
/// in another matched element counts once (the outermost); a hidden one does not count. Nothing here needs a configured element.
/// </summary>
public static class DialogProbe
{
    /// <summary>The selector of every dialog shape the framework knows.</summary>
    public const string Selector = ".ts-messagebox-box, mat-dialog-container, crt-dialog, .cdk-overlay-pane.modal-container";

    private const string ButtonSelector = "button, .t-btn-wrapper[data-item-marker], [role=button]";
    private const string AnswerMark = "data-act-answer";
    private const int PollMs = 250;

    // The script runs in the page: visible dialogs, outermost only, each with its text and the captions of its visible buttons.
    private const string ReadScript = @"(args) => {
        const visible = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
        const all = [...document.querySelectorAll(args.selector)].filter(visible);
        const top = all.filter(e => !all.some(o => o !== e && o.contains(e)));
        return top.map(e => ({
            text: (e.innerText || '').trim(),
            buttons: [...e.querySelectorAll(args.buttons)].filter(visible).map(b => (b.innerText || '').trim()).filter(t => t)
        }));
    }";

    private const string MarkScript = @"(args) => {
        const visible = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
        document.querySelectorAll('[' + args.mark + ']').forEach(e => e.removeAttribute(args.mark));
        const all = [...document.querySelectorAll(args.selector)].filter(visible);
        const top = all.filter(e => !all.some(o => o !== e && o.contains(e)));
        const dialog = top[top.length - 1];
        if (!dialog) return 0;
        const wanted = args.caption.trim().toLowerCase();
        const hit = [...dialog.querySelectorAll(args.buttons)].filter(visible).find(b => (b.innerText || '').trim().toLowerCase() === wanted);
        if (!hit) return 0;
        hit.setAttribute(args.mark, '1');
        return 1;
    }";

    /// <summary>The visible dialogs now, in DOM order; empty while the page is navigating.</summary>
    public static async Task<IReadOnlyList<DialogSnapshot>> ReadAsync(IPage page)
    {
        try
        {
            var read = await page.EvaluateAsync<System.Text.Json.JsonElement>(ReadScript, new { selector = Selector, buttons = ButtonSelector }).ConfigureAwait(false);
            return read.ValueKind != System.Text.Json.JsonValueKind.Array
                ? Array.Empty<DialogSnapshot>()
                : read.EnumerateArray().Select(d => new DialogSnapshot(
                    d.GetProperty("text").GetString() ?? string.Empty,
                    d.GetProperty("buttons").EnumerateArray().Select(b => b.GetString() ?? string.Empty).ToArray())).ToArray();
        }
        catch (PlaywrightException)
        {
            return Array.Empty<DialogSnapshot>();
        }
    }

    /// <summary>
    /// Polls until <paramref name="done"/> holds or the budget ends, and returns the last reading either way. With
    /// <paramref name="settleMs"/> the condition must still hold after that pause: "exactly one dialog" is not true at the
    /// moment the first of two appears.
    /// </summary>
    public static async Task<IReadOnlyList<DialogSnapshot>> WaitAsync(
        IPage page, Func<IReadOnlyList<DialogSnapshot>, bool> done, int timeoutMs, int settleMs, CancellationToken cancellationToken)
    {
        var until = DateTime.UtcNow.AddMilliseconds(timeoutMs);
        var last = await ReadAsync(page).ConfigureAwait(false);
        while (true)
        {
            if (done(last))
            {
                if (settleMs <= 0)
                {
                    return last;
                }

                await Task.Delay(settleMs, cancellationToken).ConfigureAwait(false);
                last = await ReadAsync(page).ConfigureAwait(false);
                if (done(last))
                {
                    return last;
                }
            }

            if (DateTime.UtcNow >= until)
            {
                return last;
            }

            await Task.Delay(PollMs, cancellationToken).ConfigureAwait(false);
            last = await ReadAsync(page).ConfigureAwait(false);
        }
    }

    /// <summary>
    /// Clicks the button of the topmost visible dialog whose caption equals <paramref name="caption"/>, case-blind on its
    /// text (Classic shows captions upper-cased by CSS). Waits for the dialog and the button within the budget.
    /// </summary>
    /// <returns>The captions of the buttons that were there when it failed, or null when the button was clicked.</returns>
    public static async Task<IReadOnlyList<string>?> AnswerAsync(IPage page, string caption, int timeoutMs, CancellationToken cancellationToken)
    {
        var until = DateTime.UtcNow.AddMilliseconds(timeoutMs);
        while (true)
        {
            var marked = 0;
            try
            {
                marked = await page.EvaluateAsync<int>(MarkScript, new { selector = Selector, buttons = ButtonSelector, mark = AnswerMark, caption }).ConfigureAwait(false);
            }
            catch (PlaywrightException)
            {
                // the page is navigating: look again
            }

            if (marked == 1)
            {
                await page.Locator("[" + AnswerMark + "]").First.ClickAsync(new LocatorClickOptions { Timeout = timeoutMs }).ConfigureAwait(false);
                return null;
            }

            if (DateTime.UtcNow >= until)
            {
                var now = await ReadAsync(page).ConfigureAwait(false);
                return now.Count == 0 ? Array.Empty<string>() : now[^1].Buttons;
            }

            await Task.Delay(PollMs, cancellationToken).ConfigureAwait(false);
        }
    }
}
