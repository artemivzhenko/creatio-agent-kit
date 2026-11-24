using CreatioAutoTests.Execution;
using Microsoft.Extensions.Logging;
using Microsoft.Playwright;

namespace CreatioAutoTests.Frontend.Controls;

/// <summary>
/// A lookup quick filter chip of a Freedom UI list page (crt-quick-filter, filterType "lookup", S44-T07). The chip is a button;
/// its drop-down is an autocomplete panel in the page overlay whose rows are checkboxes, so the selection is the value:
/// <c>set Chip "A; B"</c> ticks exactly those rows (and unticks the others), <c>check-value Chip eq "A"</c> reads the ticked ones.
/// The grid reloads after the panel closes.
/// </summary>
[UiElement("QuickFilter", HostTag = "crt-quick-filter", ValueKind = ValueKind.Lookup)]
public sealed class QuickFilter : FreedomElementBase, IValueElement
{
    private const string Panel = ".cdk-overlay-container .mat-autocomplete-panel";
    private const int OfferedShown = 20;

    /// <summary>Initializes the chip against its configured page control.</summary>
    public QuickFilter(ElementRuntimeContext context) : base(context)
    {
    }

    /// <summary>What a set has to do with the panel's rows: which to click, and which wanted values the panel does not offer.</summary>
    internal static (List<string> Toggle, List<string> Missing) Plan(IReadOnlyList<(string Label, bool Checked)> rows, IReadOnlyList<string> wanted)
    {
        var toggle = new List<string>();
        foreach (var (label, isChecked) in rows)
        {
            var isWanted = wanted.Contains(label, StringComparer.OrdinalIgnoreCase);
            if (isWanted != isChecked)
            {
                toggle.Add(label);
            }
        }

        var missing = wanted.Where(w => !rows.Any(r => string.Equals(r.Label, w, StringComparison.OrdinalIgnoreCase))).ToList();
        return (toggle, missing);
    }

    /// <summary>The values of "A; B" in the order written, trimmed, empties dropped.</summary>
    internal static List<string> ParseValues(string? value) =>
        (value ?? string.Empty).Split(';', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries).ToList();

    /// <summary>The ticked values, joined with "; " (an empty string when none is ticked).</summary>
    public async Task<string?> GetValueAsStringAsync(CancellationToken cancellationToken = default)
    {
        await OpenAsync().ConfigureAwait(false);
        try
        {
            var rows = await ReadRowsAsync().ConfigureAwait(false);
            return string.Join("; ", rows.Where(r => r.Checked).Select(r => r.Label));
        }
        finally
        {
            await CloseAsync().ConfigureAwait(false);
        }
    }

    /// <summary>Ticks exactly the listed values; a value the panel does not offer fails the step with the rows it showed.</summary>
    public async Task SetValueFromStringAsync(string value, CancellationToken cancellationToken = default)
    {
        var wanted = ParseValues(value);
        await OpenAsync().ConfigureAwait(false);
        try
        {
            var rows = await ReadRowsAsync().ConfigureAwait(false);
            var (toggle, missing) = Plan(rows, wanted);
            if (missing.Count > 0)
            {
                var shown = rows.Take(OfferedShown).Select(r => "'" + r.Label + "'");
                throw new CommandFailedException("Quick filter '" + Code + "' does not offer " + string.Join(", ", missing.Select(m => "'" + m + "'")) +
                                                 ". It shows: " + (rows.Count == 0 ? "(nothing)" : string.Join(", ", shown)) + ".");
            }

            foreach (var label in toggle)
            {
                await Page.Locator(Panel + " mat-option:has(input[aria-label=\"" + label.Replace("\"", "\\\"") + "\"])").First
                    .ClickAsync(new LocatorClickOptions { Timeout = TimeoutMs }).ConfigureAwait(false);
            }
        }
        finally
        {
            await CloseAsync().ConfigureAwait(false);
        }

        // the grid reloads for the new filter: wait for the requests to end, not for a fixed time
        try
        {
            await Page.WaitForLoadStateAsync(LoadState.NetworkIdle, new PageWaitForLoadStateOptions { Timeout = TimeoutMs }).ConfigureAwait(false);
        }
        catch (TimeoutException)
        {
            Logger.LogDebug("The page did not go idle after the quick filter '{Code}' changed.", Code);
        }
    }

    private async Task OpenAsync()
    {
        if (!await ExistsAsync().ConfigureAwait(false))
        {
            throw NotFound();
        }

        // With a value ticked the chip's button no longer opens the list; the combobox input inside it always does (seen on 8.2.3)
        var input = Root.Locator("crt-combobox input").First;
        var opener = await input.IsVisibleAsync().ConfigureAwait(false) ? input : Root.Locator("crt-button button").First;
        try
        {
            await opener.ClickAsync(new LocatorClickOptions { Timeout = TimeoutMs }).ConfigureAwait(false);
            await Page.Locator(Panel).First.WaitForAsync(new LocatorWaitForOptions { State = WaitForSelectorState.Visible, Timeout = TimeoutMs }).ConfigureAwait(false);
            // the rows arrive after the panel
            await Page.Locator(Panel + " mat-option").First
                .WaitForAsync(new LocatorWaitForOptions { State = WaitForSelectorState.Attached, Timeout = TimeoutMs }).ConfigureAwait(false);
        }
        catch (TimeoutException)
        {
            throw new CommandFailedException("Quick filter '" + Code + "' did not open its list of values.");
        }
    }

    private async Task CloseAsync()
    {
        await Page.Keyboard.PressAsync("Escape").ConfigureAwait(false);
        try
        {
            await Page.Locator(Panel).First.WaitForAsync(new LocatorWaitForOptions { State = WaitForSelectorState.Hidden, Timeout = TimeoutMs }).ConfigureAwait(false);
        }
        catch (TimeoutException)
        {
            Logger.LogDebug("The panel of quick filter '{Code}' stayed open after Escape.", Code);
        }
    }

    private async Task<IReadOnlyList<(string Label, bool Checked)>> ReadRowsAsync()
    {
        var rows = await Page.EvaluateAsync<string[][]>(
            @"(panel) => [...document.querySelectorAll(panel + ' mat-option')]
                .map(o => { const i = o.querySelector('input[aria-label]'); const c = o.querySelector('mat-checkbox');
                            return i ? [i.getAttribute('aria-label'), c && c.classList.contains('mat-checkbox-checked') ? '1' : '0'] : null; })
                .filter(r => r)", Panel).ConfigureAwait(false);
        // a ticked value is listed twice: in the "chosen" group on top and in its place among the rows
        return (rows ?? Array.Empty<string[]>()).GroupBy(r => r[0]).Select(g => (g.Key, g.Any(r => r[1] == "1"))).ToList();
    }
}
