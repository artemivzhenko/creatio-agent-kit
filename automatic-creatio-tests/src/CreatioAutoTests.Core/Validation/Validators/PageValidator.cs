using CreatioAutoTests.Commands;
using CreatioAutoTests.Execution;

namespace CreatioAutoTests.Validation.Validators;

/// <summary>
/// Shape of 'open': a configured page, optionally an existing record.
///   open TestPage
///   open TestPage for 0c48c818-08f0-4f70-9b58-be512227f3bf
///   open TestPage for ShipmentId        (a static value, e.g. from --static ShipmentId=...)
///   open TestPage for $order            (a case variable)
///   open process-task UsrDemo_Process on UsrDemoPage   (the page of the process's running pre-configured page task, S45-T09)
/// Reports the page it moves to so later lines resolve their codes against it.
/// </summary>
public sealed class PageValidator : ICommandValidator
{
    /// <summary>Validates an <c>open</c> command and advances the virtual page for later code resolution.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context)
    {
        if (OpenCommand.IsProcessTask(command))
        {
            if (command.ArgumentCount != 4 || !string.Equals(command.ValueAt(2), "on", StringComparison.OrdinalIgnoreCase))
            {
                return ValidationResult.Fail("'open process-task' takes a process and the page it shows: 'open process-task <process> on <page>'.");
            }

            return context.Catalog.PageExists(command.ValueAt(3)!)
                ? ValidationResult.OkOnPage(command.ValueAt(3)!)
                : ValidationResult.Fail("Page '" + command.ValueAt(3) + "' is not configured. Known pages: " + string.Join(", ", context.Catalog.PageNames) + ".");
        }

        if (command.ArgumentCount is not (1 or 3))
        {
            return ValidationResult.Fail(
                "'open' takes a page name, optionally followed by 'for <recordId>'.");
        }

        var pageName = command.ValueAt(0)!;
        if (string.IsNullOrWhiteSpace(pageName))
        {
            return ValidationResult.Fail("'open' needs a page name.");
        }

        if (!context.Catalog.PageExists(pageName))
        {
            return ValidationResult.Fail(
                "Page '" + pageName + "' is not configured. Known pages: " +
                string.Join(", ", context.Catalog.PageNames) + ".");
        }

        if (command.ArgumentCount == 3)
        {
            var keyword = command.ValueAt(1)!;
            if (!string.Equals(keyword, "for", StringComparison.OrdinalIgnoreCase))
            {
                return ValidationResult.Fail(
                    "'open <page> <x> <id>' expects 'for' in the middle, found '" + keyword + "'.");
            }

            var id = command.ArgumentAt(2)!;
            if (string.IsNullOrWhiteSpace(id.Value))
            {
                return ValidationResult.Fail("'open <page> for ...' needs a record id.");
            }

            // A quoted id is a literal; an unquoted one is a GUID, a $variable or a static value name.
            if (!id.IsQuoted && !id.Value.Contains('$') && !Guid.TryParse(id.Value, out _) &&
                !context.StaticValues.ContainsKey(id.Value))
            {
                var known = context.StaticValues.Keys.OrderBy(k => k, StringComparer.Ordinal).ToArray();
                return ValidationResult.Fail(
                    "'open " + pageName + " for " + id.Value + "': it is not a record id, a $variable or a static value. " +
                    "Known static values: " + (known.Length == 0 ? "(none)" : string.Join(", ", known)) +
                    ". Add it to static.values.json or run with --static " + id.Value + "=<id>.");
            }
        }

        return ValidationResult.OkOnPage(pageName);
    }
}
