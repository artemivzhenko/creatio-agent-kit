using System.Reflection;
using CreatioAutoTests.Commands;
using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Frontend.Controls;
using CreatioAutoTests.Tests.Support;
using CreatioAutoTests.Validation;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Playwright;

namespace CreatioAutoTests.Tests;

/// <summary>S48-T11: 'wait-process-task' waits for the page task a UI line started and binds its page inside its dialog.</summary>
[TestFixture]
public sealed class WaitProcessTaskTests
{
    private static ExecutionPlan Validate(params string[] lines)
    {
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        var catalog = CatalogBuilder.Build(
            CatalogBuilder.Element("SaveButton", "Button", "UsrProbePage"),
            CatalogBuilder.Element("UsrName", "Text", "UsrOrderPage"));
        return new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider()).Validate("p", "p.act", new ScriptParser().Parse(lines),
            new ValidationContext(catalog, new Dictionary<string, string>(), new[] { "tester" }, new Dictionary<string, ObjectDefinition>()));
    }

    [TestCase("wait-process-task UsrDemo_Process on UsrProbePage")]
    [TestCase("wait-process-task UsrDemo_Process on UsrProbePage within 30 second")]
    public void The_line_moves_the_virtual_page_to_the_page_it_names(string line)
    {
        var plan = Validate("use tester", "open UsrOrderPage", "set UsrName \"a\"", line, "click SaveButton");
        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
        Assert.That(Validate("use tester", "open UsrOrderPage", line, "set UsrName \"a\"").IsValid, Is.False);
    }

    [TestCase("wait-process-task UsrDemo_Process UsrProbePage", "wait-process-task <process> on <page>")]
    [TestCase("wait-process-task UsrDemo_Process on Nope", "Nope")]
    [TestCase("wait-process-task UsrDemo_Process on UsrProbePage within 30 hour", "second' or 'minute")]
    [TestCase("wait-process-task UsrDemo_Process on UsrProbePage after 30 second", "within")]
    public void A_malformed_line_names_its_own_form(string line, string expected)
    {
        var plan = Validate("use tester", "open UsrOrderPage", line);
        Assert.That(plan.IsValid, Is.False, line);
        Assert.That(plan.DescribeIssues(), Does.Contain(expected));
    }

    [TestCase("wait-process-task UsrDemo_Process on UsrProbePage", "wait-process-task UsrDemo_Process on UsrProbePage")]
    [TestCase("wait-process-task UsrDemo_Process on UsrProbePage within 2 minute", "wait-process-task UsrDemo_Process on UsrProbePage 120000")]
    public async Task The_command_hands_the_process_the_page_and_the_budget_to_the_session(string line, string expected)
    {
        var plan = Validate("use tester", "open UsrOrderPage", line);
        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
        var session = new FakeExecutionSession();
        await new WaitProcessTaskCommand().ExecuteAsync(new CommandContext(plan.Steps[^1], Array.Empty<IUiElement>(), session, NullLogger.Instance));
        Assert.That(session.Navigations, Is.EqualTo(new[] { expected }));
    }

    /// <summary>Records every locator call, so the selector chain an element builds can be read back.</summary>
    public class RecordingProxy : DispatchProxy
    {
        public List<string> Calls = new();

        protected override object? Invoke(MethodInfo? targetMethod, object?[]? args)
        {
            var name = targetMethod!.Name;
            Calls.Add(name == "Locator" ? "Locator(" + args![0] + ")" : name.Replace("get_", string.Empty));
            if (targetMethod.ReturnType == typeof(ILocator))
            {
                return this is ILocator ? this : Next();
            }

            return targetMethod.ReturnType == typeof(Task) ? Task.CompletedTask : null;
        }

        private ILocator Next()
        {
            var locator = DispatchProxy.Create<ILocator, RecordingProxy>();
            ((RecordingProxy)(object)locator).Calls = Calls;
            return locator;
        }
    }

    [TestCase(null, "Locator(crt-button[element-name=\"SaveButton\"]) First WaitForAsync")]
    [TestCase("mat-dialog-container", "Locator(mat-dialog-container) Last Locator(crt-button[element-name=\"SaveButton\"]) First WaitForAsync")]
    public async Task An_element_of_a_page_in_a_dialog_is_searched_inside_the_newest_dialog(string? scope, string expected)
    {
        var page = DispatchProxy.Create<IPage, RecordingProxy>();
        var definition = new ElementDefinition { Code = "SaveButton", Page = "UsrProbePage", Type = "Button" };
        var button = new Button(new ElementRuntimeContext(page, definition, new RunSettings(), NullLogger.Instance, null, scope));

        Assert.That(await button.ExistsAsync(10), Is.True);
        Assert.That(string.Join(" ", ((RecordingProxy)(object)page).Calls), Is.EqualTo(expected));
    }
}

/// <summary>S48-T11: 'open &lt;page&gt;' without a record opens a Freedom UI card in add mode.</summary>
[TestFixture]
public sealed class AddModeAddressTests
{
    [TestCase("/0/Shell/#Card/UsrOrder_FormPage", null, "/0/Shell/#Card/UsrOrder_FormPage/add")]
    [TestCase("/0/Shell/#Card/UsrOrder_FormPage/", null, "/0/Shell/#Card/UsrOrder_FormPage/add")]
    [TestCase("/0/Shell/#Card/UsrOrder_FormPage", "5d2a1c3e-0000-4000-8000-000000000001", "/0/Shell/#Card/UsrOrder_FormPage/edit/5d2a1c3e-0000-4000-8000-000000000001")]
    [TestCase("/0/Shell/#Card/UsrOrder_FormPage/add", null, "/0/Shell/#Card/UsrOrder_FormPage/add")]
    [TestCase("/0/Shell/#Section/UsrOrder_ListPage", null, "/0/Shell/#Section/UsrOrder_ListPage")]
    [TestCase("/0/Shell/#CardModuleV2/UsrOrder1Page", null, "/0/Shell/#CardModuleV2/UsrOrder1Page")]
    public void A_card_address_without_a_record_is_the_add_mode(string url, string? record, string expected) =>
        Assert.That(new CreatioAutoTests.Frontend.Runtime.FreedomUiRuntime().BuildUrl(url, record), Is.EqualTo(expected));
}

/// <summary>S48-T11 (D77): a Classic address the Shell turned into a Freedom UI card is named, not reported as missing controls.</summary>
[TestFixture]
public sealed class ClassicRedirectTests
{
    [TestCase("https://dev.example.com/0/Shell/#Card/Orders_FormPage/edit/5d2a1c3e-0000-4000-8000-000000000001", "Card/Orders_FormPage/edit/5d2a1c3e-0000-4000-8000-000000000001")]
    [TestCase("https://dev.example.com/0/Shell/#CardModuleV2/UsrOrder1Page/edit/5d2a1c3e-0000-4000-8000-000000000001", null)]
    public void The_freedom_card_the_shell_went_to_is_read_off_the_address(string url, string? expected) =>
        Assert.That(CreatioAutoTests.Frontend.Runtime.ClassicUiRuntime.RedirectedToFreedom(url), Is.EqualTo(expected));
}
