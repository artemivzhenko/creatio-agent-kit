using System.Text.RegularExpressions;
using CreatioAutoTests.Execution;

namespace CreatioAutoTests.Validation.Validators;

/// <summary>What 'check-process' asks (S34-T07): a process the case did not start, and one of four conditions.</summary>
/// <param name="Process">The process schema name.</param>
/// <param name="Kind">started, running, step-completed or step-running.</param>
/// <param name="Caption">The step caption for the step forms.</param>
/// <param name="BudgetMs">The <c>within</c> budget; 0 reads once.</param>
public sealed record ProcessCheck(string Process, string Kind, string Caption, int BudgetMs);

/// <summary>Reading of the 'check-process' line, shared by the validator and the command.</summary>
public static class CheckProcessShapes
{
    private const string Usage = "'check-process <process> [for $record] started | running | step \"<caption>\" completed|running' with an optional 'within <n> second|minute'.";

    /// <summary>Parses the line; false with the message when it is none of the forms.</summary>
    public static bool TryParse(ParsedCommand command, out ProcessCheck check, out string error)
    {
        check = null!;
        error = Usage;
        var words = command.Arguments.ToList();
        var budget = 0;
        if (words.Count >= 4 && DataShapes.Is(command, words.Count - 3, "within"))
        {
            if (!int.TryParse(words[^2].Value, out var amount) || amount <= 0 || words[^1].Value is not ("second" or "minute"))
            {
                error = "'check-process ... within' takes a positive whole number and second or minute.";
                return false;
            }

            budget = checked(amount * (words[^1].Value == "minute" ? 60_000 : 1_000));
            words.RemoveRange(words.Count - 3, 3);
        }

        if (words.Count == 0 || words[0].IsQuoted || !Regex.IsMatch(words[0].Value, @"^[A-Za-z_][A-Za-z0-9_]*$"))
        {
            error = "'check-process' starts with a process schema name (letters, digits, '_'). " + Usage;
            return false;
        }

        var process = words[0].Value;
        words.RemoveAt(0);
        if (words.Count >= 2 && !words[0].IsQuoted && string.Equals(words[0].Value, "for", StringComparison.OrdinalIgnoreCase))
        {
            if (words[1].IsQuoted || !Regex.IsMatch(words[1].Value, @"^\$[A-Za-z_]\w*$"))
            {
                error = "'check-process <process> for' takes a $variable naming the record.";
                return false;
            }

            words.RemoveRange(0, 2);
        }

        string Word(int i) => i < words.Count && !words[i].IsQuoted ? words[i].Value.ToLowerInvariant() : string.Empty;
        if (words.Count == 1 && Word(0) is "started" or "running")
        {
            check = new ProcessCheck(process, Word(0), string.Empty, budget);
            return true;
        }

        if (words.Count == 3 && Word(0) == "step" && words[1].IsQuoted && !string.IsNullOrWhiteSpace(words[1].Value) && Word(2) is "completed" or "running")
        {
            check = new ProcessCheck(process, "step-" + Word(2), words[1].Value, budget);
            return true;
        }

        return false;
    }
}

/// <summary>Shape of 'check-process'.</summary>
public sealed class CheckProcessValidator : ICommandValidator
{
    /// <summary>Validates the line; the process is read from the site's log at run time.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context) =>
        CheckProcessShapes.TryParse(command, out _, out var error) ? ValidationResult.Ok() : ValidationResult.Fail(error);
}
