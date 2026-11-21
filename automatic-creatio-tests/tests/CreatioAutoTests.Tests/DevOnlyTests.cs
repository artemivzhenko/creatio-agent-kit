using CreatioAutoTests.Commands;
using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Session;
using CreatioAutoTests.Tests.Support;
using CreatioAutoTests.Validation;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;

namespace CreatioAutoTests.Tests;

/// <summary>S34-T08: '# dev-only', 'seed' and 'fire-timer' are refused unless the case and the environment both say so.</summary>
[TestFixture]
public sealed class DevOnlyTests
{
    private const string Id = "11111111-1111-1111-1111-111111111111";
    private const string Element = "99999999-9999-4999-8999-999999999999";

    private static ExecutionPlan Validate(bool allow, params string[] lines)
    {
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        return new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider()).Validate("d", "d.act",
            new ScriptParser().Parse(lines), new ValidationContext(CatalogBuilder.Default(), new Dictionary<string, string>(), new[] { "tester" }, new Dictionary<string, ObjectDefinition>())
            {
                Directives = ScriptParser.Directives(lines),
                AllowDevOnly = allow,
            });
    }

    private static readonly string[] Seeded = { "# dev-only", "use tester", "insert UsrOrder as A set UsrName=x", "seed UsrOrder $A set UsrStatus=" + Id + ";UsrAmount=5", "fire-timer UsrOrder_Process for $A" };

    [Test]
    public void A_dev_only_case_validates_when_the_environment_allows_it()
    {
        var plan = Validate(true, Seeded);
        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
    }

    [Test]
    public void Without_the_environment_flag_the_case_is_refused_before_anything_runs()
    {
        var plan = Validate(false, Seeded);
        Assert.That(plan.IsValid, Is.False);
        Assert.That(plan.Issues[0].Message, Does.Contain("# dev-only").And.Contain("AllowDevOnly"));
    }

    [Test]
    public void The_commands_without_the_header_are_refused_even_where_the_environment_allows_it()
    {
        var plan = Validate(true, "use tester", "insert UsrOrder as A set UsrName=x", "seed UsrOrder $A set UsrAmount=5", "fire-timer UsrOrder_Process");
        Assert.That(plan.Issues.Select(i => i.LineNumber), Is.EqualTo(new[] { 3, 4 }));
        Assert.That(plan.Issues[0].Message, Does.Contain("'# dev-only'"));
    }

    [TestCase("seed UsrOrder $A")]
    [TestCase("seed UsrOrder $A UsrAmount=5")]
    [TestCase("seed UsrOrder A set UsrAmount=5")]
    [TestCase("fire-timer")]
    [TestCase("fire-timer UsrOrder_Process for A")]
    [TestCase("fire-timer UsrOrder_Process $A")]
    [TestCase("fire-timer \"UsrOrder_Process\"")]
    public void A_malformed_dev_only_line_is_an_error(string line) =>
        Assert.That(Validate(true, "# dev-only", "use tester", "insert UsrOrder as A set UsrName=x", line).IsValid, Is.False, line);

    [Test]
    public void The_seed_statement_is_a_direct_update_with_typed_literals()
    {
        var sql = DevSql.Seed("UsrOrder", Id, new[]
        {
            new RecordAssignment("UsrStatus", "0042909f-aaaa-4bbb-8ccc-ddddeeeeffff"), new RecordAssignment("UsrAmount", "5.5"), new RecordAssignment("UsrIsUrgent", "true"),
            new RecordAssignment("UsrNotes", "it's"), new RecordAssignment("UsrDue", "null"),
        });

        Assert.That(sql, Is.EqualTo("update \"UsrOrder\" set \"UsrStatusId\" = '0042909f-aaaa-4bbb-8ccc-ddddeeeeffff', \"UsrAmount\" = 5.5, \"UsrIsUrgent\" = true, "
                                    + "\"UsrNotes\" = 'it''s', \"UsrDue\" = NULL where \"Id\" = '" + Id + "'"));
        Assert.Throws<CommandFailedException>(() => DevSql.Seed("Usr'; drop", Id, new[] { new RecordAssignment("A", "1") }));
        Assert.Throws<CommandFailedException>(() => DevSql.Seed("UsrOrder", "not-a-guid", new[] { new RecordAssignment("A", "1") }));
        Assert.Throws<CommandFailedException>(() => DevSql.Seed("UsrOrder", Id, new[] { new RecordAssignment("A\" = 1; --", "1") }));
    }

    [Test]
    public void Ticks_are_dotnet_ticks_in_utc()
    {
        Assert.That(DevSql.Ticks(new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)), Is.EqualTo(621355968000000000));
        Assert.That(DevSql.Ticks(new DateTime(2026, 11, 21, 7, 18, 0, DateTimeKind.Utc)), Is.EqualTo(639308422800000000));
        Assert.That(DevSql.FromTicks(639308422800000000), Is.EqualTo(new DateTime(2026, 11, 21, 7, 18, 0)));
    }

    private sealed class Recording : IDevSql
    {
        public List<string> Statements { get; } = new();
        public List<IReadOnlyDictionary<string, string>> Timers { get; } = new();

        public Task<IReadOnlyList<IReadOnlyDictionary<string, string>>> RunAsync(string sql, CancellationToken cancellationToken = default)
        {
            Statements.Add(sql);
            return Task.FromResult<IReadOnlyList<IReadOnlyDictionary<string, string>>>(sql.StartsWith("select") ? Timers.ToArray() : Array.Empty<IReadOnlyDictionary<string, string>>());
        }
    }

    private static IReadOnlyDictionary<string, string> Timer(string trigger, string state = "WAITING", string caption = "1 d.", string element = Element) =>
        new Dictionary<string, string> { ["trigger"] = trigger, ["state"] = state, ["caption"] = caption, ["element_id"] = element, ["next"] = "1" };

    private static async Task Run(string line, FakeExecutionSession session)
    {
        var plan = Validate(true, "# dev-only", "use tester", "insert UsrOrder as A set UsrName=x", line);
        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
        var step = plan.Steps[^1];
        ICommand command = step.Registration.Keyword == "seed" ? new SeedCommand() : new FireTimerCommand();
        session.Variables["A"] = Id;
        await command.ExecuteAsync(new CommandContext(step, Array.Empty<IUiElement>(), session, NullLogger.Instance));
    }

    [Test]
    public async Task Seed_runs_the_update_through_the_dev_channel_and_notes_it_for_the_report()
    {
        var sql = new Recording();
        var session = new FakeExecutionSession { DevSql = sql };

        await Run("seed UsrOrder $A set UsrAmount=5", session);

        Assert.That(sql.Statements.Single(), Is.EqualTo("update \"UsrOrder\" set \"UsrAmount\" = 5 where \"Id\" = '" + Id + "'"));
        Assert.That(session.DevNotes.Single(), Does.Contain("data prepared behind the business logic").And.Contain("seed UsrOrder $A set UsrAmount=5"));
    }

    [Test]
    public async Task Fire_timer_moves_the_one_pending_timer_to_about_twenty_seconds_from_now()
    {
        var sql = new Recording();
        sql.Timers.Add(Timer("t-1"));
        var session = new FakeExecutionSession { DevSql = sql };
        var before = DateTime.UtcNow;

        await Run("fire-timer UsrOrder_Process for $A", session);

        Assert.That(sql.Statements[0], Does.Contain("s.\"Name\" = 'UsrOrder_Process'").And.Contain("l.\"StartDate\" >= '2026-11-21 08:00:00'"));
        var update = sql.Statements[1];
        Assert.That(update, Does.StartWith("update qrtz_triggers set next_fire_time = ").And.EndWith("where trigger_name = 't-1' and job_group = '" + Element + "'"));
        var ticks = long.Parse(update.Split('=')[1].Split(' ', StringSplitOptions.RemoveEmptyEntries)[0]);
        Assert.That(DevSql.FromTicks(ticks), Is.EqualTo(before.AddSeconds(20)).Within(TimeSpan.FromSeconds(5)));
        Assert.That(session.DevNotes.Single(), Does.Contain("timer '1 d.' of UsrOrder_Process moved to"));
    }

    [Test]
    public void Fire_timer_needs_exactly_one_pending_timer_and_writes_nothing_otherwise()
    {
        var none = new Recording();
        var noneFailure = Assert.ThrowsAsync<CommandFailedException>(() => Run("fire-timer UsrOrder_Process", new FakeExecutionSession { DevSql = none }))!;
        Assert.That(noneFailure.Message, Does.Contain("no pending timer"));

        var two = new Recording();
        two.Timers.Add(Timer("t-1"));
        two.Timers.Add(Timer("t-2", caption: "2 d."));
        two.Timers.Add(Timer("t-3", state: "COMPLETE"));
        var twoFailure = Assert.ThrowsAsync<CommandFailedException>(() => Run("fire-timer UsrOrder_Process", new FakeExecutionSession { DevSql = two }))!;
        Assert.That(twoFailure.Message, Does.Contain("2 pending timers").And.Contain("2 d."));
        Assert.That(none.Statements.Concat(two.Statements).Any(s => s.StartsWith("update")), Is.False);
    }

    [Test]
    public void Without_a_clio_environment_the_commands_say_what_to_configure()
    {
        var failure = Assert.ThrowsAsync<CommandFailedException>(() => Run("seed UsrOrder $A set UsrAmount=5", new FakeExecutionSession()))!;
        Assert.That(failure.Message, Does.Contain("ClioEnvironment"));
    }
}
