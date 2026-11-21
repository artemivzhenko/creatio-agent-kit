using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Playwright;

namespace CreatioAutoTests.Frontend;

/// <summary>
/// What the screen looks like right now, for the author who is about to write a case (S34-T05): the open menus with their items,
/// the visible dialogs with their text and buttons, the masks that block clicks, the current stage, the open tabs of the page, the
/// URL. Read in one page script; it checks nothing and changes nothing.
/// </summary>
public static class ScreenSnapshot
{
    private const string Script = @"(args) => {
        const visible = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
        const text = e => (e.innerText || '').trim().replace(/\s+/g, ' ');
        const menus = [...document.querySelectorAll('.mat-mdc-menu-panel, .mat-menu-panel, [role=menu], .x-menu')].filter(visible)
            .map(m => ({ items: [...m.querySelectorAll('[role=menuitem], .mat-mdc-menu-item, .mat-menu-item, .x-menu-item')].filter(visible).map(text).filter(t => t) }))
            .filter(m => m.items.length);
        const masks = [...document.querySelectorAll('.cdk-overlay-backdrop, .x-mask, .loading-mask, .crt-loader, mat-progress-spinner, .mat-mdc-progress-spinner, [class*=mask]')]
            .filter(visible).map(e => e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : ''));
        const stageEl = document.querySelector('crt-stage-chart [aria-selected=true], crt-stage-chart .selected, crt-stage-chart .active, .stage-item-active, .ts-stage-active');
        let tabEls = [...document.querySelectorAll('[role=tab]')];
        if (!tabEls.length) tabEls = [...document.querySelectorAll('crt-tab-panel-header-item, li[data-item-index]')];
        const tabs = tabEls.filter(visible)
            .map(t => ({ caption: text(t), active: t.getAttribute('aria-selected') === 'true' || /active|selected/.test(typeof t.className === 'string' ? t.className : '') }));
        return { menus, masks, stage: stageEl ? text(stageEl) : null, tabs, url: location.href };
    }";

    /// <summary>Reads the screen of <paramref name="page"/> as the snapshot document the author reads.</summary>
    public static async Task<JsonObject> ReadAsync(IPage page, string name, string caseName, int tab, DateTime at)
    {
        var raw = await page.EvaluateAsync<JsonElement>(Script).ConfigureAwait(false);
        var dialogs = await DialogProbe.ReadAsync(page).ConfigureAwait(false);
        return Build(raw, dialogs, name, caseName, tab, at);
    }

    /// <summary>Shapes the page's answer and the dialogs into the snapshot document; pure, so a fixture can test it.</summary>
    public static JsonObject Build(JsonElement raw, IReadOnlyList<DialogSnapshot> dialogs, string name, string caseName, int tab, DateTime at) =>
        new()
        {
            ["name"] = name,
            ["case"] = caseName,
            ["at"] = at.ToString("yyyy-MM-ddTHH:mm:ss", System.Globalization.CultureInfo.InvariantCulture),
            ["tab"] = tab,
            ["url"] = raw.TryGetProperty("url", out var url) ? url.GetString() : null,
            ["dialogs"] = new JsonArray(dialogs.Select(d => (JsonNode)new JsonObject
            {
                ["text"] = d.Text,
                ["buttons"] = new JsonArray(d.Buttons.Select(b => (JsonNode)JsonValue.Create(b)!).ToArray()),
            }).ToArray()),
            ["menus"] = Node(raw, "menus"),
            ["masks"] = Node(raw, "masks"),
            ["stage"] = raw.TryGetProperty("stage", out var stage) && stage.ValueKind == JsonValueKind.String ? stage.GetString() : null,
            ["tabs"] = Node(raw, "tabs"),
        };

    private static JsonNode Node(JsonElement raw, string property)
    {
        var node = raw.TryGetProperty(property, out var value) ? JsonNode.Parse(value.GetRawText())! : new JsonArray();
        Strip(node);
        return node;
    }

    // Playwright marks the objects it returns with "$id"; the author reads the document, not its bookkeeping.
    private static void Strip(JsonNode? node)
    {
        switch (node)
        {
            case JsonObject o:
                o.Remove("$id");
                foreach (var child in o.Select(p => p.Value).ToArray()) { Strip(child); }
                break;
            case JsonArray a:
                foreach (var child in a) { Strip(child); }
                break;
        }
    }

    /// <summary>The file <c>snapshot "name"</c> writes: <c>&lt;reports&gt;/snapshots/&lt;case&gt;-&lt;name&gt;.json</c>, characters a file name cannot hold replaced.</summary>
    public static string PathFor(string reportsDirectory, string caseName, string name)
    {
        var safe = string.Concat((caseName + "-" + name).Select(c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c));
        return Path.GetFullPath(Path.Combine(reportsDirectory, "snapshots", safe + ".json"));
    }
}
