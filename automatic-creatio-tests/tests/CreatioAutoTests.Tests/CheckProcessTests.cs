using CreatioAutoTests.Commands;
using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Tests.Support;
using CreatioAutoTests.Validation;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;

namespace CreatioAutoTests.Tests;

/// <summary>S34-T07: 'check-process' reads the process log over OData for a process the case did not start.</summary>
[TestFixture]
public sealed class CheckProcessTests
{
    private const string Run = "44444444-4444-4444-4444-444444444444";

    private static ExecutionPlan Validate(params string[] lines)
    {
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        return new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider()).Validate("p", "p.act",
            new ScriptParser().Parse(new[] { "use tester", "insert UsrOrder as B set UsrName=x" }.Concat(lines).ToArray()),
            new ValidationContext(CatalogBuilder.Default(), new Dictionary<string, string>(), new[] { "tester" }, new Dictionary<string, ObjectDefinition>()));
    }

    [TestCase("check-process UsrOrder_Process started")]
    [TestCase("check-process UsrOrder_Process for $B started within 30 second")]
    [TestCase("check-process UsrOrder_Process for $B step \"Status\" completed within 2 minute")]
    [TestCase("check-process UsrOrder_Process step \"Wait a day\" running")]
    [TestCase("check-process UsrOrder_Process for $B running")]
    public void The_forms_validate(string line) => Assert.That(Validate(line).IsValid, Is.True, Validate(line).DescribeIssues());

    [TestCase("check-process")]
    [TestCase("check-process \"UsrOrder_Process\" started")]
    [TestCase("check-process UsrOrder_Process")]
    [TestCase("check-process UsrOrder_Process stopped")]
    [TestCase("check-process UsrOrder_Process for B started")]
    [TestCase("check-process UsrOrder_Process for $Nope started")]
    [TestCase("check-process UsrOrder_Process step Status completed")]
    [TestCase("check-process UsrOrder_Process step \"S\" finished")]
    [TestCase("check-process UsrOrder_Process started within 0 second")]
    [TestCase("check-process UsrOrder_Process started within 5 hour")]
    [TestCase("check-process Usr'Order started")]
    public void A_malformed_line_is_a_validation_error(string line) => Assert.That(Validate(line).IsValid, Is.False, line);

    private static IReadOnlyDictionary<string, string> Row(params (string, string)[] cells) => cells.ToDictionary(c => c.Item1, c => c.Item2);

    private static async Task Execute(string line, FakeExecutionSession session)
    {
        var plan = Validate(line);
        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
        await new CheckProcessCommand().ExecuteAsync(new CommandContext(plan.Steps[^1], Array.Empty<IUiElement>(), session, NullLogger.Instance));
    }

    private static FakeExecutionSession Site(Func<int, IReadOnlyList<IReadOnlyDictionary<string, string>>> runs,
        IReadOnlyList<IReadOnlyDictionary<string, string>>? elements = null, bool logOn = true)
    {
        var polls = 0;
        return new FakeExecutionSession
        {
            Settings = new RunSettings { PollIntervalMs = 5 },
            OnQuery = (entity, _, filter, _) =>
            {
                if (entity == "SysProcessElementLog")
                {
                    Assert.That(filter, Does.Contain("SysProcess/Id eq " + Run));
                    return elements ?? Array.Empty<IReadOnlyDictionary<string, string>>();
                }

                if (filter.StartsWith("StartDate ge 2000"))
                {
                    return logOn ? new[] { Row(("Id", Run)) } : Array.Empty<IReadOnlyDictionary<string, string>>();
                }

                Assert.That(filter, Does.Contain("SysSchema/Name eq 'UsrOrder_Process'").And.Contain("StartDate ge 2026-11-21T08:00:00.000Z"));
                return runs(++polls);
            },
        };
    }

    private static IReadOnlyList<IReadOnlyDictionary<string, string>> One(string complete = "") =>
        new[] { Row(("Id", Run), ("CompleteDate", complete), ("ErrorDescription", "")) };

    [Test]
    public async Task Started_polls_until_the_third_read_finds_a_run()
    {
        var reads = 0;
        var session = Site(n => { reads = n; return n < 3 ? Array.Empty<IReadOnlyDictionary<string, string>>() : One(); });
        session.PreviousLineStartedUtc = new DateTime(2026, 11, 21, 8, 0, 0, DateTimeKind.Utc);

        await Execute("check-process UsrOrder_Process for $B started within 30 second", session);

        Assert.That(reads, Is.EqualTo(3));
    }

    [Test]
    public void Without_within_it_reads_once_and_names_the_time_it_looked_from()
    {
        var session = Site(_ => Array.Empty<IReadOnlyDictionary<string, string>>());

        var failure = Assert.ThrowsAsync<CommandFailedException>(() => Execute("check-process UsrOrder_Process started", session))!;

        Assert.That(failure.Message, Does.Contain("no run of UsrOrder_Process started since 2026-11-21T08:00:00").And.Contain("line before"));
    }

    [Test]
    public async Task A_step_completes_by_its_caption_case_blind()
    {
        var steps = new[] { Row(("Caption", "Status"), ("CompleteDate", "2026-11-21T08:01:00Z"), ("ErrorDescription", "")) };
        await Execute("check-process UsrOrder_Process step \"status\" completed", Site(_ => One(), steps));
    }

    [Test]
    public void A_step_that_is_still_running_or_missing_says_what_the_run_did()
    {
        var running = new[] { Row(("Caption", "Wait a day"), ("CompleteDate", ""), ("ErrorDescription", "")), Row(("Caption", "Start"), ("CompleteDate", "x"), ("ErrorDescription", "")) };

        var notDone = Assert.ThrowsAsync<CommandFailedException>(() => Execute("check-process UsrOrder_Process step \"Wait a day\" completed", Site(_ => One(), running)))!;
        Assert.That(notDone.Message, Does.Contain("not completed").And.Contain("it is running"));

        var missing = Assert.ThrowsAsync<CommandFailedException>(() => Execute("check-process UsrOrder_Process step \"Status\" completed", Site(_ => One(), running)))!;
        Assert.That(missing.Message, Does.Contain("no such step").And.Contain("\"Wait a day\" (running)").And.Contain("\"Start\" (completed)"));
    }

    [Test]
    public async Task A_step_can_be_expected_running_and_a_run_can_be_running()
    {
        var running = new[] { Row(("Caption", "Wait a day"), ("CompleteDate", ""), ("ErrorDescription", "")) };
        await Execute("check-process UsrOrder_Process step \"Wait a day\" running", Site(_ => One(), running));
        await Execute("check-process UsrOrder_Process running", Site(_ => One()));
        Assert.ThrowsAsync<CommandFailedException>(() => Execute("check-process UsrOrder_Process running", Site(_ => One("2026-11-21T08:01:00Z"))));
    }

    [Test]
    public async Task A_date_odata_answers_as_year_one_is_not_a_completion()
    {
        var running = new[] { Row(("Caption", "Wait a day"), ("CompleteDate", "0001-01-01T00:00:00Z"), ("ErrorDescription", "")) };
        await Execute("check-process UsrOrder_Process step \"Wait a day\" running", Site(_ => One("0001-01-01T00:00:00Z"), running));
        await Execute("check-process UsrOrder_Process running", Site(_ => One("0001-01-01T00:00:00Z")));
        Assert.ThrowsAsync<CommandFailedException>(() => Execute("check-process UsrOrder_Process step \"Wait a day\" completed", Site(_ => One(), running)));
    }

    [Test]
    public void A_site_that_logs_nothing_says_logging_is_off_and_does_not_wait()
    {
        var session = Site(_ => Array.Empty<IReadOnlyDictionary<string, string>>(), logOn: false);

        var failure = Assert.ThrowsAsync<CommandFailedException>(() => Execute("check-process UsrOrder_Process step \"Status\" completed within 1 minute", session))!;

        Assert.That(failure.Message, Does.StartWith("process logging is off for UsrOrder_Process"));
    }
}
