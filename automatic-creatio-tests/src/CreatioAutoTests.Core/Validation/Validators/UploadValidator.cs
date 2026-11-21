using CreatioAutoTests.Execution;

namespace CreatioAutoTests.Validation.Validators;

/// <summary>
/// Shape of 'upload': an element code and the path of a file under the test data directory, quoted.
///   upload AttachmentList "requisites-ok.xlsx"
/// A path that leaves the directory, or a file that is not there, fails validation (the check needs the directory the run was
/// given; without one only the shape is checked, as in unit tests).
/// </summary>
public sealed class UploadValidator : ICommandValidator
{
    /// <summary>Validates the element and the file.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context)
    {
        if (command.ArgumentCount != 2 || command.ArgumentAt(1) is not { IsQuoted: true } path || string.IsNullOrWhiteSpace(path.Value))
        {
            return ValidationResult.Fail("'upload' reads 'upload <code> \"<path under TestData>\"'.");
        }

        if (!context.TryResolve(command.ValueAt(0)!, out var target, out var error))
        {
            return ValidationResult.Fail("'upload' cannot run: " + error + ".");
        }

        if (context.TestDataDirectory is { } directory)
        {
            var full = Resolve(directory, path.Value, out var problem);
            if (full is null)
            {
                return ValidationResult.Fail("'upload " + target.Code + "': " + problem + ".");
            }

            if (!File.Exists(full))
            {
                return ValidationResult.Fail("'upload " + target.Code + "': there is no file '" + path.Value + "' under " + directory + ".");
            }
        }

        return ValidationResult.Ok(target);
    }

    /// <summary>The full path of <paramref name="relative"/> under <paramref name="directory"/>; null with the reason when it leaves it.</summary>
    public static string? Resolve(string directory, string relative, out string problem)
    {
        problem = string.Empty;
        if (Path.IsPathRooted(relative))
        {
            problem = "the path is relative to the test data directory, not absolute";
            return null;
        }

        var root = Path.GetFullPath(directory);
        var full = Path.GetFullPath(Path.Combine(root, relative));
        if (!full.StartsWith(root.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
        {
            problem = "the path leaves the test data directory";
            return null;
        }

        return full;
    }
}
