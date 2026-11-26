using CreatioAutoTests.Frontend;
using CreatioAutoTests.Validation.Validators;

namespace CreatioAutoTests.Commands;

/// <summary>The comparison behind the grid forms of <c>check</c>, kept apart from the browser so it can be tested on plain rows.</summary>
public static class GridRowChecks
{
    /// <summary>The failure message, or null when the assertion holds for these rows.</summary>
    public static string? Evaluate(string grid, GridRowCheck check, IReadOnlyList<GridRowSnapshot> rows)
    {
        if (check.Kind == "rows")
        {
            var actual = rows.Select(r => r.Text).ToList();
            return actual.SequenceEqual(check.Expected, StringComparer.Ordinal)
                ? null
                : "'" + grid + "' shows rows [" + Join(actual) + "] but [" + Join(check.Expected) + "] were expected.";
        }

        if (check.Kind == "active")
        {
            var at = rows.ToList().FindIndex(r => r.Classes.Any(IsActive)) + 1;
            return at == check.Row ? null : "'" + grid + "' " + (at == 0 ? "has no active row" : "has row " + at + " active") + " but row " + check.Row + " was expected.";
        }

        if (check.Row > rows.Count)
        {
            return "'" + grid + "' shows " + rows.Count + " row(s), so there is no row " + check.Row + ".";
        }

        var row = rows[check.Row - 1];
        if (check.Kind == "row")
        {
            return string.Equals(row.Text, check.Expected[0], StringComparison.Ordinal)
                ? null
                : "'" + grid + "' row " + check.Row + " is \"" + row.Text + "\" but \"" + check.Expected[0] + "\" was expected.";
        }

        var has = row.Classes.Contains(check.Expected[0], StringComparer.Ordinal);
        return has != check.Negated
            ? null
            : "'" + grid + "' row " + check.Row + (has ? " has" : " has not") + " class '" + check.Expected[0] + "' (its classes: " + string.Join(" ", row.Classes) + ").";
    }

    /// <summary>The class a grid gives its marked row: <c>active</c>, <c>selected</c> or a <c>...-active</c> / <c>...-selected</c> variant.</summary>
    internal static bool IsActive(string cls) =>
        cls is "active" or "selected" || cls.EndsWith("-active", StringComparison.Ordinal) || cls.EndsWith("-selected", StringComparison.Ordinal);

    private static string Join(IEnumerable<string> texts) => string.Join(", ", texts.Select(t => "\"" + t + "\""));
}
