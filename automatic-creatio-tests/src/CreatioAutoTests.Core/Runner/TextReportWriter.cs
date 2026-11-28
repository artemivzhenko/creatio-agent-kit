using System.Text;
using CreatioAutoTests.Configuration;
using Microsoft.Extensions.Logging;

namespace CreatioAutoTests.Runner;

/// <summary>Writes a plain text report next to the run and logs a one-line summary per case.</summary>
public sealed class TextReportWriter : IReportWriter
{
    private readonly RunSettings _settings;
    private readonly ILogger<TextReportWriter> _logger;

    /// <summary>Initializes plain-text reporting with configured output location and diagnostics.</summary>
    public TextReportWriter(RunSettings settings, ILogger<TextReportWriter> logger)
    {
        _settings = settings ?? throw new ArgumentNullException(nameof(settings));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    /// <summary>Writes the completed run to a timestamped text artifact and logs its case summary.</summary>
    public async Task WriteAsync(RunResult result, CancellationToken cancellationToken = default)
    {
        var stamp = DateTime.Now.ToString("yyyy-MM-dd-HH-mm-ss");
        var logs = await WriteConsoleLogsAsync(result, stamp, cancellationToken).ConfigureAwait(false);
        await WriteNetworkLogsAsync(result, stamp, cancellationToken).ConfigureAwait(false);
        var report = Render(result, logs);

        Directory.CreateDirectory(_settings.ReportsDirectory);
        var path = Path.Combine(_settings.ReportsDirectory, "run-" + stamp + ".txt");

        await File.WriteAllTextAsync(path, report, cancellationToken).ConfigureAwait(false);

        _logger.LogInformation(
            "{Passed} passed, {Failed} failed in {Duration:0.0}s. Report: {Path}",
            result.Passed,
            result.Failed,
            result.Duration.TotalSeconds,
            path);
    }

    /// <summary>
    /// The whole browser console of each case that has one, as <c>&lt;reports&gt;/console/&lt;stamp&gt;-&lt;case&gt;.log</c>
    /// (one timestamped line per message, page error, failed or 4xx / 5xx request). Returns case name -> absolute path.
    /// </summary>
    private async Task<Dictionary<string, string>> WriteConsoleLogsAsync(RunResult result, string stamp, CancellationToken cancellationToken)
    {
        var logs = new Dictionary<string, string>(StringComparer.Ordinal);
        var folder = Path.Combine(_settings.ReportsDirectory, "console");
        foreach (var testCase in result.Cases.Where(c => c.ConsoleLog.Count > 0))
        {
            Directory.CreateDirectory(folder);
            var name = string.Concat(testCase.Name.Select(c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c));
            var path = Path.GetFullPath(Path.Combine(folder, stamp + "-" + name + ".log"));
            await File.WriteAllLinesAsync(path, testCase.ConsoleLog, cancellationToken).ConfigureAwait(false);
            logs[testCase.Name] = path;
        }

        return logs;
    }

    /// <summary>
    /// The requests of each case as <c>&lt;reports&gt;/network/&lt;stamp&gt;-&lt;case&gt;.log</c>: the slowest ten first, then every request in the
    /// order it finished (duration, status, method, url). Sets the case result's NetworkFile.
    /// </summary>
    private async Task WriteNetworkLogsAsync(RunResult result, string stamp, CancellationToken cancellationToken)
    {
        var folder = Path.Combine(_settings.ReportsDirectory, "network");
        foreach (var testCase in result.Cases.Where(c => c.Network.Count > 0))
        {
            Directory.CreateDirectory(folder);
            var name = string.Concat(testCase.Name.Select(c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c));
            var path = Path.GetFullPath(Path.Combine(folder, stamp + "-" + name + ".log"));
            var lines = new List<string> { "slowest:" };
            lines.AddRange(testCase.Network.OrderByDescending(n => n.Milliseconds).Take(10).Select(n => n.ToString()));
            lines.Add("all, in the order they finished:");
            lines.AddRange(testCase.Network.Select(n => n.ToString()));
            await File.WriteAllLinesAsync(path, lines, cancellationToken).ConfigureAwait(false);
            testCase.NetworkFile = path;
        }
    }

    /// <summary>Also used by the CLI to print the same summary to the console. <paramref name="logs"/>: case name -> console log file.</summary>
    public static string Render(RunResult result, IReadOnlyDictionary<string, string>? logs = null)
    {
        var builder = new StringBuilder();

        if (result.Site is not null)
        {
            builder.AppendLine(result.Site);
        }

        foreach (var line in result.Head)
        {
            builder.AppendLine(line);
        }

        foreach (var warning in result.Warnings)
        {
            builder.AppendLine("warning: " + warning);
        }

        builder.AppendLine("Creatio automated tests");
        builder.AppendLine("Generated: " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));
        builder.AppendLine("Cases: " + result.Cases.Count + "   passed: " + result.Passed +
                           "   failed: " + result.Failed);
        builder.AppendLine("Duration: " + result.Duration.TotalSeconds.ToString("0.00") + "s");
        builder.AppendLine();

        if (result.AnalysisScripts.Count > 0)
        {
            builder.AppendLine("Analysis phase:");
            foreach (var script in result.AnalysisScripts)
            {
                builder.AppendLine("  " + (script.Success ? "ok   " : "FAIL ") + script.Name +
                                   "   (" + script.Duration.TotalSeconds.ToString("0.00") + "s)");

                if (script.FailureSummary is not null)
                {
                    builder.AppendLine("       " + script.FailureSummary);
                }
            }

            builder.AppendLine();
        }

        foreach (var testCase in result.Cases)
        {
            builder.AppendLine((testCase.Success ? "PASS  " : "FAIL  ") + testCase.Name +
                               "   (" + testCase.Duration.TotalSeconds.ToString("0.00") + "s)" + Labels(testCase));

            if (!testCase.IsValid)
            {
                builder.AppendLine("      the case did not run: it does not validate");
                foreach (var issue in testCase.ValidationIssues)
                {
                    builder.AppendLine("      line " + issue.LineNumber + ": " + issue.Message);
                    builder.AppendLine("        " + issue.RawText);
                }

                builder.AppendLine();
                continue;
            }

            if (testCase.RunError is not null)
            {
                builder.AppendLine("      run error: " + testCase.RunError);
            }

            foreach (var failure in testCase.Failures)
            {
                builder.AppendLine("      line " + failure.LineNumber + ": " + failure.Message);
                builder.AppendLine("        " + failure.RawText);
            }

            foreach (var error in testCase.ConsoleErrors)
            {
                builder.AppendLine("      console: " + error);
            }

            if (logs is not null && logs.TryGetValue(testCase.Name, out var log))
            {
                builder.AppendLine("      console log (" + testCase.ConsoleLog.Count + " lines): " + log);
            }

            if (testCase.NetworkFile is not null)
            {
                var errors = testCase.Network.Count(n => n.IsError);
                builder.AppendLine("      network (" + testCase.Network.Count + " requests, " + errors + " error(s), slowest " +
                                   testCase.Network.Max(n => n.Milliseconds) + " ms): " + testCase.NetworkFile);
            }

            foreach (var note in testCase.DevNotes)
            {
                builder.AppendLine("      " + (note.StartsWith("line ") ? "dev-only: " : note.StartsWith("cleanup: ") ? string.Empty : "note: ") + note);
            }

            if (testCase.Screenshot is not null)
            {
                builder.AppendLine("      screenshot at the failure: " + testCase.Screenshot);
            }

            builder.AppendLine();
        }

        if (result.NotRunnable.Count > 0)
        {
            builder.AppendLine("Not runnable (framework gaps):");
            foreach (var gap in result.NotRunnable)
            {
                builder.AppendLine("  " + gap.Name + Labels(gap) + ": " + gap.FrameworkGap);
            }

            builder.AppendLine();
        }

        return builder.ToString();
    }

    /// <summary><c>  [task &lt;folder&gt;, &lt;AC&gt;]</c> from the case's headers, or empty.</summary>
    private static string Labels(Execution.TestCaseResult testCase)
    {
        var labels = new[] { testCase.Task is null ? null : "task " + testCase.Task, testCase.AcceptanceCriterion }.Where(l => l is not null).ToArray();
        return labels.Length == 0 ? string.Empty : "   [" + string.Join(", ", labels) + "]";
    }
}
