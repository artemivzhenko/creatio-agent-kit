using System.Diagnostics;
using System.Text.Json;
using System.Text.RegularExpressions;
using CreatioAutoTests.Configuration;

namespace CreatioAutoTests.Runner;

/// <summary>
/// A run of one package's tests in a project's layout <c>&lt;workspace&gt;/tests/&lt;Package&gt;/{unit,integration,e2e,pages}</c>:
/// <c>dotnet test unit/</c>, then the cases of <c>integration/</c> and <c>e2e/</c> only, one report with a line per tier.
/// </summary>
public static class PackageRun
{
    /// <summary>The folder of browser cases inside a package's tests folder.</summary>
    public const string E2e = "e2e";

    /// <summary>The folder of cases without a browser (backend, process, integration) inside a package's tests folder.</summary>
    public const string Integration = "integration";

    /// <summary>The folder of the C# test project inside a package's tests folder.</summary>
    public const string Unit = "unit";

    /// <summary>
    /// <c>&lt;package.workspace&gt;/tests/&lt;package&gt;</c> of <paramref name="projectFile"/> when one is given, else the parent of the
    /// configured case folder named <c>&lt;package&gt;/e2e</c> or <c>&lt;package&gt;/integration</c>; null when neither knows it.
    /// </summary>
    public static string? FindFolder(string package, string? projectFile, IEnumerable<string> configuredFolders)
    {
        if (!string.IsNullOrWhiteSpace(projectFile))
        {
            using var project = JsonDocument.Parse(File.ReadAllText(projectFile),
                new JsonDocumentOptions { CommentHandling = JsonCommentHandling.Skip, AllowTrailingCommas = true });
            if (!project.RootElement.TryGetProperty("package", out var section) ||
                !section.TryGetProperty("workspace", out var workspace) || workspace.ValueKind != JsonValueKind.String)
            {
                throw new InvalidOperationException(projectFile + " has no package.workspace.");
            }

            var root = Path.GetDirectoryName(Path.GetFullPath(projectFile))!;
            return Path.Combine(Path.GetFullPath(workspace.GetString()!, root), "tests", package);
        }

        return configuredFolders
            .Select(f => Path.GetFullPath(f))
            .Where(f => Path.GetFileName(f) is E2e or Integration)
            .Select(Path.GetDirectoryName)
            .FirstOrDefault(p => string.Equals(Path.GetFileName(p), package, StringComparison.OrdinalIgnoreCase));
    }

    /// <summary>
    /// Points this run's case folders at the package's <c>e2e/</c> and <c>integration/</c> only: the folder filter. A tier without its
    /// folder gets an empty list, which scans nothing (never the default Cases / ProcessCases).
    /// </summary>
    public static void UseFolders(EnvironmentConfig environment, string packageFolder)
    {
        environment.CasesFolders = Existing(Path.Combine(packageFolder, E2e));
        environment.ProcessCasesFolders = Existing(Path.Combine(packageFolder, Integration));
    }

    /// <summary>
    /// The package run's configuration: <see cref="UseFolders"/>, and the process files of the package's <c>integration/</c>
    /// loaded whatever the env config names (a run with <c>--project</c> on a config that was never synced).
    /// </summary>
    public static void Use(FrameworkConfiguration configuration, string packageFolder)
    {
        UseFolders(configuration.Environment, packageFolder);
        configuration.LoadProcessesFrom(Path.Combine(packageFolder, Integration));
    }

    private static List<string> Existing(string folder) => Directory.Exists(folder) ? new List<string> { folder } : new List<string>();

    /// <summary>
    /// The project <c>dotnet test</c> runs: a solution, else a project file, in <c>unit/</c>; else one directly in the package's tests
    /// folder, where <c>project.py tests-init</c> put it before S51 (Legacy true); null when there is none.
    /// </summary>
    public static (string Path, bool Legacy)? UnitProject(string packageFolder)
    {
        foreach (var (folder, legacy) in new[] { (Path.Combine(packageFolder, Unit), false), (packageFolder, true) })
        {
            var found = Directory.Exists(folder)
                ? Directory.GetFiles(folder, "*.sln*").Concat(Directory.GetFiles(folder, "*.csproj")).FirstOrDefault()
                : null;
            if (found is not null)
            {
                return (found, legacy);
            }
        }

        return null;
    }

    /// <summary>
    /// Runs <c>dotnet test</c> of the package's unit project: (the <c>unit:</c> lines, failed). No project is not a failure; a project
    /// at the legacy location runs and adds the line that says to move it.
    /// </summary>
    public static async Task<(IReadOnlyList<string> Lines, bool Failed)> RunUnitAsync(string packageFolder, CancellationToken cancellationToken = default)
    {
        if (UnitProject(packageFolder) is not { } found)
        {
            return (new[] { "unit: no unit project" }, false);
        }

        var (project, legacy) = found;

        var start = new ProcessStartInfo("dotnet") { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
        start.ArgumentList.Add("test");
        start.ArgumentList.Add(project);
        // clio's test projects build in their own configuration (project.py tests-init: dotnet test ... -c dev-nf)
        if (Directory.GetFiles(Path.GetDirectoryName(project)!, "*.csproj").Any(p => File.ReadAllText(p).Contains("dev-nf", StringComparison.Ordinal)))
        {
            start.ArgumentList.Add("-c");
            start.ArgumentList.Add("dev-nf");
        }

        using var process = Process.Start(start) ?? throw new InvalidOperationException("dotnet could not be started.");
        var output = process.StandardOutput.ReadToEndAsync(cancellationToken);
        var errors = process.StandardError.ReadToEndAsync(cancellationToken);
        await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
        var (line, failed) = UnitLine(await output.ConfigureAwait(false) + await errors.ConfigureAwait(false), process.ExitCode);
        return (legacy ? new[] { LegacyLine(packageFolder), line } : new[] { line }, failed);
    }

    /// <summary><c>unit: legacy location tests/&lt;Pkg&gt;/ - move it to unit/</c>.</summary>
    public static string LegacyLine(string packageFolder) =>
        "unit: legacy location tests/" + Path.GetFileName(packageFolder) + "/ - move it to unit/";

    /// <summary>
    /// The <c>unit:</c> line from <c>dotnet test</c>'s output: its summary (<c>Failed: M, Passed: N</c>, or the newer
    /// <c>failed: M, succeeded: N</c>) summed over the test assemblies; no summary or a failure is (line, true).
    /// </summary>
    public static (string Line, bool Failed) UnitLine(string output, int exitCode)
    {
        var classic = Regex.Matches(output, @"Failed:\s*(\d+),\s*Passed:\s*(\d+)");
        var newer = Regex.Matches(output, @"failed:\s*(\d+),\s*succeeded:\s*(\d+)", RegexOptions.IgnoreCase);
        var counts = (classic.Count > 0 ? classic : newer)
            .Select(m => (Failed: int.Parse(m.Groups[1].Value), Passed: int.Parse(m.Groups[2].Value)))
            .ToArray();
        if (counts.Length == 0)
        {
            var last = output.Split('\n').Select(l => l.Trim()).LastOrDefault(l => l.Length > 0) ?? string.Empty;
            return ("unit: dotnet test exit " + exitCode + ", no summary: " + last, true);
        }

        var failed = counts.Sum(c => c.Failed);
        return ("unit: " + counts.Sum(c => c.Passed) + " passed, " + failed + " failed", failed > 0 || exitCode != 0);
    }

    /// <summary>
    /// The <c>integration:</c>, <c>e2e:</c> and <c>not runnable:</c> lines of a package run, by the folder of each case; a tier whose
    /// folder list is empty says <c>0 cases (no folder configured)</c>.
    /// </summary>
    public static IEnumerable<string> TierLines(RunResult result, string packageFolder, EnvironmentConfig environment)
    {
        foreach (var (tier, folders) in new[] { (Integration, environment.ProcessCasesFolders), (E2e, environment.CasesFolders) })
        {
            var folder = Path.Combine(packageFolder, tier) + Path.DirectorySeparatorChar;
            var cases = result.Cases.Where(c => Path.GetFullPath(c.FilePath).StartsWith(folder, StringComparison.OrdinalIgnoreCase)).ToArray();
            yield return tier + ": " + (cases.Length > 0
                ? cases.Count(c => c.Success) + " passed, " + cases.Count(c => !c.Success) + " failed"
                : folders is { Count: 0 } ? "0 cases (no folder configured)" : "0 cases");
        }

        yield return "not runnable: " + result.NotRunnable.Count + " (framework gaps)";
    }
}
