using CreatioAutoTests.Commands;
using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Tests.Support;
using CreatioAutoTests.Validation;
using Microsoft.Extensions.DependencyInjection;

namespace CreatioAutoTests.Tests;

/// <summary>S45-T09: 'open process-task' opens the page of a running pre-configured page task, which has no address of its own.</summary>
[TestFixture]
public sealed class ProcessTaskTests
{
    private ExecutionPlan Validate(params string[] lines)
    {
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        var catalog = CatalogBuilder.Build(
            CatalogBuilder.Element("SaveButton", "Button", "UsrProbePage"),
            CatalogBuilder.Element("UsrName", "Text", "UsrOrderPage"));
        return new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider()).Validate("p", "p.act", new ScriptParser().Parse(lines),
            new ValidationContext(catalog, new Dictionary<string, string>(), new[] { "tester" }, new Dictionary<string, ObjectDefinition>()));
    }

    [Test]
    public void The_line_moves_the_virtual_page_to_the_page_it_names()
    {
        var plan = Validate("use tester", "open process-task UsrDemo_Process on UsrProbePage", "click SaveButton");
        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
        Assert.That(Validate("use tester", "open process-task UsrDemo_Process on UsrProbePage", "set UsrName \"a\"").IsValid, Is.False);
    }

    [TestCase("open process-task UsrDemo_Process")]
    [TestCase("open process-task UsrDemo_Process UsrProbePage")]
    [TestCase("open process-task UsrDemo_Process on Nope")]
    public void A_malformed_line_names_its_own_form(string line)
    {
        var plan = Validate("use tester", line);
        Assert.That(plan.IsValid, Is.False, line);
        Assert.That(plan.DescribeIssues(), Does.Contain("process-task").Or.Contain("Nope"));
    }

    [Test]
    public async Task The_command_hands_the_process_and_the_page_to_the_session()
    {
        var plan = Validate("use tester", "open process-task UsrDemo_Process on UsrProbePage");
        var session = new FakeExecutionSession();
        await new OpenCommand().ExecuteAsync(new CommandContext(plan.Steps[^1], Array.Empty<CreatioAutoTests.Frontend.IUiElement>(), session,
            Microsoft.Extensions.Logging.Abstractions.NullLogger.Instance));
        Assert.That(session.Navigations, Is.EqualTo(new[] { "process-task UsrDemo_Process on UsrProbePage" }));
    }
}
