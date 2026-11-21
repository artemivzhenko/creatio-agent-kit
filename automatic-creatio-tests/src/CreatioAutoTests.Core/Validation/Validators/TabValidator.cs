using CreatioAutoTests.Execution;

namespace CreatioAutoTests.Validation.Validators;

/// <summary>
/// Shape of 'tab': a second browser tab of the same session, and the switch between tabs.
///   tab new            (a blank tab, made current; 'open' follows)
///   tab new as second  (the same, with a name)
///   tab 1              (back to the first tab, by number from 1)
///   tab second         (by name)
/// A number that no 'tab new' has made yet, an unknown name, a name taken twice and 'tab new' before any page is open
/// are validation errors: the browser never opens for them.
/// </summary>
public sealed class TabValidator : ICommandValidator
{
    /// <summary>Validates 'tab new [as name]' and 'tab number|name', and tells the validator which tab the script is in after it.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context)
    {
        const string usage = "'tab' takes 'new', 'new as <name>', a tab number or a tab name.";
        var first = command.ValueAt(0);
        if (first is null || command.ArgumentCount > 3)
        {
            return ValidationResult.Fail(usage);
        }

        if (!command.ArgumentAt(0)!.IsQuoted && string.Equals(first, "new", StringComparison.OrdinalIgnoreCase))
        {
            if (command.ArgumentCount is not (1 or 3) || (command.ArgumentCount == 3 && !string.Equals(command.ValueAt(1), "as", StringComparison.OrdinalIgnoreCase)))
            {
                return ValidationResult.Fail("'tab new' takes nothing or 'as <name>'.");
            }

            if (string.IsNullOrWhiteSpace(context.CurrentPage))
            {
                return ValidationResult.Fail("'tab new' needs a page open in the current tab: 'open <page>' comes before it.");
            }

            string? name = null;
            if (command.ArgumentCount == 3)
            {
                name = command.ValueAt(2)!;
                if (!IsName(name))
                {
                    return ValidationResult.Fail("a tab name starts with a letter and holds letters, digits, '_' or '-' (and is not 'new'): '" + name + "'.");
                }

                if (context.FindTab(name) >= 0)
                {
                    return ValidationResult.Fail("a tab named '" + name + "' already exists.");
                }
            }

            return ValidationResult.OkWithTab(new TabEffect(true, name));
        }

        if (command.ArgumentCount != 1)
        {
            return ValidationResult.Fail(usage);
        }

        var index = context.FindTab(first);
        if (index < 0)
        {
            return ValidationResult.Fail(
                "there is no tab '" + first + "' at this point: " + context.TabCount + " open (1" + (context.TabCount > 1 ? "-" + context.TabCount : string.Empty) +
                "); 'tab new' opens one.");
        }

        return ValidationResult.OkWithTab(new TabEffect(false, null, index));
    }

    private static bool IsName(string name) =>
        char.IsLetter(name[0]) && name.All(c => char.IsLetterOrDigit(c) || c is '_' or '-') &&
        !string.Equals(name, "new", StringComparison.OrdinalIgnoreCase);
}
