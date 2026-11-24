using CreatioAutoTests.Commands;
using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Frontend.Controls;
using CreatioAutoTests.Tests.Support;
using CreatioAutoTests.Validation;
using Microsoft.Extensions.DependencyInjection;

namespace CreatioAutoTests.Tests;

/// <summary>S44-T07: what a set does with the rows of a quick filter's panel.</summary>
[TestFixture]
public sealed class QuickFilterTests
{
    private static readonly (string, bool)[] Rows = { ("Supervisor", false), ("Creatio Webhook Service", true), ("SysPortalConnection", false) };

    [Test]
    public void Only_the_rows_whose_state_differs_are_clicked()
    {
        var (toggle, missing) = QuickFilter.Plan(Rows, new[] { "supervisor", "Creatio Webhook Service" });
        Assert.That(toggle, Is.EqualTo(new[] { "Supervisor" }), "an already ticked wanted row is left alone, the case of the label does not matter");
        Assert.That(missing, Is.Empty);
    }

    [Test]
    public void A_ticked_row_that_is_not_wanted_is_unticked()
    {
        var (toggle, _) = QuickFilter.Plan(Rows, new[] { "SysPortalConnection" });
        Assert.That(toggle, Is.EquivalentTo(new[] { "Creatio Webhook Service", "SysPortalConnection" }));
    }

    [Test]
    public void A_value_the_panel_does_not_offer_is_reported_missing()
    {
        var (_, missing) = QuickFilter.Plan(Rows, new[] { "Nobody", "Supervisor" });
        Assert.That(missing, Is.EqualTo(new[] { "Nobody" }));
    }

    [TestCase("A; B", new[] { "A", "B" })]
    [TestCase(" A ;; B;", new[] { "A", "B" })]
    [TestCase("", new string[0])]
    public void Values_are_split_on_semicolons(string text, string[] expected) =>
        Assert.That(QuickFilter.ParseValues(text), Is.EqualTo(expected));
}

/// <summary>S44-T07: how a row of a Freedom UI grid is matched against the cells a case names.</summary>
[TestFixture]
public sealed class GridRowMatchTests
{
    private static readonly Dictionary<string, string> Row = new(StringComparer.OrdinalIgnoreCase) { ["Name"] = "Bed 1", ["Quantity"] = "3" };

    [Test]
    public void Every_named_cell_must_equal_the_rendered_text()
    {
        Assert.Multiple(() =>
        {
            Assert.That(Frontend.Composite.DataGrid.RowMatches(Row, new[] { new RecordAssignment("Name", "Bed 1") }), Is.True);
            Assert.That(Frontend.Composite.DataGrid.RowMatches(Row, new[] { new RecordAssignment("name", "Bed 1"), new RecordAssignment("Quantity", "3") }), Is.True, "a column caption is not case sensitive");
            Assert.That(Frontend.Composite.DataGrid.RowMatches(Row, new[] { new RecordAssignment("Name", "Bed") }), Is.False, "the text is equal, not contained");
            Assert.That(Frontend.Composite.DataGrid.RowMatches(Row, new[] { new RecordAssignment("Amount", "1") }), Is.False, "a column the grid does not show never matches");
        });
    }
}

/// <summary>S44-T08: the shape of 'select-in-dialog'.</summary>
[TestFixture]
public sealed class SelectInDialogValidationTests
{
    private static ExecutionPlan Validate(string line)
    {
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        var validator = new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider());
        var context = new ValidationContext(CatalogBuilder.Default(), new Dictionary<string, string>(), new[] { "tester" }, new Dictionary<string, ObjectDefinition>());
        return validator.Validate("d", "d.act", new ScriptParser().Parse(new[] { "use tester", line }), context);
    }

    [TestCase("select-in-dialog \"Supervisor\"")]
    [TestCase("select-in-dialog \"Supervisor; Sales\"")]
    public void Values_in_quotes_validate(string line) => Assert.That(Validate(line).IsValid, Is.True);

    [TestCase("select-in-dialog")]
    [TestCase("select-in-dialog \"\"")]
    [TestCase("select-in-dialog \"A\" \"B\"")]
    public void A_missing_or_empty_or_second_argument_is_refused(string line) => Assert.That(Validate(line).IsValid, Is.False);
}
