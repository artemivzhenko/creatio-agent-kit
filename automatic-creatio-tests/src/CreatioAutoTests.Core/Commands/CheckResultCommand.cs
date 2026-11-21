using CreatioAutoTests.Execution;
using CreatioAutoTests.Validation.Validators;

namespace CreatioAutoTests.Commands;

/// <summary>
/// Compares a result parameter of the process the script last started with an expected value,
/// with the same operators and the same typing as 'check-value'; 'check-result X exists' only
/// asks that the process returned a value for X.
/// </summary>
[Command("check-result",
    Validator = typeof(ResultCheckValidator),
    Usage = "check-result <parameter> eq|ne|gt|ge|lt|le|contains|startswith|endswith \"expected\" | check-result <parameter> exists")]
public sealed class CheckResultCommand : ICommand
{
    /// <summary>Compares the stored result parameter using the parameter's configured type.</summary>
    public Task ExecuteAsync(CommandContext context, CancellationToken cancellationToken = default)
    {
        var run = context.Session.LastProcess
                  ?? throw new CommandFailedException("No process has been started in this case.");

        var code = context.Command.ValueAt(0)!;
        var operatorText = context.Command.ValueAt(1)!.ToLowerInvariant();
        if (context.Command.ArgumentCount == 2)
        {
            // 'exists': the process returned a value for the parameter (not that it is non-empty)
            return run.Results.ContainsKey(code)
                ? Task.CompletedTask
                : throw new CommandFailedException(
                    "'" + run.Process + "' returned no value for '" + code + "'. Returned: " +
                    (run.Results.Count == 0 ? "(nothing)" : string.Join(", ", run.Results.Keys)) + ".");
        }

        var expected = context.ResolveValue(2);

        var parameter = context.Session.Processes[run.Process].Find(code)
                        ?? throw new CommandFailedException("'" + run.Process + "' has no parameter '" + code + "'.");

        if (!run.Results.TryGetValue(code, out var actual))
        {
            throw new CommandFailedException(
                "'" + run.Process + "' returned no value for '" + code + "'. Returned: " +
                (run.Results.Count == 0 ? "(nothing)" : string.Join(", ", run.Results.Keys)) + ".");
        }

        if (!ValueComparer.Satisfies(parameter.ValueKind, actual, expected, operatorText))
        {
            throw new CommandFailedException(
                "'" + code + "' of '" + run.Process + "' is \"" + actual + "\" which is not " + operatorText +
                " \"" + expected + "\".");
        }

        return Task.CompletedTask;
    }
}
