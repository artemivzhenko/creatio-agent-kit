using CreatioAutoTests.Frontend;
using CreatioAutoTests.Session;
using Microsoft.Playwright;
using NUnit.Framework;

namespace CreatioAutoTests.Tests;

/// <summary>S11-T10: the elements a tab keeps are valid only for the page they were made for.</summary>
public sealed class ElementCacheTests
{
    private static IUiElement Element() => (IUiElement)System.Reflection.DispatchProxy.Create<IUiElement, Stub>();

    private class Stub : System.Reflection.DispatchProxy
    {
        protected override object? Invoke(System.Reflection.MethodInfo? targetMethod, object?[]? args) => null;
    }

    [Test]
    public void A_new_page_or_a_new_current_page_drops_the_elements_even_when_the_value_is_the_same()
    {
        var tab = new ExecutionSession.Tab();
        tab.Elements["P/Code"] = Element();

        tab.CurrentPage = "P";
        Assert.That(tab.Elements, Is.Empty, "'open' of the page the tab already shows reloads it");

        tab.Elements["P/Code"] = Element();
        tab.Page = null;
        Assert.That(tab.Elements, Is.Empty, "a closed or replaced browser page");

        tab.Elements["P/Code"] = Element();
        tab.CurrentPage = "Q";
        tab.Page = null;
        Assert.That(tab.Elements, Is.Empty);
    }
}
