namespace CreatioAutoTests.Frontend.Controls;

/// <summary>
/// Expansion panel (crt-expansion-panel), the designer's shape of a detail: <c>check S48Panel is shown</c>,
/// <c>check S48Panel exists</c> (its title is the label), <c>check A is before B</c> for the order of two panels.
/// A collapsed panel is still shown: only its content is not rendered.
/// </summary>
[UiElement("ExpansionPanel", HostTag = "crt-expansion-panel")]
public sealed class ExpansionPanel : FreedomElementBase
{
    /// <summary>Creates the panel against an open page.</summary>
    /// <param name="context">Page, definition and run settings for this element.</param>
    public ExpansionPanel(ElementRuntimeContext context) : base(context)
    {
    }

    /// <summary>A panel has no value.</summary>
    protected override Microsoft.Playwright.ILocator ValueLocator => Root;

    /// <summary>The panel's title is its header text.</summary>
    protected override Microsoft.Playwright.ILocator LabelLocator => Root.Locator(".expansion-panel-header").First;
}
