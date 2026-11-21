using CreatioAutoTests.Commands;
using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Tests.Support;
using CreatioAutoTests.Validation;
using Microsoft.Extensions.DependencyInjection;

namespace CreatioAutoTests.Tests;

/// <summary>S34-T06: 'navigate' is 'open' through the Shell hash, from a page already open in the tab.</summary>
[TestFixture]
public sealed class NavigateTests
{
    private ExecutionPlan Validate(params string[] lines)
    {
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        var catalog = CatalogBuilder.Build(
            CatalogBuilder.Element("UsrName", "Text", "UsrOrderPage"),
            CatalogBuilder.Element("UsrTitle", "Text", "UsrListPage"));
        return new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider()).Validate("n", "n.act", new ScriptParser().Parse(lines),
            new ValidationContext(catalog, new Dictionary<string, string> { ["Rec"] = "1" }, new[] { "tester" }, new Dictionary<string, ObjectDefinition>()));
    }

    [Test]
    public void Navigate_moves_the_virtual_page_so_later_codes_resolve_against_it()
    {
        var plan = Validate("use tester", "open UsrOrderPage", "navigate UsrListPage", "set UsrTitle \"a\"", "navigate UsrOrderPage for Rec", "set UsrName \"b\"");
        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
        Assert.That(Validate("use tester", "open UsrOrderPage", "navigate UsrListPage", "set UsrName \"a\"").IsValid, Is.False);
    }

    [Test]
    public void Navigate_needs_a_page_open_in_the_tab()
    {
        var plan = Validate("use tester", "navigate UsrOrderPage");
        Assert.That(plan.Issues.Single().Message, Does.Contain("must be open").And.Contain("open <page>"));
        var tabs = Validate("use tester", "open UsrOrderPage", "tab new", "navigate UsrListPage");
        Assert.That(tabs.IsValid, Is.False, "a new tab has no page to leave from");
    }

    [TestCase("navigate")]
    [TestCase("navigate Nope")]
    [TestCase("navigate UsrListPage 1")]
    [TestCase("navigate UsrListPage with Rec")]
    [TestCase("navigate UsrListPage for ShipmentId")]
    public void A_malformed_navigate_names_navigate_not_open(string line)
    {
        var plan = Validate("use tester", "open UsrOrderPage", line);
        Assert.That(plan.IsValid, Is.False, line);
        Assert.That(plan.Issues.Single().Message, Does.Not.Contain("'open"));
    }

    [Test]
    public async Task The_command_hands_the_page_and_the_record_to_the_session()
    {
        var plan = Validate("use tester", "open UsrOrderPage", "navigate UsrListPage for Rec");
        var session = new FakeExecutionSession();
        await new NavigateCommand().ExecuteAsync(new CommandContext(plan.Steps[^1], Array.Empty<CreatioAutoTests.Frontend.IUiElement>(), session,
            Microsoft.Extensions.Logging.Abstractions.NullLogger.Instance));
        Assert.That(session.Navigations, Is.EqualTo(new[] { "UsrListPage Rec" }));
    }
}
