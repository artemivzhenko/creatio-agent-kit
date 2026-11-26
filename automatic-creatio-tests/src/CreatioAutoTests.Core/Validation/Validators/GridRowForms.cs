using CreatioAutoTests.Execution;

namespace CreatioAutoTests.Validation.Validators;

/// <summary>One parsed grid row assertion. <see cref="Kind"/> is <c>rows</c>, <c>row</c>, <c>class</c> or <c>active</c>.</summary>
/// <param name="Kind">Which form.</param>
/// <param name="Row">The 1-based row of <c>row N</c> and <c>active row is N</c>.</param>
/// <param name="Expected">The texts of <c>rows are</c> / <c>row N is</c>, or the one class name.</param>
/// <param name="Column">Caption after <c>column</c>, or null.</param>
/// <param name="Negated">True for <c>has not class</c>.</param>
public sealed record GridRowCheck(string Kind, int Row, IReadOnlyList<string> Expected, string? Column, bool Negated);

/// <summary>
/// The grid forms of <c>check</c>: <c>rows are "a" "b" [column C]</c>, <c>row N is "a" [column C]</c>,
/// <c>row N has [not] class name</c>, <c>active row is N</c>. A comma after a quoted text is accepted and ignored.
/// </summary>
public static class GridRowForms
{
    /// <summary>Whether the line (after the code) starts like one of the forms.</summary>
    public static bool IsForm(ParsedCommand command) =>
        command.ArgumentAt(1) is { IsQuoted: false } w && w.Value.ToLowerInvariant() is "rows" or "row" or "active";

    /// <summary>Parses the line; <paramref name="text"/> turns an argument index into its value (the validator passes the literal, the run resolves <c>$name</c>).</summary>
    public static bool TryParse(ParsedCommand command, Func<int, string> text, out GridRowCheck check, out string error)
    {
        check = new GridRowCheck("", 0, Array.Empty<string>(), null, false);
        var args = command.Arguments;
        var end = args.Count;
        string? column = null;
        if (end >= 4 && !args[end - 2].IsQuoted && args[end - 2].Value.Equals("column", StringComparison.OrdinalIgnoreCase))
        {
            column = text(end - 1);
            end -= 2;
        }

        bool Word(int i, string w) => i < end && !args[i].IsQuoted && args[i].Value.Equals(w, StringComparison.OrdinalIgnoreCase);
        bool Number(int i, out int n) { n = 0; return i < end && !args[i].IsQuoted && int.TryParse(args[i].Value, out n) && n > 0; }
        string Clean(int i) => command.ArgumentAt(i)!.IsQuoted && command.ArgumentAt(i)!.Raw is { } r && r.EndsWith("\",") ? text(i)[..^1] : text(i);
        error = "'check <grid> ...' reads 'rows are \"a\" \"b\" [column <caption>]', 'row <N> is \"a\" [column <caption>]', 'row <N> has [not] class <name>' or 'active row is <N>' (N counts from 1).";

        if (Word(1, "rows") && Word(2, "are") && end > 3)
        {
            check = new GridRowCheck("rows", 0, Enumerable.Range(3, end - 3).Select(Clean).ToList(), column, false);
        }
        else if (Word(1, "row") && Number(2, out var n) && Word(3, "is") && end == 5)
        {
            check = new GridRowCheck("row", n, new[] { Clean(4) }, column, false);
        }
        else if (Word(1, "row") && Number(2, out n) && Word(3, "has") && column is null)
        {
            var not = Word(4, "not");
            if (!Word(not ? 5 : 4 , "class") || end != (not ? 7 : 6))
            {
                return false;
            }

            check = new GridRowCheck("class", n, new[] { text(end - 1) }, null, not);
        }
        else if (Word(1, "active") && Word(2, "row") && Word(3, "is") && Number(4, out n) && end == 5 && column is null)
        {
            check = new GridRowCheck("active", n, Array.Empty<string>(), null, false);
        }
        else
        {
            return false;
        }

        error = string.Empty;
        return true;
    }
}
