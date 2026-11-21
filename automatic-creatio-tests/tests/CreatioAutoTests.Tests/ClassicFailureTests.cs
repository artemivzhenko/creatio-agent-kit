using System.Reflection;
using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Frontend.Classic;
using CreatioAutoTests.Frontend.Classic.Controls;
using CreatioAutoTests.Frontend.Classic.Fields;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Playwright;

namespace CreatioAutoTests.Tests;

/// <summary>S11-T12: a control that is hidden or zero-width fails the line cleanly; a Classic button is found by its marker first.</summary>
[TestFixture]
public sealed class ClassicFailureTests
{
    /// <summary>A page that answers nothing: enough for an element that fails before it touches the browser.</summary>
    public class NoPage : DispatchProxy
    {
        protected override object? Invoke(MethodInfo? targetMethod, object?[]? args) => null;
    }

    private static TextField Field()
    {
        var page = new PageDefinition { Name = "UsrOrderPage", Url = "/p", Type = "ClassicUI", Schema = "UsrOrderPage" };
        var definition = new ElementDefinition { Code = "UsrWebsite", Page = "UsrOrderPage", Type = "Text" };
        return new TextField(new ElementRuntimeContext(DispatchProxy.Create<IPage, NoPage>(), definition, new RunSettings(), NullLogger.Instance, page));
    }

    [Test]
    public void A_missing_control_is_a_failed_line_not_a_framework_error()
    {
        var error = typeof(UiElementBase).GetMethod("NotFound", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(Field(), null);

        Assert.That(error, Is.TypeOf<CommandFailedException>());
        Assert.That(((Exception)error!).Message, Is.EqualTo("'UsrWebsite' was not found on the page."));
    }

    [Test]
    public void A_zero_width_field_has_its_own_sentence() =>
        Assert.That(ClassicFieldBase.InvisibleMessage("UsrWebsite"), Is.EqualTo("UsrWebsite is in the page but invisible (zero width)"));

    [Test]
    public void A_toolbar_button_is_looked_up_by_its_marker_then_the_two_id_forms() =>
        Assert.That(Button.ButtonSelector("UsrOrderPage", "Save"),
            Is.EqualTo("[data-item-marker=\"SaveButton\"], [id=\"UsrOrderPageSaveButton-wrapperEl\"], [id=\"UsrOrderPageSaveButton-textEl\"]"));
}
