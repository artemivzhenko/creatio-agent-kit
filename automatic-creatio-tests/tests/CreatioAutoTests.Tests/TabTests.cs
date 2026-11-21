using CreatioAutoTests.Commands;
using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Tests.Support;
using CreatioAutoTests.Validation;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;

namespace CreatioAutoTests.Tests;

/// <summary>S34-T01: 'tab new [as name]' and 'tab number|name' through the parser, the validator and the command.</summary>
[TestFixture]
public sealed class TabTests
{
    private ScriptValidator _validator = null!;
    private ScriptParser _parser = null!;
    private ElementCatalog _catalog = null!;

    [SetUp]
    public void SetUp()
    {
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        _validator = new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider());
        _parser = new ScriptParser();
        _catalog = CatalogBuilder.Build(
            CatalogBuilder.Element("UsrName", "Text", "UsrOrderPage"),
            CatalogBuilder.Element("SaveButton", "Button", "UsrOrderPage"),
            CatalogBuilder.Element("UsrTitle", "Text", "UsrListPage"));
    }

    private ExecutionPlan Validate(params string[] lines) =>
        _validator.Validate("tabs", "tabs.act", _parser.Parse(lines),
            new ValidationContext(_catalog, new Dictionary<string, string>(), new[] { "tester" }, new Dictionary<string, ObjectDefinition>()));

    [Test]
    public void Two_tabs_validate_and_each_tab_resolves_codes_against_its_own_page()
    {
        var plan = Validate("use tester", "open UsrOrderPage", "tab new as second", "open UsrListPage", "set UsrTitle \"a\"",
            "tab 1", "set UsrName \"b\"", "tab second", "set UsrTitle \"c\"", "tab new", "open UsrOrderPage", "tab 3", "click SaveButton");

        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
    }

    [Test]
    public void A_code_of_the_other_tabs_page_is_unknown_on_this_tab()
    {
        var plan = Validate("use tester", "open UsrOrderPage", "tab new", "open UsrListPage", "tab 1", "set UsrTitle \"a\"");

        Assert.That(plan.IsValid, Is.False);
        Assert.That(plan.Issues.Single().Message, Does.Contain("UsrTitle").And.Contain("UsrOrderPage"));
    }

    [Test]
    public void A_new_tab_has_no_page_until_open_runs()
    {
        var plan = Validate("use tester", "open UsrOrderPage", "tab new", "set UsrName \"a\"");

        Assert.That(plan.IsValid, Is.False);
        Assert.That(plan.Issues.Single().Message, Does.Contain("no page is open"));
    }

    [Test]
    public void Tab_before_the_second_tab_new_is_an_error_naming_how_many_are_open()
    {
        var plan = Validate("use tester", "open UsrOrderPage", "tab 2");

        Assert.That(plan.IsValid, Is.False);
        Assert.That(plan.Issues.Single().Message, Does.Contain("no tab '2'").And.Contain("1 open").And.Contain("tab new"));
    }

    [TestCase("tab 0")]
    [TestCase("tab 3")]
    [TestCase("tab missing")]
    [TestCase("tab new as 2nd")]
    [TestCase("tab new as new")]
    [TestCase("tab new as second")]
    [TestCase("tab new second")]
    [TestCase("tab")]
    [TestCase("tab 1 2")]
    public void A_bad_tab_command_is_a_validation_error_and_the_browser_never_opens(string line)
    {
        var plan = Validate("use tester", "open UsrOrderPage", "tab new as second", line);

        Assert.That(plan.IsValid, Is.False, line);
        Assert.That(plan.Issues.Single().LineNumber, Is.EqualTo(4));
    }

    [Test]
    public void Tab_new_needs_an_open_page()
    {
        var plan = Validate("use tester", "tab new");

        Assert.That(plan.IsValid, Is.False);
        Assert.That(plan.Issues.Single().Message, Does.Contain("open <page>"));
    }

    [Test]
    public void Names_are_case_blind_and_unique()
    {
        var plan = Validate("use tester", "open UsrOrderPage", "tab new as Second", "tab SECOND", "tab new as second");

        Assert.That(plan.Issues.Select(i => i.LineNumber), Is.EqualTo(new[] { 5 }));
    }

    [Test]
    public async Task The_command_calls_the_session_with_the_number_or_the_name()
    {
        var plan = Validate("use tester", "open UsrOrderPage", "tab new as second", "open UsrListPage", "tab 1", "tab second", "tab new");
        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
        var session = new FakeExecutionSession();

        foreach (var step in plan.Steps.Where(s => s.Registration.Keyword == "tab"))
        {
            await new TabCommand().ExecuteAsync(new CommandContext(step, Array.Empty<CreatioAutoTests.Frontend.IUiElement>(), session, NullLogger.Instance));
        }

        Assert.That(session.TabCalls, Is.EqualTo(new[] { "new as second", "switch 1", "switch second", "new" }));
    }
}
