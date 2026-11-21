using System.Diagnostics;
using System.Text.Json;

namespace CreatioAutoTests.Session;

/// <summary>
/// SQL for the dev-only commands (S34-T08): run on the site through <c>clio execute-sql-script</c>, never through a direct database connection.
/// The environment is the clio environment <c>ClioEnvironment</c> of <c>creatio.env.config.json</c>; a failure (<c>[ERR]</c>, a non-zero exit)
/// is an exception carrying clio's line.
/// </summary>
public interface IDevSql
{
    /// <summary>Runs one statement; the rows it returns, every value as text (a statement without rows answers an empty list).</summary>
    Task<IReadOnlyList<IReadOnlyDictionary<string, string>>> RunAsync(string sql, CancellationToken cancellationToken = default);
}

/// <summary>The clio-backed <see cref="IDevSql"/>.</summary>
public sealed class ClioDevSql : IDevSql
{
    private readonly string _environment;

    /// <summary>Uses the clio environment of that name.</summary>
    public ClioDevSql(string environment)
    {
        _environment = string.IsNullOrWhiteSpace(environment) ? throw new ArgumentException("a clio environment name is required", nameof(environment)) : environment;
    }

    /// <inheritdoc />
    public async Task<IReadOnlyList<IReadOnlyDictionary<string, string>>> RunAsync(string sql, CancellationToken cancellationToken = default)
    {
        var folder = Path.Combine(Path.GetTempPath(), "act-devsql-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        try
        {
            var script = Path.Combine(folder, "q.sql");
            var output = Path.Combine(folder, "out.json");
            await File.WriteAllTextAsync(script, sql, cancellationToken).ConfigureAwait(false);
            var start = new ProcessStartInfo("clio")
            {
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            foreach (var argument in new[] { "execute-sql-script", "-e", _environment, "-f", script, "-v", "json", "-d", output })
            {
                start.ArgumentList.Add(argument);
            }

            using var process = Process.Start(start) ?? throw new InvalidOperationException("clio could not be started.");
            var text = await process.StandardOutput.ReadToEndAsync(cancellationToken).ConfigureAwait(false)
                       + await process.StandardError.ReadToEndAsync(cancellationToken).ConfigureAwait(false);
            await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
            var failure = text.Split('\n').Select(l => l.Trim()).FirstOrDefault(l => l.Contains("[ERR]"));
            if (process.ExitCode != 0 || failure is not null)
            {
                throw new InvalidOperationException("sql: " + (failure ?? "clio exited " + process.ExitCode));
            }

            var json = File.Exists(output) ? (await File.ReadAllTextAsync(output, cancellationToken).ConfigureAwait(false)).Trim().TrimStart('﻿') : string.Empty;
            if (json.Length == 0 || !json.StartsWith('['))
            {
                return Array.Empty<IReadOnlyDictionary<string, string>>();
            }

            using var document = JsonDocument.Parse(json);
            return document.RootElement.EnumerateArray()
                .Select(row => (IReadOnlyDictionary<string, string>)row.EnumerateObject().ToDictionary(
                    p => p.Name,
                    p => p.Value.ValueKind == JsonValueKind.Null ? string.Empty : p.Value.ValueKind == JsonValueKind.String ? p.Value.GetString()! : p.Value.GetRawText(),
                    StringComparer.OrdinalIgnoreCase))
                .ToArray();
        }
        finally
        {
            Directory.Delete(folder, true);
        }
    }
}
