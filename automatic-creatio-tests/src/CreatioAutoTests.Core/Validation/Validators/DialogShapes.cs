using System.Text.RegularExpressions;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;

namespace CreatioAutoTests.Validation.Validators;

/// <summary>What 'check dialog' asks, parsed once for the validator and the command.</summary>
/// <param name="Kind">shown, not-shown, contains, matches or count.</param>
/// <param name="Argument">The text, the regex or the number.</param>
/// <param name="Op">The operator of the count form.</param>
public sealed record DialogCheck(string Kind, string Argument = "", string Op = "")
{
    /// <summary>Whether the readings satisfy the check; the pure half of the command, tested without a browser.</summary>
    public bool Holds(IReadOnlyList<DialogSnapshot> dialogs) => Kind switch
    {
        "shown" => dialogs.Count > 0,
        "not-shown" => dialogs.Count == 0,
        "contains" => dialogs.Any(d => d.Text.Contains(Argument, StringComparison.OrdinalIgnoreCase)),
        "matches" => dialogs.Any(d => Regex.IsMatch(d.Text, Argument, RegexOptions.IgnoreCase | RegexOptions.Singleline)),
        _ => ValueComparer.Satisfies(ValueKind.Number, dialogs.Count.ToString(), Argument, Op),
    };

    /// <summary>The pause after the condition first holds: "one dialog, not two" needs the second to have had time to appear.</summary>
    public int SettleMs => Kind == "count" && Op is "eq" or "le" or "lt" ? 500 : 0;

    /// <summary>The check as the author wrote it, for the failure message.</summary>
    public string Describe() => Kind switch
    {
        "shown" => "a dialog is shown",
        "not-shown" => "no dialog is shown",
        "contains" => "a dialog contains \"" + Argument + "\"",
        "matches" => "a dialog matches /" + Argument + "/",
        _ => "the number of dialogs is " + Op + " " + Argument,
    };
}

/// <summary>Shapes of the dialog commands (S34-T02): <c>check dialog ...</c>, <c>remember dialog as $x</c>, <c>answer "caption"</c>.</summary>
public static class DialogShapes
{
    private static readonly string[] CountOperators = { "eq", "ne", "gt", "ge", "lt", "le" };

    /// <summary>Whether the command's first word is the unquoted <c>dialog</c>: it is the dialog, not an element of that name.</summary>
    public static bool IsDialog(ParsedCommand command) => DataShapes.Is(command, 0, "dialog");

    /// <summary>Reads the words after <c>check dialog</c>; false with the message when they are none of the forms.</summary>
    public static bool TryParseCheck(ParsedCommand command, out DialogCheck check, out string error)
    {
        check = null!;
        error = "'check dialog' reads 'check dialog [not] shown', 'check dialog contains \"<text>\"', " +
                "'check dialog matches \"<regex>\"' or 'check dialog count eq|ne|gt|ge|lt|le <number>'.";
        var words = command.Arguments.Skip(1).ToArray();
        switch (words.Length)
        {
            case 1 when IsWord(words[0], "shown"):
                check = new DialogCheck("shown");
                return true;
            case 2 when IsWord(words[0], "not") && IsWord(words[1], "shown"):
                check = new DialogCheck("not-shown");
                return true;
            case 2 when IsWord(words[0], "contains"):
                check = new DialogCheck("contains", words[1].Value);
                return true;
            case 2 when IsWord(words[0], "matches"):
                try
                {
                    _ = new Regex(words[1].Value);
                }
                catch (ArgumentException ex)
                {
                    error = "'check dialog matches' has a regex that does not compile: " + ex.Message;
                    return false;
                }

                check = new DialogCheck("matches", words[1].Value);
                return true;
            case 3 when IsWord(words[0], "count"):
                var op = words[1].Value.ToLowerInvariant();
                if (!CountOperators.Contains(op) || !int.TryParse(words[2].Value, out var n) || n < 0)
                {
                    error = "'check dialog count' takes eq, ne, gt, ge, lt or le and a whole number: 'check dialog count eq 1'.";
                    return false;
                }

                check = new DialogCheck("count", n.ToString(), op);
                return true;
            default:
                return false;
        }
    }

    private static bool IsWord(CommandToken token, string word) =>
        !token.IsQuoted && string.Equals(token.Value, word, StringComparison.OrdinalIgnoreCase);
}

/// <summary>Shape of 'answer': the caption of one button of the visible dialog, <c>answer "Yes"</c>.</summary>
public sealed class AnswerValidator : ICommandValidator
{
    /// <summary>One argument, not empty; which buttons the dialog has is only known at run time.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context) =>
        command.ArgumentCount == 1 && !string.IsNullOrWhiteSpace(command.ValueAt(0))
            ? ValidationResult.Ok()
            : ValidationResult.Fail("'answer' takes the caption of one button: 'answer \"Yes\"'.");
}
