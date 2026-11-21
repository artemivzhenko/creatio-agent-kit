using CreatioAutoTests.Execution;

namespace CreatioAutoTests.Validation.Validators;

/// <summary>Shape of 'snapshot': one non-empty name, <c>snapshot "after-stage-menu"</c>.</summary>
public sealed class SnapshotValidator : ICommandValidator
{
    /// <summary>One argument that is not blank.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context) =>
        command.ArgumentCount == 1 && !string.IsNullOrWhiteSpace(command.ValueAt(0))
            ? ValidationResult.Ok()
            : ValidationResult.Fail("'snapshot' takes one name: 'snapshot \"after-stage-menu\"'.");
}
