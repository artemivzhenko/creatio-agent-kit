using CreatioAutoTests.Commands;
using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Tests.Support;
using CreatioAutoTests.Validation;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;

namespace CreatioAutoTests.Tests;

/// <summary>S46-T06: <c>click X expect error "text"</c> - a refused save is the pass.</summary>
[TestFixture]
public sealed class ClickExpectErrorTests
{
    private sealed class FakeButton : IUiElement, IRefusable
    {
        public FakeButton(string showing) { Showing = showing; }
        public string Showing { get; }
        public string Code => "SaveButton";
        public string Label => Code;
        public bool Plain { get; private set; }
        public Task ClickAsync(CancellationToken cancellationToken = default) { Plain = true; return Task.CompletedTask; }
        public Task<string> ClickReadingRefusalAsync(string expected, CancellationToken cancellationToken = default) => Task.FromResult(Showing);
    }

    private static ExecutionPlan Validate(params string[] lines)
    {
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        var catalog = CatalogBuilder.Build(CatalogBuilder.Element("SaveButton", "Button"), CatalogBuilder.Element("GeneralInfoTab", "Tab"));
        return new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider()).Validate("c", "c.act",
            new ScriptParser().Parse(new[] { "use tester", "open TestPage" }.Concat(lines).ToArray()),
            new ValidationContext(catalog, new Dictionary<string, string>(), new[] { "tester" }, new Dictionary<string, ObjectDefinition>()));
    }

    private static async Task<(TestCaseResult Result, FakeButton Button)> Run(string showing, string line)
    {
        var plan = Validate(line);
        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
        var button = new FakeButton(showing);
        var session = new FakeExecutionSession { Catalog = CatalogBuilder.Build(CatalogBuilder.Element("SaveButton", "Button")), MaterializeWith = _ => button };
        var result = await new CommandExecutor(new ServiceCollection().BuildServiceProvider(), NullLoggerFactory.Instance).ExecuteAsync(plan, session);
        return (result, button);
    }

    [Test]
    public void The_clause_is_parsed_by_the_shared_parser_and_needs_text_and_a_button()
    {
        Assert.Multiple(() =>
        {
            Assert.That(Validate("click SaveButton expect error \"Enter a value\"").IsValid, Is.True);
            Assert.That(Validate("click SaveButton").IsValid, Is.True, "without the clause nothing changes");
            Assert.That(Validate("click SaveButton expect error").DescribeIssues(), Does.Contain("text the refusal shows is required"));
            Assert.That(Validate("click GeneralInfoTab expect error \"x\"").DescribeIssues(), Does.Contain("needs a Freedom UI Button"));
        });
    }

    [Test]
    public async Task A_refusal_showing_the_text_passes_without_the_plain_click()
    {
        var (result, button) = await Run("Field: \"Carrier\". Error: Enter a value", "click SaveButton expect error \"enter a VALUE\"");
        Assert.That(result.Success, Is.True, result.FailureSummary);
        Assert.That(button.Plain, Is.False);
    }

    [Test]
    public async Task A_save_that_went_through_and_another_text_fail_naming_what_the_page_showed()
    {
        var saved = await Run(string.Empty, "click SaveButton expect error \"Enter a value\"");
        Assert.That(saved.Result.FailureSummary, Does.Contain("expected the refusal \"Enter a value\", the page showed: nothing"));

        var other = await Run("Too long", "click SaveButton expect error \"Enter a value\"");
        Assert.That(other.Result.FailureSummary, Does.Contain("expected the refusal \"Enter a value\", the page showed: Too long"));
    }
}
