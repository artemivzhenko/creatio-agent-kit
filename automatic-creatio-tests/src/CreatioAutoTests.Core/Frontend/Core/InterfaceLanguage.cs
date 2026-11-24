namespace CreatioAutoTests.Frontend;

/// <summary>
/// The few texts the framework reads out of Creatio's interface and that change with the user's language: the aria-label of a date
/// control's picker icon, and the service row a lookup dropdown ends with. One table per language, here and nowhere else.
/// en-US and ru-RU were read from a live page; uk-UA was not (the test site serves no uk-UA resources, S11-T09): its words are
/// Creatio's Ukrainian wording and an unrecognised label falls through to the value rule, so a wrong word costs precision, not a failure.
/// </summary>
internal static class InterfaceLanguage
{
    private static readonly string[] CalendarLabels = ["Calendar", "Календарь", "Календар"];
    private static readonly string[] TimeLabels = ["Time", "Время", "Час"];
    private static readonly string[] DateTimeLabels = ["Date/Time", "Дата/Время", "Дата/Час"];
    private static readonly string[] AddNewPrefixes = ["Add new", "Добавить", "Додати"];

    /// <summary>"Date", "Time" or "DateTime" for the picker icon's label in any known language; null when it is none of them.</summary>
    internal static string? PickerKind(string label)
    {
        var text = label.Trim();
        if (Has(CalendarLabels, text))
        {
            return "Date";
        }

        if (Has(TimeLabels, text))
        {
            return "Time";
        }

        return Has(DateTimeLabels, text) ? "DateTime" : null;
    }

    /// <summary>True for the dropdown's service row ("Add new"), which is never a record to pick.</summary>
    internal static bool IsAddNewRow(string text)
    {
        var start = text.TrimStart();
        return AddNewPrefixes.Any(p => start.StartsWith(p, StringComparison.OrdinalIgnoreCase));
    }

    private static bool Has(string[] labels, string text) => labels.Contains(text, StringComparer.OrdinalIgnoreCase);
}
