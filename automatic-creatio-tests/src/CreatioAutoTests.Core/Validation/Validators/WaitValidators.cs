using CreatioAutoTests.Execution;

namespace CreatioAutoTests.Validation.Validators;

/// <summary>
/// Shape of 'wait-record' and 'wait-count' (S34-T03): the line of 'check-record' / 'check-count' followed by
/// <c>within &lt;n&gt; second|minute</c>. The condition is validated by the check's own validator; the wait only adds the budget.
///   wait-record UsrOrder Id=$B has UsrStatus eq Done within 30 second
///   wait-record UsrQueue Order/Id=$B exists within 1 minute
///   wait-count UsrQueue Order/Id=$B ge 2 within 60 second
/// </summary>
public sealed class WaitRecordValidator : ICommandValidator
{
    /// <summary>The check-record line without the budget, then the budget.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context) =>
        WaitShapes.Validate(command, context, "check-record", new RecordCheckValidator());
}

/// <summary>Shape of 'wait-count': 'check-count' plus the budget.</summary>
public sealed class WaitCountValidator : ICommandValidator
{
    /// <summary>The check-count line without the budget, then the budget.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context) =>
        WaitShapes.Validate(command, context, "check-count", new CountCheckValidator());
}

/// <summary>
/// Shape of 'wait-process-task' (S48-T11): the 'open process-task' line with an optional budget.
///   wait-process-task UsrOrder_Process on UsrOrderTaskPage [within 30 second]
/// </summary>
public sealed class WaitProcessTaskValidator : ICommandValidator
{
    /// <summary>Process, 'on', a configured page, then an optional budget; moves the virtual page to that page.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context)
    {
        var line = command;
        if (command.ArgumentCount > 3)
        {
            if (!WaitShapes.TrySplit(command, command.Keyword, out line, out _, out var error))
            {
                return ValidationResult.Fail(error);
            }
        }

        var open = line with { Keyword = "open", Arguments = new[] { new CommandToken("process-task", false) }.Concat(line.Arguments).ToArray() };
        var result = new PageValidator().Validate(open, context);
        return result.IsValid ? result : ValidationResult.Fail(result.Error!.Replace("'open process-task' takes", "'wait-process-task' takes")
            .Replace("'open process-task <process> on <page>'", "'wait-process-task <process> on <page> [within <n> second|minute]'"));
    }
}

/// <summary>Splitting a wait line into the check it repeats and the time it may take.</summary>
public static class WaitShapes
{
    /// <summary>
    /// The check line inside a wait line and the budget in milliseconds; false with the message when the line does not end in
    /// <c>within &lt;whole number&gt; second|minute</c>.
    /// </summary>
    public static bool TrySplit(ParsedCommand command, string checkKeyword, out ParsedCommand check, out int budgetMs, out string error)
    {
        check = command;
        budgetMs = 0;
        error = "'" + command.Keyword + "' ends in 'within <n> second|minute': '" + command.Keyword + " ... within 30 second'.";
        var n = command.ArgumentCount;
        if (n < 4 || !DataShapes.Is(command, n - 3, "within"))
        {
            return false;
        }

        if (!int.TryParse(command.ValueAt(n - 2), out var amount) || amount <= 0)
        {
            error = "'" + command.Keyword + " ... within' takes a positive whole number of second or minute.";
            return false;
        }

        var unit = command.ValueAt(n - 1);
        if (unit is not "second" and not "minute")
        {
            error = "'" + command.Keyword + " ... within " + amount + "' takes the unit 'second' or 'minute'.";
            return false;
        }

        budgetMs = checked(amount * (unit == "minute" ? 60_000 : 1_000));
        check = command with { Keyword = checkKeyword, Arguments = command.Arguments.Take(n - 3).ToArray() };
        return true;
    }

    internal static ValidationResult Validate(ParsedCommand command, ValidationContext context, string checkKeyword, ICommandValidator inner)
    {
        if (!TrySplit(command, checkKeyword, out var check, out _, out var error))
        {
            return ValidationResult.Fail(error);
        }

        var result = inner.Validate(check, context);
        return result.IsValid ? result : ValidationResult.Fail(result.Error!.Replace(checkKeyword, command.Keyword));
    }
}
