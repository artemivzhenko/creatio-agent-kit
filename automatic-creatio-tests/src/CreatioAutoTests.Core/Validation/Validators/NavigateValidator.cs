using CreatioAutoTests.Execution;

namespace CreatioAutoTests.Validation.Validators;

/// <summary>Shape of 'navigate': the shape of 'open', and a page already open in the current tab to leave from.</summary>
public sealed class NavigateValidator : ICommandValidator
{
    /// <summary>The page validator's checks, worded for 'navigate', plus the open-page rule.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context)
    {
        if (string.IsNullOrWhiteSpace(context.CurrentPage))
        {
            return ValidationResult.Fail("'navigate' moves inside the application: a page must be open in this tab first ('open <page>').");
        }

        var result = new PageValidator().Validate(command, context);
        return result.IsValid ? result : ValidationResult.Fail(result.Error!.Replace("'open", "'navigate"));
    }
}
