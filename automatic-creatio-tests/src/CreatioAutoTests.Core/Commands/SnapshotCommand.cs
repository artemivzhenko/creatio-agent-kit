using System.Text.Json;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Validation;
using CreatioAutoTests.Validation.Validators;
using Microsoft.Extensions.Logging;

namespace CreatioAutoTests.Commands;

/// <summary>
/// <c>snapshot "after-stage-menu"</c> writes what the screen shows now (menus, dialogs, masks, stage, tabs, URL) to
/// <c>Reports/snapshots/&lt;case&gt;-&lt;name&gt;.json</c>. The author's eyes before a case is written; it checks nothing and never fails the case (S34-T05).
/// </summary>
[Command("snapshot", Validator = typeof(SnapshotValidator), Usage = "snapshot \"<name>\"")]
public sealed class SnapshotCommand : ICommand
{
    /// <summary>Reads the screen of the active tab and writes the document.</summary>
    public async Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default)
    {
        var name = context.ResolveValue(0);
        var session = context.Session;
        var document = await ScreenSnapshot.ReadAsync(session.RequirePage(), name, session.CaseName, session.ActiveTab, DateTime.Now).ConfigureAwait(false);
        var path = ScreenSnapshot.PathFor(session.Settings.ReportsDirectory, session.CaseName, name);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        await File.WriteAllTextAsync(path, document.ToJsonString(new JsonSerializerOptions { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping }), cancellationToken).ConfigureAwait(false);
        context.Logger.LogInformation("Snapshot {Name}: {Path}", name, path);
    }
}
