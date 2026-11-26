using System.Net;
using System.Text;
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

/// <summary>S48-T10: a quoted value is text; null and empty values; a refused delete; an upsert on the cleanup list; a replacing process.</summary>
[TestFixture]
public sealed class FrameworkValuesTests
{
    private const string Guid1 = "0c48c818-08f0-4f70-9b58-be512227f3bf";
    private const string Parent = "00000009-0000-0000-0000-000000000000";

    private static ExecutionPlan Validate(params string[] lines)
    {
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        return new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider()).Validate("p", "p.act",
            new ScriptParser().Parse(lines),
            new ValidationContext(CatalogBuilder.Default(), new Dictionary<string, string>(), new[] { "Supervisor" }, new Dictionary<string, ObjectDefinition>())
            {
                Directives = ScriptParser.Directives(lines),
            });
    }

    private static Task<TestCaseResult> Run(FakeExecutionSession session, params string[] lines)
    {
        var plan = Validate(lines);
        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
        return new CommandExecutor(new ServiceCollection().BuildServiceProvider(), NullLoggerFactory.Instance).ExecuteAsync(plan, session);
    }

    private static IReadOnlyList<RecordAssignment> Assignments(string line, FakeExecutionSession session)
    {
        var step = Validate("use Supervisor", "insert UsrProject as P set UsrName=x", line).Steps[^1];
        var context = new CommandContext(step, Array.Empty<IUiElement>(), session, NullLogger.Instance);
        return context.Assignments(step.Command.Arguments.Skip(3));
    }

    [Test]
    public void A_quoted_value_is_text_in_a_filter_and_a_body_whatever_it_looks_like()
    {
        var session = new FakeExecutionSession();
        var values = Assignments("update UsrInvoice " + Parent + " set UsrNumber=\"0008640\";UsrExternalId=\"" + Guid1 + "\";UsrFlag=\"true\";UsrKind=\"null\"", session);
        var body = ODataValues.Body(values);
        Assert.Multiple(() =>
        {
            Assert.That(values.Select(v => v.Quoted), Is.All.True);
            Assert.That(body.Keys, Is.EqualTo(new[] { "UsrNumber", "UsrExternalId", "UsrFlag", "UsrKind" }), "a quoted GUID is no lookup");
            Assert.That(body.Values, Is.EqualTo(new object[] { "0008640", Guid1, "true", "null" }));
            Assert.That(Commands.CheckRecordCommand.BuildFilter(values, new Dictionary<string, string>()),
                Is.EqualTo("UsrNumber eq '0008640' and UsrExternalId eq '" + Guid1 + "' and UsrFlag eq 'true' and UsrKind eq 'null'"));
        });
    }

    [Test]
    public void A_bare_value_keeps_its_typing_and_a_bare_null_is_null()
    {
        var values = Assignments("update UsrInvoice " + Parent + " set UsrNumber=0008640;UsrBaseDoc=null;UsrOwnerId=null;UsrContact=" + Guid1, new FakeExecutionSession());
        var body = ODataValues.Body(values);
        Assert.Multiple(() =>
        {
            Assert.That(body.Keys, Is.EqualTo(new[] { "UsrNumber", "UsrBaseDocId", "UsrOwnerId", "UsrContactId" }));
            Assert.That(body.Values, Is.EqualTo(new object?[] { 8640m, null, null, Guid1 }));
            Assert.That(ODataValues.FilterLiteral("null"), Is.EqualTo("null"));
            Assert.That(ODataValues.FilterColumn("UsrBaseDoc", "null"), Is.EqualTo("UsrBaseDoc"));
        });
    }

    /// <summary>D92: <c>UsrNumber="";UsrProject=$P</c> is one token with a quote inside; the quote must not hide the alias that follows.</summary>
    [Test]
    public void An_empty_quoted_value_does_not_change_how_the_next_value_is_read()
    {
        var session = new FakeExecutionSession();
        session.Variables["P"] = Guid1;
        var values = Assignments("update UsrInvoice " + Parent + " set UsrNumber=\"\";UsrProject=$P", session);
        var body = ODataValues.Body(values);
        Assert.Multiple(() =>
        {
            Assert.That(values, Is.EqualTo(new[] { new RecordAssignment("UsrNumber", string.Empty, true), new RecordAssignment("UsrProject", Guid1) }));
            Assert.That(body.Keys, Is.EqualTo(new[] { "UsrNumber", "UsrProjectId" }));
            Assert.That(body["UsrNumber"], Is.EqualTo(string.Empty));
        });
    }

    [Test]
    public void A_semicolon_or_an_alias_inside_quotes_stays_text()
    {
        var session = new FakeExecutionSession();
        session.Variables["P"] = Guid1;
        var values = Assignments("update UsrInvoice " + Parent + " set UsrNote=\"a;b=$P\";UsrProject=$P", session);
        Assert.That(values, Is.EqualTo(new[] { new RecordAssignment("UsrNote", "a;b=$P", true), new RecordAssignment("UsrProject", Guid1) }));
    }

    [Test]
    public async Task A_refused_delete_passes_and_a_deleted_record_fails()
    {
        var refused = new FakeExecutionSession
        {
            OnDelete = _ => "delete failed with 400: {\"error\":{\"message\":\"violates foreign key\"}}",
            OnQuery = (_, _, _, _) => new[] { (IReadOnlyDictionary<string, string>)new Dictionary<string, string> { ["Id"] = Parent } },
        };
        var ok = await Run(refused, "use Supervisor", "delete UsrItem " + Parent + " expect error \"FOREIGN KEY\"",
            "delete-record UsrItem Id=" + Parent + " expect error");
        Assert.That(ok.Success, Is.True, ok.FailureSummary);

        var failed = await Run(new FakeExecutionSession(), "use Supervisor", "delete UsrItem " + Parent + " expect error \"foreign key\"");
        Assert.That(failed.FailureSummary, Does.Contain("expected an error containing \"foreign key\" but the record was deleted: " + Parent));

        var wrong = await Run(new FakeExecutionSession { OnDelete = _ => "403 denied" }, "use Supervisor", "delete UsrItem " + Parent + " expect error \"foreign key\"");
        Assert.That(wrong.FailureSummary, Does.Contain("containing \"foreign key\"").And.Contain("403 denied"));
    }

    [Test]
    public void A_refused_delete_does_not_count_as_the_delete_of_an_inserted_alias()
    {
        Assert.Multiple(() =>
        {
            Assert.That(Validate("# writes", "use Supervisor", "insert UsrItem as P set UsrName=x", "delete UsrItem $P expect error \"key\"", "delete UsrItem $P").IsValid, Is.True);
            Assert.That(Validate("# writes", "use Supervisor", "insert UsrItem as P set UsrName=x", "delete UsrItem $P expect error \"key\"").DescribeIssues(), Does.Contain("P"));
            Assert.That(Validate("use Supervisor", "delete UsrItem " + Parent + " expect error \"x\" more").IsValid, Is.False);
        });
    }

    [Test]
    public async Task A_patch_that_created_the_record_puts_it_on_the_cleanup_list()
    {
        foreach (var exists in new[] { false, true })
        {
            var stub = new UpsertHandler(exists);
            using var client = new CreatioODataClient(
                new EnvironmentConfig { BaseUrl = "https://dev.example", Users = { new UserCredentials { Username = "Supervisor", Password = "x" } } },
                new SiteConfig(), NullLogger<CreatioODataClient>.Instance, stub);

            var created = await client.UpdateAsync("UsrItem", Guid.Parse(Parent), ODataValues.Body(new[] { new RecordAssignment("UsrName", "x") }));

            Assert.That(created, Is.EqualTo(!exists), "exists=" + exists);
            Assert.That(stub.Requests, Does.Contain("GET /0/odata/UsrItem?$select=Id&$filter=Id+eq+" + Parent + "&$top=1"));
            Assert.That(stub.Requests.Any(r => r.StartsWith("PATCH ", StringComparison.Ordinal)), Is.True);
        }
    }

    [Test]
    public async Task A_replacing_version_of_the_process_counts_as_a_run_of_it()
    {
        string? filter = null;
        var session = new FakeExecutionSession
        {
            OnQuery = (_, _, f, _) =>
            {
                filter = f.StartsWith("StartDate ge 2000", StringComparison.Ordinal) ? filter : f;
                return new[] { (IReadOnlyDictionary<string, string>)new Dictionary<string, string> { ["Id"] = Guid1, ["CompleteDate"] = string.Empty, ["ErrorDescription"] = string.Empty } };
            },
        };
        var plan = Validate("use Supervisor", "insert UsrOrder as B set UsrName=x", "check-process UsrOrder_Process started");
        await new CheckProcessCommand().ExecuteAsync(new CommandContext(plan.Steps[^1], Array.Empty<IUiElement>(), session, NullLogger.Instance));

        Assert.That(filter, Does.StartWith("(SysSchema/Name eq 'UsrOrder_Process' or SysSchema/Parent/Name eq 'UsrOrder_Process') and (StartDate ge"));
    }

    private sealed class UpsertHandler : HttpMessageHandler
    {
        private readonly bool _exists;

        public UpsertHandler(bool exists) => _exists = exists;

        public List<string> Requests { get; } = new();

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var path = request.RequestUri!.PathAndQuery;
            Requests.Add(request.Method.Method + " " + Uri.UnescapeDataString(path));
            if (path.Contains("AuthService", StringComparison.Ordinal))
            {
                var login = new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("{\"Code\":0}", Encoding.UTF8, "application/json") };
                login.Headers.Add("Set-Cookie", "BPMCSRF=csrf-1; path=/");
                return Task.FromResult(login);
            }

            return Task.FromResult(request.Method == HttpMethod.Get
                ? new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(_exists ? "{\"value\":[{\"Id\":\"" + Parent + "\"}]}" : "{\"value\":[]}", Encoding.UTF8, "application/json"),
                }
                : new HttpResponseMessage(HttpStatusCode.NoContent));
        }
    }
}
