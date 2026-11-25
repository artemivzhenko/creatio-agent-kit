using CreatioAutoTests.Frontend;
using CreatioAutoTests.Execution;

namespace CreatioAutoTests.Validation.Validators;

/// <summary>
/// Shape: keyword followed by exactly one element code, for example 'click SaveButton'.
/// Reference implementation for every validator: check arity, resolve, return targets.
/// Shared by click, clear and goto.
/// </summary>
public sealed class SingleTargetValidator : ICommandValidator
{
    /// <summary>Validates and statically resolves the single target shared by click, clear, and goto.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context)
    {
        // 'click X no-answer' (S34-T02): a click never answers the dialog it raises; the words state that the case will.
        var noAnswer = command.ArgumentCount == 2 && DataShapes.Is(command, 1, "no-answer") &&
                       string.Equals(command.Keyword, "click", StringComparison.OrdinalIgnoreCase);
        // 'click X expect error "text"' (S46-T06): a refused save is the pass; the same tail parser as 'insert'.
        var isClick = string.Equals(command.Keyword, "click", StringComparison.OrdinalIgnoreCase);
        var expect = isClick ? DataShapes.ExpectError(command) : (1, false, (string?)null);
        if (expect.Item2 && (expect.Item1 != 1 || string.IsNullOrEmpty(expect.Item3)))
        {
            return ValidationResult.Fail("'click' reads 'click <code> expect error \"<text>\"'; the text the refusal shows is required.");
        }

        if (command.ArgumentCount != 1 && !noAnswer && !expect.Item2)
        {
            return ValidationResult.Fail(
                "'" + command.Keyword + "' takes exactly one element code, for example '" +
                command.Keyword + " SaveButton'.");
        }

        var code = command.ValueAt(0)!;
        if (string.IsNullOrWhiteSpace(code))
        {
            return ValidationResult.Fail("'" + command.Keyword + "' needs an element code.");
        }

        if (!context.TryResolve(code, out var target, out var error))
        {
            return ValidationResult.Fail("'" + command.Keyword + "' cannot run: " + error + ".");
        }

        return expect.Item2 && !target.Entry.Supports(typeof(IRefusable))
            ? ValidationResult.Fail("'click " + code + " expect error' needs a Freedom UI Button; '" + code + "' is not one.")
            : ValidationResult.Ok(target);
    }
}
