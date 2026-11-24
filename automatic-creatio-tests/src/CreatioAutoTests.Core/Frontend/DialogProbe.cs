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

    private const string TickMark = "data-act-tick";

    // Marks every body row of the topmost dialog's grid whose cell text equals a wanted value (the row's checkbox exists only while the row is hovered).
    // Returns { dialog, rows: first 20 rows as text, found: wanted values that are rows }.
    private const string TickScript = @"(args) => {
        const visible = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
        document.querySelectorAll('[' + args.mark + ']').forEach(e => e.removeAttribute(args.mark));
        const all = [...document.querySelectorAll(args.selector)].filter(visible);
        const top = all.filter(e => !all.some(o => o !== e && o.contains(e)));
        const dialog = top[top.length - 1];
        if (!dialog) return { dialog: false, rows: [], found: [] };
        const rows = [...dialog.querySelectorAll('tbody tr[role=row], tbody tr')];
        const texts = rows.map(r => [...r.querySelectorAll('td')].map(c => (c.innerText || '').trim()).filter(t => t));
        const found = [];
        rows.forEach((r, i) => {
            const hit = args.wanted.find(w => texts[i].some(t => t.toLowerCase() === w.toLowerCase()));
            if (!hit) return;
            found.push(hit);
            r.setAttribute(args.mark, '1');
        });
        return { dialog: true, rows: texts.slice(0, 20).map(t => t.join(' | ')), found };
    }";

    /// <summary>
    /// Ticks the rows of the topmost dialog's grid (a record selection window) whose display value equals each wanted text, case-blind.
    /// Returns the wanted values that are not rows, with the rows the window showed (the first 20); null when every row was found and ticked.
    /// <paramref name="windowShown"/> is false when there is no dialog at all.
    /// </summary>
    public static async Task<(bool WindowShown, IReadOnlyList<string> Missing, IReadOnlyList<string> Rows)?> TickRowsAsync(
        IPage page, IReadOnlyList<string> wanted, int timeoutMs, CancellationToken cancellationToken)
    {
        var until = DateTime.UtcNow.AddMilliseconds(timeoutMs);
        string? lastRows = null;
        while (true)
        {
            var read = await page.EvaluateAsync<System.Text.Json.JsonElement>(TickScript, new { selector = Selector, mark = TickMark, wanted }).ConfigureAwait(false);
            var shown = read.GetProperty("dialog").GetBoolean();
            var rows = read.GetProperty("rows").EnumerateArray().Select(r => r.GetString() ?? string.Empty).ToArray();
            var found = read.GetProperty("found").EnumerateArray().Select(r => r.GetString() ?? string.Empty).ToArray();
            var missing = wanted.Where(w => !found.Contains(w, StringComparer.OrdinalIgnoreCase)).ToArray();

            // the window's grid re-renders while its rows load and a tick made before that is lost: tick only when two readings agree
            var snapshot = string.Join("|", rows);
            var steady = snapshot == lastRows;
            lastRows = snapshot;
            if (shown && missing.Length == 0 && steady)
            {
                // the checkbox of a row is rendered while the row is hovered only: hover, then tick it unless it is ticked
                foreach (var row in await page.Locator("[" + TickMark + "]").AllAsync().ConfigureAwait(false))
                {
                    await row.HoverAsync(new LocatorHoverOptions { Timeout = timeoutMs }).ConfigureAwait(false);
                    var box = row.Locator("mat-checkbox").First;
                    if (!await IsTickedAsync(box).ConfigureAwait(false))
                    {
                        await box.Locator(".mat-checkbox-layout").ClickAsync(new LocatorClickOptions { Timeout = timeoutMs }).ConfigureAwait(false);
                    }

                    if (!await IsTickedAsync(box).ConfigureAwait(false))
                    {
                        throw new Execution.CommandFailedException("'select-in-dialog': the checkbox of a row did not tick.");
                    }
                }

                return null;
            }

            if (DateTime.UtcNow >= until)
            {
                return (shown, missing, rows);
            }

            await Task.Delay(PollMs, cancellationToken).ConfigureAwait(false);
        }
    }

    private static async Task<bool> IsTickedAsync(ILocator checkbox) =>
        (await checkbox.GetAttributeAsync("class").ConfigureAwait(false) ?? string.Empty).Contains("mat-checkbox-checked", StringComparison.Ordinal);

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
