using CreatioAutoTests.Commands;
using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Tests.Support;
using CreatioAutoTests.Validation;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;

namespace CreatioAutoTests.Tests;

/// <summary>S34-T03: 'wait-record' and 'wait-count' poll the check until it holds, over a fake OData that answers on the third read.</summary>
[TestFixture]
public sealed class WaitRecordTests
{
    private ScriptValidator _validator = null!;
    private ScriptParser _parser = null!;

    [SetUp]
    public void SetUp()
    {
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        _validator = new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider());
        _parser = new ScriptParser();
    }

    private ExecutionPlan Validate(params string[] lines) =>
        _validator.Validate("waits", "waits.act", _parser.Parse(new[] { "use tester" }.Concat(lines).ToArray()),
            new ValidationContext(CatalogBuilder.Default(), new Dictionary<string, string>(), new[] { "tester" }, new Dictionary<string, ObjectDefinition>()));

    [TestCase("wait-record UsrOrder Id=$B has UsrStatus eq Done within 30 second")]
    [TestCase("wait-record UsrOrder UsrName=Bed exists within 1 minute")]
    [TestCase("wait-record UsrOrder UsrName=Bed not exists within 5 second")]
    [TestCase("wait-count UsrQueue Order/Id=$B ge 2 within 60 second")]
    [TestCase("wait-count UsrQueue UsrName=Bed eq 0 within 1 minute")]
    public void The_wait_lines_validate(string line)
    {
        var plan = Validate("insert UsrOrder as B set UsrName=Bed", line);
        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
    }

    [TestCase("wait-record UsrOrder UsrName=Bed exists")]
    [TestCase("wait-record UsrOrder UsrName=Bed exists within second")]
    [TestCase("wait-record UsrOrder UsrName=Bed exists within 0 second")]
    [TestCase("wait-record UsrOrder UsrName=Bed exists within 3 hour")]
    [TestCase("wait-record UsrOrder UsrName=Bed exists within many second")]
    [TestCase("wait-record UsrOrder within 5 second")]
    [TestCase("wait-record UsrOrder UsrName=Bed has UsrStatus like Done within 5 second")]
    [TestCase("wait-record UsrOrder UsrName=Bed within 5 second")]
    [TestCase("wait-count UsrQueue UsrName=Bed ge within 5 second")]
    [TestCase("wait-count UsrQueue UsrName=Bed between 2 within 5 second")]
    [TestCase("wait-count UsrQueue UsrName=Bed ge two within 5 second")]
    [TestCase("wait-count UsrQueue ge 2 within 5 second")]
    public void A_malformed_wait_line_is_a_validation_error_naming_the_wait_command(string line)
    {
        var plan = Validate(line);

        Assert.That(plan.IsValid, Is.False, line);
        Assert.That(plan.Issues.Single().Message, Does.Contain("wait-").And.Not.Contain("check-"));
    }

    [Test]
    public void An_unknown_variable_in_the_filter_is_a_validation_error()
    {
        var plan = Validate("wait-record UsrOrder Id=$B has UsrStatus eq Done within 30 second");

        Assert.That(plan.Issues.Single().Message, Does.Contain("$B"));
    }

    private static async Task Run(ExecutionPlan plan, FakeExecutionSession session, string keyword)
    {
        var step = plan.Steps.Single(s => s.Registration.Keyword == keyword);
        ICommand command = keyword == "wait-record" ? new WaitRecordCommand() : new WaitCountCommand();
        await command.ExecuteAsync(new CommandContext(step, Array.Empty<IUiElement>(), session, NullLogger.Instance));
    }

    private static FakeExecutionSession Session(int reads, Func<int, string> statusAt, Action<int>? onRead = null) =>
        new()
        {
            Settings = new RunSettings { PollIntervalMs = 5 },
            OnQuery = (_, select, _, _) =>
            {
                reads++;
                onRead?.Invoke(reads);
                return new IReadOnlyDictionary<string, string>[] { new Dictionary<string, string> { [select[0]] = statusAt(reads) } };
            },
        };

    [Test]
    public async Task Wait_record_has_reads_again_until_the_third_read_shows_the_value()
    {
        var reads = 0;
        var session = Session(0, n => n >= 3 ? "Done" : "Draft", n => reads = n);
        var plan = Validate("wait-record UsrOrder UsrName=Bed has UsrStatus eq Done within 30 second");

        await Run(plan, session, "wait-record");

        Assert.That(reads, Is.EqualTo(3));
    }

    [Test]
    public async Task Wait_record_exists_polls_until_the_record_appears()
    {
        var reads = 0;
        var session = new FakeExecutionSession
        {
            Settings = new RunSettings { PollIntervalMs = 5 },
            OnRecordExists = (_, _) => ++reads >= 3,
        };

        await Run(Validate("wait-record UsrOrder UsrName=Bed exists within 30 second"), session, "wait-record");

        Assert.That(reads, Is.EqualTo(3));
    }

    [Test]
    public async Task Wait_record_not_exists_waits_for_the_record_to_go()
    {
        var reads = 0;
        var session = new FakeExecutionSession
        {
            Settings = new RunSettings { PollIntervalMs = 5 },
            OnRecordExists = (_, _) => ++reads < 3,
        };

        await Run(Validate("wait-record UsrOrder UsrName=Bed not exists within 30 second"), session, "wait-record");

        Assert.That(reads, Is.EqualTo(3));
    }

    [Test]
    public async Task Wait_count_reads_again_until_the_count_is_big_enough()
    {
        var reads = 0;
        var session = new FakeExecutionSession
        {
            Settings = new RunSettings { PollIntervalMs = 5 },
            OnCount = (_, _) => ++reads,
        };

        await Run(Validate("wait-count UsrQueue UsrName=Bed ge 3 within 30 second"), session, "wait-count");

        Assert.That(reads, Is.EqualTo(3));
    }

    [Test]
    public void When_the_condition_never_holds_the_failure_carries_the_last_value_read()
    {
        var session = Session(0, _ => "Draft");
        var plan = Validate("wait-record UsrOrder UsrName=Bed has UsrStatus eq Done within 1 second");

        var failure = Assert.ThrowsAsync<CommandFailedException>(() => Run(plan, session, "wait-record"))!;

        Assert.That(failure.Message, Does.StartWith("gave up after").And.Contain("1 s allowed").And.Contain("\"Draft\"").And.Contain("UsrStatus"));
    }

    [Test]
    public void When_the_record_never_appears_the_failure_says_so()
    {
        var session = new FakeExecutionSession { Settings = new RunSettings { PollIntervalMs = 5 } };
        var plan = Validate("wait-record UsrOrder UsrName=Bed exists within 1 second");

        var failure = Assert.ThrowsAsync<CommandFailedException>(() => Run(plan, session, "wait-record"))!;

        Assert.That(failure.Message, Does.StartWith("gave up after").And.Contain("has no record"));
    }

    [Test]
    public void An_error_of_the_read_itself_is_not_a_condition_and_is_not_retried()
    {
        var reads = 0;
        var session = new FakeExecutionSession
        {
            Settings = new RunSettings { PollIntervalMs = 5 },
            OnQuery = (_, _, _, _) =>
            {
                reads++;
                throw new InvalidOperationException("OData answered 400: no column UsrStatus");
            },
        };
        var plan = Validate("wait-record UsrOrder UsrName=Bed has UsrStatus eq Done within 30 second");

        var failure = Assert.ThrowsAsync<InvalidOperationException>(() => Run(plan, session, "wait-record"))!;

        Assert.That(failure.Message, Does.Contain("no column"));
        Assert.That(reads, Is.EqualTo(1));
    }

    [Test]
    public void Cancelling_the_run_stops_the_wait()
    {
        var session = Session(0, _ => "Draft");
        var plan = Validate("wait-record UsrOrder UsrName=Bed has UsrStatus eq Done within 30 second");
        using var cancel = new CancellationTokenSource(100);
        var step = plan.Steps.Single(s => s.Registration.Keyword == "wait-record");

        Assert.CatchAsync<OperationCanceledException>(() =>
            new WaitRecordCommand().ExecuteAsync(new CommandContext(step, Array.Empty<IUiElement>(), session, NullLogger.Instance), cancel.Token));
    }
}
