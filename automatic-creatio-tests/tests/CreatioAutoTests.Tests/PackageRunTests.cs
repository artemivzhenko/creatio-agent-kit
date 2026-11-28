using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend.Registry;
using CreatioAutoTests.Runner;
using Microsoft.Extensions.DependencyInjection;

namespace CreatioAutoTests.Tests;

/// <summary>
/// A project's layout <c>tests/&lt;Package&gt;/{unit,integration,e2e,pages}</c> (S51-T01): the pages folders, the folder filter,
/// the <c># framework:</c> case listed and never run, the unit and tier lines of the report.
/// </summary>
[TestFixture]
public sealed class PackageRunTests
{
    private string _root = null!;

    [SetUp]
    public void SetUp()
    {
        _root = Path.Combine(Path.GetTempPath(), "creatio-package-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.Combine(_root, "Configuration", "pages"));
        File.WriteAllText(Path.Combine(_root, "Configuration", "creatio.site.config.json"), "{}");
        WritePage(Path.Combine(_root, "Configuration", "pages"), "P");
    }

    [TearDown]
    public void TearDown() => Directory.Delete(_root, recursive: true);

    private string Package => Path.Combine(_root, "ws", "tests", "UsrOrder");

    private static void WritePage(string folder, string name, string file = "")
    {
        Directory.CreateDirectory(folder);
        File.WriteAllText(Path.Combine(folder, (file.Length > 0 ? file : name) + ".json"),
            "{\"name\":\"" + name + "\",\"url\":\"/" + name + "\",\"type\":\"FreedomUI\",\"elements\":[{\"code\":\"UsrName\",\"label\":\"\",\"type\":\"Text\"}]}");
    }

    private void WriteEnvironment(string extra) =>
        File.WriteAllText(Path.Combine(_root, "Configuration", "creatio.env.config.json"),
            "{\"BaseUrl\":\"https://dev.example.com\",\"Users\":[{\"Username\":\"Supervisor\",\"Password\":\"p\"}]" + extra + "}");

    private FrameworkConfiguration Load() =>
        FrameworkConfiguration.Load(_root, UiElementRegistry.Discover(typeof(FrameworkConfiguration).Assembly));

    [Test]
    public void Pages_folders_are_read_beside_Configuration_pages_and_a_missing_one_is_skipped()
    {
        WritePage(Path.Combine(Package, "pages"), "UsrOrderForm");
        WriteEnvironment(",\"PagesFolders\":[\"ws/tests/UsrOrder/pages\",\"ws/tests/UsrNone/pages\"]");

        var catalog = Load().Catalog;

        Assert.That(catalog.Pages.Select(p => p.Name), Is.EquivalentTo(new[] { "P", "UsrOrderForm" }));
    }

    [Test]
    public void A_page_name_found_in_two_folders_is_an_error_naming_both_files()
    {
        WritePage(Path.Combine(Package, "pages"), "UsrOrderForm");
        WritePage(Path.Combine(_root, "ws", "tests", "UsrShipment", "pages"), "UsrOrderForm", "Copy");
        WriteEnvironment(",\"PagesFolders\":[\"ws/tests/UsrOrder/pages\",\"ws/tests/UsrShipment/pages\"]");

        var error = Assert.Catch(() => Load())!;

        Assert.That(error.Message, Does.Contain("'UsrOrderForm' is declared twice")
            .And.Contain(Path.Combine(Package, "pages", "UsrOrderForm.json"))
            .And.Contain(Path.Combine(_root, "ws", "tests", "UsrShipment", "pages", "Copy.json")));
    }

    [Test]
    public void The_package_folder_comes_from_project_json_or_from_the_configured_folders()
    {
        var project = Path.Combine(_root, "project.json");
        File.WriteAllText(project, "{ // a comment\n\"package\": {\"name\": \"UsrPkg\", \"workspace\": \"ws\"},}");
        var configured = new[] { Path.Combine(_root, "Cases"), Path.Combine(Package, "e2e"), Path.Combine(_root, "ws", "tests", "UsrShipment", "integration") };

        Assert.Multiple(() =>
        {
            Assert.That(PackageRun.FindFolder("UsrOrder", project, Array.Empty<string>()), Is.EqualTo(Package));
            Assert.That(PackageRun.FindFolder("usrorder", null, configured), Is.EqualTo(Package));
            Assert.That(PackageRun.FindFolder("UsrShipment", null, configured), Is.EqualTo(Path.Combine(_root, "ws", "tests", "UsrShipment")));
            Assert.That(PackageRun.FindFolder("UsrNone", null, configured), Is.Null);
        });
    }

    [Test]
    public void A_package_run_scans_its_own_folders_only_and_lists_a_framework_case_without_running_it()
    {
        Directory.CreateDirectory(Path.Combine(Package, "e2e"));
        Directory.CreateDirectory(Path.Combine(Package, "integration"));
        File.WriteAllText(Path.Combine(Package, "integration", "012-AC-04.act"),
            "# task: 012-order\n# ac: AC-04\n# framework: a step the DSL cannot express yet\nuse Supervisor\ncheck-count UsrOrder UsrName=Bed eq 0\n");
        var other = Path.Combine(_root, "ws", "tests", "UsrShipment", "integration");
        Directory.CreateDirectory(other);
        File.WriteAllText(Path.Combine(other, "013-AC-01.act"), "use Supervisor\ncheck-count UsrOrder UsrName=Bed eq 0\n");
        WriteEnvironment(",\"ProcessCasesFolders\":[\"ws/tests/UsrOrder/integration\",\"ws/tests/UsrShipment/integration\"]");

        var services = new ServiceCollection()
            .AddSingleton<Microsoft.Extensions.Logging.ILoggerFactory>(Microsoft.Extensions.Logging.Abstractions.NullLoggerFactory.Instance)
            .AddSingleton(typeof(Microsoft.Extensions.Logging.ILogger<>), typeof(Microsoft.Extensions.Logging.Abstractions.NullLogger<>));
        services.AddCreatioAutoTests(_root);
        using var provider = services.BuildServiceProvider();
        var configuration = provider.GetRequiredService<FrameworkConfiguration>();
        var folder = PackageRun.FindFolder("UsrOrder", null, configuration.ProcessCasesFolders)!;
        PackageRun.UseFolders(configuration.Environment, folder);
        var runner = provider.GetRequiredService<TestRunner>();

        Assert.That(runner.DiscoverProcessFiles().Select(Path.GetFileName), Is.EqualTo(new[] { "012-AC-04.act" }));
        var result = runner.RunAsync().GetAwaiter().GetResult();
        result.Head.AddRange(PackageRun.TierLines(result, folder, configuration.Environment));
        var report = TextReportWriter.Render(result);

        Assert.Multiple(() =>
        {
            Assert.That(result.Cases, Is.Empty, "never started");
            Assert.That(result.NotRunnable.Single().FrameworkGap, Is.EqualTo("a step the DSL cannot express yet"));
            Assert.That(result.Success, Is.True, "a gap is not a failure");
            Assert.That(result.Head, Is.EqualTo(new[] { "integration: 0 cases", "e2e: 0 cases", "not runnable: 1 (framework gaps)" }));
            Assert.That(report, Does.Contain("Not runnable (framework gaps):" + Environment.NewLine +
                                             "  012-AC-04   [task 012-order, AC-04]: a step the DSL cannot express yet"));
        });
    }

    [Test]
    public void Process_cases_run_before_UI_cases()
    {
        foreach (var (tier, name) in new[] { ("e2e", "012-AC-01"), ("integration", "012-AC-02") })
        {
            Directory.CreateDirectory(Path.Combine(Package, tier));
            File.WriteAllText(Path.Combine(Package, tier, name + ".act"), "use Supervisor\ncheck-count UsrOrder UsrName=Bed eq 0\n");
        }

        WriteEnvironment(",\"CasesFolders\":[\"ws/tests/UsrOrder/e2e\"],\"ProcessCasesFolders\":[\"ws/tests/UsrOrder/integration\"]");
        var services = new ServiceCollection()
            .AddSingleton<Microsoft.Extensions.Logging.ILoggerFactory>(Microsoft.Extensions.Logging.Abstractions.NullLoggerFactory.Instance)
            .AddSingleton(typeof(Microsoft.Extensions.Logging.ILogger<>), typeof(Microsoft.Extensions.Logging.Abstractions.NullLogger<>));
        services.AddCreatioAutoTests(_root);
        using var provider = services.BuildServiceProvider();

        var result = provider.GetRequiredService<TestRunner>().RunAsync().GetAwaiter().GetResult();

        Assert.That(result.Cases.Select(c => c.Name), Is.EqualTo(new[] { "012-AC-02", "012-AC-01" }), "the integration case is recorded first");
    }

    [Test]
    public void A_package_run_loads_the_process_files_beside_its_cases_whatever_the_config_names()
    {
        var integration = Path.Combine(Package, "integration");
        Directory.CreateDirectory(integration);
        File.WriteAllText(Path.Combine(integration, "UsrOrder_Process.json"),
            "{\"name\":\"UsrOrder_Process\",\"parameters\":[{\"code\":\"Amount\",\"type\":\"Money\",\"direction\":\"in\"}," +
            "{\"code\":\"Verdict\",\"type\":\"Text\",\"direction\":\"out\"}]}");
        var testCase = Path.Combine(integration, "012-AC-05.act");
        File.WriteAllText(testCase, "use Supervisor\nstart UsrOrder_Process with Amount=500\ncheck-result Verdict eq \"big\"\n");
        WriteEnvironment(",\"ProcessCasesFolders\":[\"ws/tests/UsrShipment/integration\"]");  // a config that was never synced for UsrOrder

        var services = new ServiceCollection()
            .AddSingleton<Microsoft.Extensions.Logging.ILoggerFactory>(Microsoft.Extensions.Logging.Abstractions.NullLoggerFactory.Instance)
            .AddSingleton(typeof(Microsoft.Extensions.Logging.ILogger<>), typeof(Microsoft.Extensions.Logging.Abstractions.NullLogger<>));
        services.AddCreatioAutoTests(_root);
        using var provider = services.BuildServiceProvider();
        var configuration = provider.GetRequiredService<FrameworkConfiguration>();
        var runner = provider.GetRequiredService<TestRunner>();
        Assert.That(runner.Validate(testCase).IsValid, Is.False, "before the package run the process is unknown");

        PackageRun.Use(configuration, Package);
        PackageRun.Use(configuration, Package);  // a second call skips the files it already loaded

        var plan = runner.Validate(testCase);
        Assert.Multiple(() =>
        {
            Assert.That(runner.DiscoverProcessFiles(), Is.EqualTo(new[] { testCase }));
            Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
            Assert.That(configuration.Processes["UsrOrder_Process"].SourceFile, Is.EqualTo(Path.Combine(integration, "UsrOrder_Process.json")));
        });
    }

    [Test]
    public void The_unit_line_is_the_dotnet_test_summary_and_no_project_is_not_a_failure()
    {
        Assert.Multiple(() =>
        {
            Assert.That(PackageRun.UnitProject(Package), Is.Null);
            var (lines, failed) = PackageRun.RunUnitAsync(Package).GetAwaiter().GetResult();
            Assert.That(lines, Is.EqualTo(new[] { "unit: no unit project" }));
            Assert.That(failed, Is.False);
            Assert.That(PackageRun.UnitLine("Passed!  - Failed:     0, Passed:    12, Skipped:     0, Total:    12, Duration: 4 s - X.dll", 0),
                Is.EqualTo(("unit: 12 passed, 0 failed", false)));
            Assert.That(PackageRun.UnitLine("Test summary: total: 5, failed: 1, succeeded: 4, skipped: 0, duration: 1s", 1),
                Is.EqualTo(("unit: 4 passed, 1 failed", true)));
            Assert.That(PackageRun.UnitLine("error CS1002: ; expected\nBuild FAILED.\n", 1),
                Is.EqualTo(("unit: dotnet test exit 1, no summary: Build FAILED.", true)));
        });
    }

    [Test]
    public void The_tier_lines_count_the_cases_by_their_folder()
    {
        var result = new RunResult
        {
            Cases = new[]
            {
                new TestCaseResult { Name = "a", FilePath = Path.Combine(Package, "integration", "a.act") },
                new TestCaseResult { Name = "b", FilePath = Path.Combine(Package, "e2e", "sub", "b.act"), RunError = "x" },
            },
        };

        var environment = new EnvironmentConfig { CasesFolders = new(), ProcessCasesFolders = new() { Path.Combine(Package, "integration") } };

        Assert.That(PackageRun.TierLines(result, Package, environment),
            Is.EqualTo(new[] { "integration: 1 passed, 0 failed", "e2e: 0 passed, 1 failed", "not runnable: 0 (framework gaps)" }));
        Assert.That(PackageRun.TierLines(new RunResult { Cases = Array.Empty<TestCaseResult>() }, Package, environment),
            Is.EqualTo(new[] { "integration: 0 cases", "e2e: 0 cases (no folder configured)", "not runnable: 0 (framework gaps)" }));
    }

    [Test]
    public void A_unit_project_in_unit_wins_and_one_at_the_legacy_location_is_found_with_the_line_to_move_it()
    {
        Directory.CreateDirectory(Package);
        File.WriteAllText(Path.Combine(Package, "UsrOrder.Tests.csproj"), "<Project />");

        Assert.That(PackageRun.UnitProject(Package), Is.EqualTo((Path.Combine(Package, "UsrOrder.Tests.csproj"), true)));
        Assert.That(PackageRun.LegacyLine(Package), Is.EqualTo("unit: legacy location tests/UsrOrder/ - move it to unit/"));

        Directory.CreateDirectory(Path.Combine(Package, "unit"));
        File.WriteAllText(Path.Combine(Package, "unit", "UsrOrder.Tests.csproj"), "<Project />");
        Assert.That(PackageRun.UnitProject(Package), Is.EqualTo((Path.Combine(Package, "unit", "UsrOrder.Tests.csproj"), false)));
    }

    [Test]
    public void An_empty_folder_list_means_none_and_only_an_absent_key_means_the_default_folders()
    {
        WriteEnvironment(",\"CasesFolders\":[],\"ProcessCasesFolders\":[]");
        var empty = Load();
        WriteEnvironment(string.Empty);
        var absent = Load();
        var environment = new EnvironmentConfig();
        Directory.CreateDirectory(Path.Combine(Package, "integration"));
        PackageRun.UseFolders(environment, Package);

        Assert.Multiple(() =>
        {
            Assert.That(empty.CasesFolders, Is.Empty);
            Assert.That(empty.ProcessCasesFolders, Is.Empty);
            Assert.That(absent.CasesFolders, Is.EqualTo(new[] { Path.Combine(_root, "Cases") }));
            Assert.That(absent.ProcessCasesFolders, Is.EqualTo(new[] { Path.Combine(_root, "ProcessCases") }));
            Assert.That(environment.CasesFolders, Is.Empty, "a package without e2e/ scans no case folder");
            Assert.That(environment.ProcessCasesFolders, Is.EqualTo(new[] { Path.Combine(Package, "integration") }));
        });
    }

    [Test]
    public void Process_files_are_read_from_the_process_cases_folders_and_a_name_declared_twice_names_both_files()
    {
        var integration = Path.Combine(Package, "integration");
        Directory.CreateDirectory(integration);
        File.WriteAllText(Path.Combine(integration, "UsrOrder_Process.json"), "{\"name\":\"UsrOrder_Process\",\"parameters\":[]}");
        WriteEnvironment(",\"ProcessCasesFolders\":[\"ws/tests/UsrOrder/integration\"]");

        Assert.That(Load().Processes.Keys, Is.EquivalentTo(new[] { "UsrOrder_Process" }));

        var processes = Path.Combine(_root, "Configuration", "processes");
        Directory.CreateDirectory(processes);
        File.WriteAllText(Path.Combine(processes, "Copy.json"), "{\"name\":\"UsrOrder_Process\",\"parameters\":[]}");
        var error = Assert.Catch(() => Load())!;

        Assert.That(error.Message, Does.Contain("'UsrOrder_Process' is declared twice")
            .And.Contain(Path.Combine(integration, "UsrOrder_Process.json"))
            .And.Contain(Path.Combine(processes, "Copy.json")));
    }
}
