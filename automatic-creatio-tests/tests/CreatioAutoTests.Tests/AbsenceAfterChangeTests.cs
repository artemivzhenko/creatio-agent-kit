using CreatioAutoTests.Commands;
using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Tests.Support;
using CreatioAutoTests.Validation;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;

namespace CreatioAutoTests.Tests;

/// <summary>S11-T13: 'check X not exists' right after a change waits for the page rule that hides X.</summary>
[TestFixture]
public sealed class AbsenceAfterChangeTests
{
    /// <summary>An element that is shown until <see cref="HiddenAfterMs"/> have passed; records the budget it was asked to wait.</summary>
    private sealed class RuleHidden : IExistable, IVisibilityAware
    {
        public int HiddenAfterMs { get; init; }
        public int AskedBudget { get; private set; }
        public string Code => "Name";
        public string Label => "Name";
        public Task<bool> ExistsAsync(CancellationToken cancellationToken = default) => Task.FromResult(true);
        public Task<bool> ExistsAsync(int timeoutMs, CancellationToken cancellationToken = default) { AskedBudget = timeoutMs; return Task.FromResult(true); }
        public Task<bool> IsShownAsync(bool expected, int timeoutMs, CancellationToken cancellationToken = default)
        {
            AskedBudget = timeoutMs;
            return Task.FromResult(!expected && HiddenAfterMs <= timeoutMs);
        }
    }

    private static async Task Run(FakeExecutionSession session, RuleHidden element)
    {
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        var lines = new[] { "use tester", "open TestPage", "check Name not exists" };
        var plan = new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider()).Validate("d", "d.act", new ScriptParser().Parse(lines),
            new ValidationContext(CatalogBuilder.Default(), new Dictionary<string, string>(), new[] { "tester" }, new Dictionary<string, ObjectDefinition>()));
        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
        await new CheckCommand().ExecuteAsync(new CommandContext(plan.Steps[^1], new IUiElement[] { element }, session, NullLogger.Instance));
    }

    [Test]
    public async Task After_a_change_absence_is_awaited_for_the_element_budget()
    {
        var session = new FakeExecutionSession { Settings = new RunSettings { ElementTimeoutMs = 15000, AbsenceTimeoutMs = 1500 } };
        session.MarkChange();
        var element = new RuleHidden { HiddenAfterMs = 4000 };

        await Run(session, element);

        Assert.That(element.AskedBudget, Is.EqualTo(15000));
    }

    [Test]
    public void Without_a_recent_change_the_short_budget_stays_and_a_visible_control_fails()
    {
        var session = new FakeExecutionSession { Settings = new RunSettings { ElementTimeoutMs = 15000, AbsenceTimeoutMs = 1500 } };
        var element = new RuleHidden { HiddenAfterMs = 4000 };

        var failure = Assert.ThrowsAsync<CommandFailedException>(() => Run(session, element))!;

        Assert.That(element.AskedBudget, Is.EqualTo(1500));
        Assert.That(failure.Message, Does.Contain("expected to be absent"));
    }

    [Test]
    public void After_a_change_a_control_that_stays_shown_still_fails()
    {
        var session = new FakeExecutionSession { Settings = new RunSettings { ElementTimeoutMs = 15000 } };
        session.MarkChange();

        Assert.ThrowsAsync<CommandFailedException>(() => Run(session, new RuleHidden { HiddenAfterMs = 99999 }));
    }
}
