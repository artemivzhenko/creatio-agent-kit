using System.Globalization;
using System.Text.RegularExpressions;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Validation;
using CreatioAutoTests.Validation.Validators;
using Microsoft.Extensions.Logging;

namespace CreatioAutoTests.Commands;

/// <summary>The statements of the dev-only commands (S34-T08), built in one place so a test can read them.</summary>
public static class DevSql
{
    /// <summary>.NET ticks (100 ns since 0001-01-01 UTC) at 1970-01-01 UTC: the unit of <c>qrtz_triggers.next_fire_time</c>.</summary>
    public const long TicksAtEpoch = 621355968000000000;

    private static readonly Regex Identifier = new(@"^[A-Za-z_][A-Za-z0-9_]*$", RegexOptions.Compiled);

    /// <summary>Ticks of a UTC moment.</summary>
    public static long Ticks(DateTime utc) => (utc.ToUniversalTime() - DateTime.UnixEpoch).Ticks + TicksAtEpoch;

    /// <summary>The moment a Quartz tick count names.</summary>
    public static DateTime FromTicks(long ticks) => DateTime.UnixEpoch.AddTicks(ticks - TicksAtEpoch);

    /// <summary>
    /// <c>update "UsrOrder" set "UsrStatusId" = '...', "UsrAmount" = 5 where "Id" = '...'</c>: a direct update, no events, no listeners, no
    /// validators. A GUID value goes to the lookup column (<c>UsrStatus</c> becomes <c>UsrStatusId</c>), <c>true</c>/<c>false</c>, <c>null</c> and numbers
    /// are literals, anything else a quoted string.
    /// </summary>
    public static string Seed(string entity, string id, IReadOnlyList<RecordAssignment> values)
    {
        if (!Identifier.IsMatch(entity) || !Guid.TryParse(id, out var guid))
        {
            throw new CommandFailedException("seed: '" + entity + "' / '" + id + "' is not an object name and a record id.");
        }

        var sets = values.Select(v =>
        {
            if (!Identifier.IsMatch(v.Column))
            {
                throw new CommandFailedException("seed: '" + v.Column + "' is not a column name.");
            }

            var isGuid = Guid.TryParse(v.Value, out var value);
            var column = isGuid && !v.Column.EndsWith("Id", StringComparison.Ordinal) ? v.Column + "Id" : v.Column;
            return "\"" + column + "\" = " + Literal(v.Value, isGuid ? value : null);
        });
        return "update \"" + entity + "\" set " + string.Join(", ", sets) + " where \"Id\" = '" + guid.ToString("D") + "'";
    }

    private static string Literal(string text, Guid? guid) =>
        guid is { } g ? "'" + g.ToString("D") + "'"
        : text.Equals("null", StringComparison.OrdinalIgnoreCase) ? "NULL"
        : text is "true" or "false" ? text
        : decimal.TryParse(text, NumberStyles.Number, CultureInfo.InvariantCulture, out _) ? text
        : "'" + text.Replace("'", "''") + "'";

    /// <summary>The pending timers of a process's runs that started at or after <paramref name="sinceUtc"/>; the join S33-T06's <c>process_timers</c> uses.</summary>
    public static string Timers(string process, DateTime sinceUtc)
    {
        if (!Identifier.IsMatch(process))
        {
            throw new CommandFailedException("fire-timer: '" + process + "' is not a process name.");
        }

        return "select t.trigger_name as \"trigger\", t.trigger_state as \"state\", t.next_fire_time as \"next\", e.\"Id\"::text as \"element_id\", e.\"Caption\" as \"caption\" "
               + "from qrtz_triggers t join \"SysProcessElementLog\" e on e.\"Id\"::text = t.job_group join \"SysProcessLog\" l on l.\"Id\" = e.\"SysProcessId\" "
               + "join \"SysSchema\" s on s.\"Id\" = l.\"SysSchemaId\" where s.\"Name\" = '" + process + "' and l.\"StartDate\" >= '"
               + sinceUtc.ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) + "' order by t.next_fire_time";
    }

    /// <summary>The statement S33-T06's MCP <c>fire_timer</c> runs: the trigger of the timer element's log row moved to <paramref name="ticks"/>.</summary>
    public static string Fire(string trigger, string elementId, long ticks) =>
        "update qrtz_triggers set next_fire_time = " + ticks.ToString(CultureInfo.InvariantCulture) + " where trigger_name = '" + trigger.Replace("'", "''")
        + "' and job_group = '" + Guid.Parse(elementId).ToString("D") + "'";
}

/// <summary>
/// <c>seed UsrOrder $A set UsrStatus=0042909f-...</c>: a direct update of a record behind the business logic - no events, no listeners, no validators
/// (a status a page refuses, a date a rule forbids). Only in a case marked <c># dev-only</c> on an environment that allows it; the SQL goes through clio.
/// </summary>
[Command("seed", Validator = typeof(SeedValidator), Usage = "seed <object> $alias|<guid> set Column=Value;...")]
public sealed class SeedCommand : ICommand
{
    /// <summary>Runs the update and records the dev-only line for the report.</summary>
    public async Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default)
    {
        var entity = context.Command.ValueAt(0)!;
        var sql = DevSql.Seed(entity, context.Substitute(context.Command.ValueAt(1)!), context.Assignments(context.Command.Arguments.Skip(3)));
        await DevOnly.Sql(context).RunAsync(sql, cancellationToken).ConfigureAwait(false);
        DevOnly.Note(context, "line " + context.Command.LineNumber + ": data prepared behind the business logic: " + context.Command.RawText);
    }
}

/// <summary>Shape of 'seed': 'update''s shape, and the dev-only directive.</summary>
public sealed class SeedValidator : ICommandValidator
{
    /// <summary>The update shape worded for 'seed'.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context) =>
        DevOnly.Require(command, context) ??
        (command.ArgumentCount < 4 || !DataShapes.Is(command, 2, "set")
            ? ValidationResult.Fail("'seed' reads 'seed <object> $alias|<guid> set Column=Value;...'.")
            : DataShapes.IdReference("seed", command.Arguments[1]) ?? DataShapes.Pairs("seed", command.Arguments.Skip(3).ToArray()) ?? ValidationResult.Ok());
}

/// <summary>
/// <c>fire-timer UsrOrder_Process for $B</c>: moves the pending timer of a run of the process, started in this case, to now + 20 s, so the step after it can be
/// checked without waiting a day (the statement of the MCP <c>fire_timer</c>). Only in a <c># dev-only</c> case on an environment that allows it.
/// </summary>
[Command("fire-timer", Validator = typeof(FireTimerValidator), Usage = "fire-timer <process> [for $record]")]
public sealed class FireTimerCommand : ICommand
{
    /// <summary>Delay between the command and the moment the timer fires, seconds.</summary>
    public const int DelaySeconds = 20;

    /// <summary>Finds the one pending timer and moves it.</summary>
    public async Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default)
    {
        var process = context.Command.ValueAt(0)!;
        var sql = DevOnly.Sql(context);
        var timers = (await sql.RunAsync(DevSql.Timers(process, context.Session.CaseStartedUtc), cancellationToken).ConfigureAwait(false))
            .Where(t => t["state"] is "WAITING" or "ACQUIRED" or "PAUSED").ToArray();
        if (timers.Length != 1)
        {
            throw new CommandFailedException(timers.Length == 0
                ? "fire-timer: no pending timer of " + process + " in a run this case started (or one it caused)."
                : "fire-timer: " + timers.Length + " pending timers of " + process + ": " + string.Join("; ", timers.Select(t => t["caption"] + " (" + t["element_id"] + ")")) + ".");
        }

        var due = DateTime.UtcNow.AddSeconds(DelaySeconds);
        await sql.RunAsync(DevSql.Fire(timers[0]["trigger"], timers[0]["element_id"], DevSql.Ticks(due)), cancellationToken).ConfigureAwait(false);
        DevOnly.Note(context, "line " + context.Command.LineNumber + ": timer '" + timers[0]["caption"] + "' of " + process + " moved to " + due.ToString("HH:mm:ss", CultureInfo.InvariantCulture) + " UTC");
        context.Logger.LogInformation("Timer {Caption} of {Process} fires in {Seconds} s.", timers[0]["caption"], process, DelaySeconds);
    }
}

/// <summary>Shape of 'fire-timer': a process name, optionally 'for $record', and the dev-only directive.</summary>
public sealed class FireTimerValidator : ICommandValidator
{
    /// <summary>One process, an optional record variable.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context)
    {
        if (DevOnly.Require(command, context) is { } refused)
        {
            return refused;
        }

        var shaped = command.ArgumentCount is 1 or 3 && command.ArgumentAt(0) is { IsQuoted: false } && Regex.IsMatch(command.ValueAt(0)!, @"^[A-Za-z_][A-Za-z0-9_]*$")
                     && (command.ArgumentCount == 1 || (DataShapes.Is(command, 1, "for") && command.ArgumentAt(2) is { IsQuoted: false } r && Regex.IsMatch(r.Value, @"^\$[A-Za-z_]\w*$")));
        return shaped ? ValidationResult.Ok() : ValidationResult.Fail("'fire-timer' reads 'fire-timer <process> [for $record]'.");
    }
}

/// <summary>What the dev-only commands share.</summary>
internal static class DevOnly
{
    /// <summary>The refusal when the case does not carry <c># dev-only</c>; null when it does.</summary>
    public static ValidationResult? Require(ParsedCommand command, ValidationContext context) =>
        context.Directives.ContainsKey(Validation.ScriptValidator.DevOnlyDirective)
            ? null
            : ValidationResult.Fail("'" + command.Keyword + "' changes the site behind the business logic: the case must say so in its header with '# dev-only' (and the environment must allow it).");

    public static Session.IDevSql Sql(CommandContext context) =>
        context.Session.DevSql ?? throw new CommandFailedException("dev-only commands need \"ClioEnvironment\" in creatio.env.config.json (the clio environment the SQL runs through).");

    public static void Note(CommandContext context, string text) => context.Session.DevNotes.Add(text);
}
