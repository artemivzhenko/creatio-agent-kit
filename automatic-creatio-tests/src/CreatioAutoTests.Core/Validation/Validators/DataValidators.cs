using System.Globalization;
using System.Text.RegularExpressions;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;

namespace CreatioAutoTests.Validation.Validators;

/// <summary>
/// Shape of 'insert':
///   insert UsrOrder as Order set UsrName=Bed;UsrAmount=500
///   insert UsrOrder as Order keep set UsrName=Bed        - the record outlives the case
///   insert UsrOrder as Order set UsrAmount=5 expect error "required"   - the write must be refused; no alias is bound
/// The alias becomes <c>$Order</c>; the record is deleted when the case ends unless kept.
/// </summary>
public sealed class InsertValidator : ICommandValidator
{
    /// <summary>Validates the object, the alias, the optional keep and the assignments.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context)
    {
        const string usage = "'insert <object> as <alias> [keep] set Column=Value;... [expect error \"<text>\"]'";
        if (command.ArgumentCount < 5 || !DataShapes.Is(command, 1, "as"))
        {
            return ValidationResult.Fail("'insert' reads " + usage + ".");
        }

        var alias = CaseVariables.NameOf(command.ValueAt(2)!);
        if (!DataShapes.IsName(alias))
        {
            return ValidationResult.Fail("'" + command.ValueAt(2) + "' is not an alias: letters, digits and '_', starting with a letter.");
        }

        var keep = DataShapes.Is(command, 3, "keep");
        var setAt = keep ? 4 : 3;
        if (!DataShapes.Is(command, setAt, "set"))
        {
            return ValidationResult.Fail("'insert' reads " + usage + "; expected 'set' after the alias.");
        }

        var expect = DataShapes.ExpectError(command);
        return DataShapes.Pairs("insert", command.Arguments.Skip(setAt + 1).Take(expect.Count - setAt - 1).ToArray())
               ?? (expect.Expected
                   ? ValidationResult.Ok() // a refused insert creates nothing, so no alias is bound
                   : ValidationResult.Ok().WithVariable(new VariableEffect(alias, Inserts: true, Kept: keep)));
    }
}

/// <summary>
/// Shape of 'update':
///   update UsrOrder $Order set UsrAmount=5000
///   update UsrOrder 0c48c818-08f0-4f70-9b58-be512227f3bf set UsrAmount=5000
///   update UsrOrder $Order set UsrAmount=-1 expect error "negative"   - the write must be refused
/// </summary>
public sealed class UpdateValidator : ICommandValidator
{
    /// <summary>Validates the object, the record reference and the assignments.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context)
    {
        if (command.ArgumentCount < 4 || !DataShapes.Is(command, 2, "set"))
        {
            return ValidationResult.Fail("'update' reads 'update <object> $alias|<guid> set Column=Value;...'.");
        }

        return DataShapes.IdReference("update", command.Arguments[1])
               ?? DataShapes.Pairs("update", command.Arguments.Skip(3).Take(DataShapes.ExpectError(command).Count - 3).ToArray())
               ?? ValidationResult.Ok();
    }
}

/// <summary>
/// Shape of 'delete':
///   delete UsrOrder $Order
///   delete UsrOrder $Parent expect error "foreign key"   - the delete must be refused
/// A deleted alias leaves the cleanup list, and counts as deleted for '# writes'.
/// </summary>
public sealed class DeleteValidator : ICommandValidator
{
    /// <summary>Validates the object and the record reference.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context)
    {
        var expect = DataShapes.ExpectError(command);
        if (expect.Count != 2)
        {
            return ValidationResult.Fail("'delete' reads 'delete <object> $alias|<guid> [expect error \"<text>\"]'.");
        }

        // A refused delete deletes nothing: the alias still needs its own delete for '# writes'.
        return DataShapes.IdReference("delete", command.Arguments[1])
               ?? ValidationResult.Ok().WithVariable(new VariableEffect(null, Deletes: expect.Expected ? null : DataShapes.AliasIn(command.ValueAt(1)!)));
    }
}

/// <summary>
/// Shape of 'delete-record': every record matching a filter, at most <see cref="DataShapes.DeleteLimit"/>.
///   delete-record UsrOrder Id=$Order
///   delete-record UsrOrderLog UsrOrder=$Order;UsrKind=Big
/// </summary>
public sealed class DeleteRecordValidator : ICommandValidator
{
    /// <summary>Validates the object and the filter.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context)
    {
        if (command.ArgumentCount < 2)
        {
            return ValidationResult.Fail("'delete-record' reads 'delete-record <object> Column=Value;... [expect error \"<text>\"]'.");
        }

        var expect = DataShapes.ExpectError(command);
        var filter = command.Arguments.Skip(1).Take(expect.Count - 1).ToArray();
        if (DataShapes.Pairs("delete-record", filter) is { } error)
        {
            return error;
        }

        // 'Id=$Order' deletes the aliased record: for '# writes' that is the same as 'delete <object> $Order'.
        var text = RecordAssignments.Rejoin(filter);
        var byId = Regex.Match(text, @"^\s*Id\s*=\s*\$([A-Za-z_]\w*)\s*$");
        return ValidationResult.Ok().WithVariable(new VariableEffect(null, Deletes: byId.Success && !expect.Expected ? byId.Groups[1].Value : null));
    }
}

/// <summary>
/// Shape of 'remember': the value of an element, as text, into a case variable.
///   remember UsrNumber as $first
/// </summary>
public sealed class RememberValidator : ICommandValidator
{
    /// <summary>Validates the element, which must hold a value, and the name.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context)
    {
        if (command.ArgumentCount != 3 || !DataShapes.Is(command, 1, "as"))
        {
            return ValidationResult.Fail("'remember' reads 'remember <code> as $name'.");
        }

        var name = CaseVariables.NameOf(command.ValueAt(2)!);
        if (!DataShapes.IsName(name))
        {
            return ValidationResult.Fail("'" + command.ValueAt(2) + "' is not a variable name: '$' and letters, digits, '_'.");
        }

        if (DialogShapes.IsDialog(command))
        {
            return ValidationResult.Ok().WithVariable(new VariableEffect(name)); // the text of the visible dialog (S34-T02)
        }

        var code = command.ValueAt(0)!;
        if (!context.TryResolve(code, out var target, out var error))
        {
            return ValidationResult.Fail("'remember' cannot run: " + error + ".");
        }

        if (target.Entry.ValueKind == ValueKind.None)
        {
            return ValidationResult.Fail("'" + code + "' is a " + target.Entry.Definition.Type + " and has no value to remember.");
        }

        return ValidationResult.Ok(target).WithVariable(new VariableEffect(name));
    }
}

/// <summary>
/// Shape of 'remember-record': the Id of the one record matching a filter, into a case variable.
///   remember-record UsrOrder UsrName=Bed 1 as $order
/// </summary>
public sealed class RememberRecordValidator : ICommandValidator
{
    /// <summary>Validates the object, the filter and the name.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context)
    {
        var asAt = DataShapes.LastIndexOf(command, "as");
        if (command.ArgumentCount < 4 || asAt != command.ArgumentCount - 2 || asAt < 2)
        {
            return ValidationResult.Fail("'remember-record' reads 'remember-record <object> Column=Value;... as $name'.");
        }

        var name = CaseVariables.NameOf(command.ValueAt(asAt + 1)!);
        if (!DataShapes.IsName(name))
        {
            return ValidationResult.Fail("'" + command.ValueAt(asAt + 1) + "' is not a variable name: '$' and letters, digits, '_'.");
        }

        return DataShapes.Pairs("remember-record", command.Arguments.Skip(1).Take(asAt - 1).ToArray())
               ?? ValidationResult.Ok().WithVariable(new VariableEffect(name));
    }
}

/// <summary>
/// Shape of 'check-count':
///   check-count UsrOrderLog UsrOrder=$Order eq 1
///   check-count UsrOrder UsrName=Bed ge $before
/// </summary>
public sealed class CountCheckValidator : ICommandValidator
{
    /// <summary>Validates the object, the filter, the operator and the number.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context)
    {
        if (command.ArgumentCount < 4)
        {
            return ValidationResult.Fail("'check-count' reads 'check-count <object> Column=Value;... eq|ne|gt|ge|lt|le <number>'.");
        }

        var op = command.ValueAt(command.ArgumentCount - 2)!.ToLowerInvariant();
        if (!DataShapes.OrderOperators.Contains(op))
        {
            return ValidationResult.Fail("'check-count' compares with eq, ne, gt, ge, lt or le; found '" + op + "'.");
        }

        var number = command.Arguments[^1];
        if (!long.TryParse(number.Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out _) &&
            !(Regex.IsMatch(number.Value, @"^\$[A-Za-z_]\w*$") && !number.IsQuoted))
        {
            return ValidationResult.Fail("'check-count' needs a whole number or a '$name' to compare with; found '" + number.Value + "'.");
        }

        return DataShapes.Pairs("check-count", command.Arguments.Skip(1).Take(command.ArgumentCount - 3).ToArray()) ?? ValidationResult.Ok();
    }
}

/// <summary>
/// Shape of 'check-distinct': no two matching records share the column's value.
///   check-distinct UsrOrder UsrNumber where UsrName=Bed
/// </summary>
public sealed class DistinctCheckValidator : ICommandValidator
{
    /// <summary>Validates the object, the column and the filter after 'where'.</summary>
    public ValidationResult Validate(ParsedCommand command, ValidationContext context)
    {
        if (command.ArgumentCount < 4 || !DataShapes.Is(command, 2, "where"))
        {
            return ValidationResult.Fail("'check-distinct' reads 'check-distinct <object> <column> where Column=Value;...'.");
        }

        return DataShapes.Pairs("check-distinct", command.Arguments.Skip(3).ToArray()) ?? ValidationResult.Ok();
    }
}

/// <summary>The shared pieces of the data commands' shapes; the commands read their lines with the same helpers.</summary>
public static class DataShapes
{
    /// <summary>'delete-record' refuses a filter matching more records than this: a wide filter is a mistake, not a cleanup.</summary>
    public const int DeleteLimit = 20;

    /// <summary>Operators of an ordered comparison (a count, a number).</summary>
    public static readonly IReadOnlySet<string> OrderOperators = new HashSet<string> { "eq", "ne", "gt", "ge", "lt", "le" };

    /// <summary>Operators of 'check-record ... has': the ordered ones and the text ones.</summary>
    public static readonly IReadOnlySet<string> ValueOperators =
        new HashSet<string> { "eq", "ne", "gt", "ge", "lt", "le", "contains", "startswith", "endswith" };

    /// <summary>Whether the argument at <paramref name="index"/> is the given unquoted word.</summary>
    public static bool Is(ParsedCommand command, int index, string word) =>
        command.ArgumentAt(index) is { IsQuoted: false } token && string.Equals(token.Value, word, StringComparison.OrdinalIgnoreCase);

    /// <summary>Position of the last unquoted <paramref name="word"/>, or -1.</summary>
    public static int LastIndexOf(ParsedCommand command, string word)
    {
        for (var i = command.ArgumentCount - 1; i >= 0; i--)
        {
            if (Is(command, i, word))
            {
                return i;
            }
        }

        return -1;
    }

    /// <summary>
    /// The optional tail <c>expect error ["&lt;text&gt;"]</c> of 'insert', 'update', 'delete' and 'delete-record': how many leading arguments
    /// are the line proper, whether the write must be refused, and the text the refusal must contain.
    /// </summary>
    public static (int Count, bool Expected, string? Text) ExpectError(ParsedCommand command)
    {
        var n = command.ArgumentCount;
        if (n >= 2 && Is(command, n - 2, "expect") && Is(command, n - 1, "error"))
        {
            return (n - 2, true, null);
        }

        return n >= 3 && Is(command, n - 3, "expect") && Is(command, n - 2, "error") ? (n - 3, true, command.Arguments[^1].Value) : (n, false, null);
    }

    /// <summary>
    /// What a refused OData write says: <c>error.message</c> and every <c>innererror.message</c> of the JSON in the
    /// failure text (P-3.10: a listener's text is in the inner one); the whole text when it is not (or no longer, cut at 400) JSON.
    /// </summary>
    public static string ErrorText(string failure)
    {
        var at = failure.IndexOf('{');
        if (at >= 0)
        {
            try
            {
                using var document = System.Text.Json.JsonDocument.Parse(failure[at..]);
                var texts = new List<string>();
                for (var node = document.RootElement.TryGetProperty("error", out var e) ? e : (System.Text.Json.JsonElement?)null; node is { } n;
                     node = n.TryGetProperty("innererror", out var inner) ? inner : null)
                {
                    if (n.TryGetProperty("message", out var message) && message.ValueKind == System.Text.Json.JsonValueKind.String)
                    {
                        texts.Add(message.GetString()!);
                    }
                }

                if (texts.Count > 0)
                {
                    return string.Join(" | ", texts);
                }
            }
            catch (System.Text.Json.JsonException)
            {
            }
        }

        return failure;
    }

    /// <summary>A variable or alias name.</summary>
    public static bool IsName(string name) => Regex.IsMatch(name, @"^[A-Za-z_]\w*$");

    /// <summary>The alias of a <c>$alias</c> reference, or null for a GUID.</summary>
    public static string? AliasIn(string reference) => reference.StartsWith('$') ? CaseVariables.NameOf(reference) : null;

    /// <summary>A record reference is a <c>$alias</c> or a GUID; null when it is one.</summary>
    public static ValidationResult? IdReference(string keyword, CommandToken token) =>
        !token.IsQuoted && (Guid.TryParse(token.Value, out _) || Regex.IsMatch(token.Value, @"^\$[A-Za-z_]\w*$"))
            ? null
            : ValidationResult.Fail("'" + keyword + "' needs the record as '$alias' or a GUID; found '" + token.Value + "'.");

    /// <summary>A <c>Column=Value;...</c> list that parses; null when it does.</summary>
    public static ValidationResult? Pairs(string keyword, IReadOnlyList<CommandToken> tokens)
    {
        if (tokens.Count == 0)
        {
            return ValidationResult.Fail("'" + keyword + "' needs 'Column=Value;Column=Value'.");
        }

        return RecordAssignments.TryParse(RecordAssignments.Rejoin(tokens), out _, out var error)
            ? null
            : ValidationResult.Fail("'" + keyword + "' cannot be read: " + error + ".");
    }
}
