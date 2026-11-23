using CreatioAutoTests.Commands;
using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Tests.Support;
using CreatioAutoTests.Validation;
using Microsoft.Extensions.DependencyInjection;

namespace CreatioAutoTests.Tests;

/// <summary>S11-T06: a command on an element of another tab opens that tab first; validation inserts nothing.</summary>
[TestFixture]
public sealed class TabSwitchTests
{
    private sealed class Clickable : IUiElement, IClickable
    {
        private readonly List<string> _log;
        public Clickable(string code, List<string> log) { Code = code; _log = log; }
        public string Code { get; }
        public string Label => Code;
        public Task ClickAsync(CancellationToken cancellationToken = default) { _log.Add("click " + Code); return Task.CompletedTask; }
    }

    private static (ExecutionPlan Plan, FakeExecutionSession Session, List<string> Log) Arrange(params string[] lines)
    {
        var name = CatalogBuilder.Element("Name", "Text");
        name.Tab = "GeneralInfoTab";
        var other = CatalogBuilder.Element("Other", "Text");
        other.Tab = "NotesTab";
        var catalog = CatalogBuilder.Build(name, other, CatalogBuilder.Element("GeneralInfoTab", "Tab"), CatalogBuilder.Element("NotesTab", "Tab"));
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        var plan = new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider()).Validate("d", "d.act", new ScriptParser().Parse(lines),
            new ValidationContext(catalog, new Dictionary<string, string>(), new[] { "tester" }, new Dictionary<string, ObjectDefinition>()));
        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
        var log = new List<string>();
        return (plan, new FakeExecutionSession { Catalog = catalog, MaterializeWith = t => new Clickable(t.Code, log) }, log);
    }

    [Test]
    public async Task The_first_command_on_a_tab_opens_it_once_and_a_command_on_another_tab_switches()
    {
        var (plan, session, log) = Arrange("use tester", "open TestPage", "check Name exists", "check Name exists", "check Other exists", "check Name exists");

        foreach (var step in plan.Steps)
        {
            await CommandExecutor.EnsureTabsAsync(step, session, default);
        }

        Assert.That(log, Is.EqualTo(new[] { "click GeneralInfoTab", "click NotesTab", "click GeneralInfoTab" }));
    }

    [Test]
    public async Task A_tab_known_to_be_open_is_not_clicked_again()
    {
        var (plan, session, log) = Arrange("use tester", "open TestPage", "check Name exists");
        session.ActiveTabCode = "GeneralInfoTab";

        await CommandExecutor.EnsureTabsAsync(plan.Steps[^1], session, default);

        Assert.That(log, Is.Empty);
    }
}

/// <summary>S11-T06: the walk records the tab a control lies on.</summary>
[TestFixture]
public sealed class AssignTabsTests
{
    private static CreatioAutoTests.Analysis.DiscoveredElement El(string code, string host = "crt-input") =>
        new(code, code, "Text", host, false, false, true, null, null, null, null, false);

    [Test]
    public void A_control_shown_on_one_tab_only_gets_that_tab_and_one_shown_everywhere_gets_none()
    {
        var elements = new List<CreatioAutoTests.Analysis.DiscoveredElement> { El("Name"), El("Notes"), El("SaveButton"), El("GeneralInfoTab", "crt-tab-panel-header-item") };
        var shown = new Dictionary<string, HashSet<string>>
        {
            ["GeneralInfoTab"] = new() { "Name", "SaveButton", "GeneralInfoTab" },
            ["NotesTab"] = new() { "Notes", "SaveButton", "GeneralInfoTab" },
        };

        CreatioAutoTests.Analysis.PageAnalyzer.AssignTabs(elements, shown);

        Assert.That(elements.Select(e => e.Tab), Is.EqualTo(new[] { "GeneralInfoTab", "NotesTab", null, null }));
    }

    [Test]
    public void With_one_pass_nothing_can_be_told_apart()
    {
        var elements = new List<CreatioAutoTests.Analysis.DiscoveredElement> { El("Name") };
        CreatioAutoTests.Analysis.PageAnalyzer.AssignTabs(elements, new Dictionary<string, HashSet<string>> { ["A"] = new() { "Name" } });
        Assert.That(elements[0].Tab, Is.Null);
    }
}
