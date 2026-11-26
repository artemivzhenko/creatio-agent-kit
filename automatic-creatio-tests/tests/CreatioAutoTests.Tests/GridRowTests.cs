using CreatioAutoTests.Commands;
using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Tests.Support;
using CreatioAutoTests.Validation;
using CreatioAutoTests.Validation.Validators;
using Microsoft.Extensions.DependencyInjection;

namespace CreatioAutoTests.Tests;

[TestFixture]
public sealed class GridRowTests
{
    private static GridRowSnapshot Row(string text, params string[] classes) => new(text, classes);

    private static GridRowCheck Parse(string line, out string error)
    {
        var command = new ScriptParser().Parse(new[] { line })[0];
        Assert.That(GridRowForms.TryParse(command, i => command.ValueAt(i)!, out var check, out error), Is.EqualTo(error.Length == 0));
        return check;
    }

    [TestCase("check G rows are \"a\" \"b\"", "rows", 0, "a|b", null, false)]
    [TestCase("check G rows are \"a\", \"b\", \"c\"", "rows", 0, "a|b|c", null, false)]
    [TestCase("check G rows are \"x\" column Name", "rows", 0, "x", "Name", false)]
    [TestCase("check G row 2 is \"b\"", "row", 2, "b", null, false)]
    [TestCase("check G row 1 is \"b\" column Name", "row", 1, "b", "Name", false)]
    [TestCase("check G row 3 has class bold", "class", 3, "bold", null, false)]
    [TestCase("check G row 3 has not class bold", "class", 3, "bold", null, true)]
    [TestCase("check G active row is 2", "active", 2, "", null, false)]
    public void Forms_parse(string line, string kind, int row, string expected, string? column, bool negated)
    {
        var check = Parse(line, out _);

        Assert.That(check.Kind, Is.EqualTo(kind));
        Assert.That(check.Row, Is.EqualTo(row));
        Assert.That(string.Join("|", check.Expected), Is.EqualTo(expected));
        Assert.That(check.Column, Is.EqualTo(column));
        Assert.That(check.Negated, Is.EqualTo(negated));
    }

    [TestCase("check G rows are")]
    [TestCase("check G row 0 is \"a\"")]
    [TestCase("check G row x is \"a\"")]
    [TestCase("check G row 1 has class")]
    [TestCase("check G row 1 has class a b")]
    [TestCase("check G row 1 has class a column Name")]
    [TestCase("check G active row is")]
    public void Malformed_forms_are_refused_with_the_usage(string line)
    {
        Parse(line, out var error);

        Assert.That(error, Does.Contain("rows are"));
    }

    [Test]
    public void Rows_are_compared_in_order()
    {
        var rows = new[] { Row("a"), Row("b") };

        Assert.That(GridRowChecks.Evaluate("G", Parse("check G rows are \"a\" \"b\"", out _), rows), Is.Null);
        Assert.That(GridRowChecks.Evaluate("G", Parse("check G rows are \"b\" \"a\"", out _), rows), Does.Contain("[\"a\", \"b\"]"));
        Assert.That(GridRowChecks.Evaluate("G", Parse("check G rows are \"a\"", out _), rows), Does.Contain("were expected"));
    }

    [Test]
    public void A_row_is_by_its_number()
    {
        var rows = new[] { Row("a"), Row("b") };

        Assert.That(GridRowChecks.Evaluate("G", Parse("check G row 2 is \"b\"", out _), rows), Is.Null);
        Assert.That(GridRowChecks.Evaluate("G", Parse("check G row 1 is \"b\"", out _), rows), Does.Contain("row 1 is \"a\""));
        Assert.That(GridRowChecks.Evaluate("G", Parse("check G row 3 is \"b\"", out _), rows), Does.Contain("no row 3"));
    }

    [Test]
    public void A_class_is_present_or_absent()
    {
        var rows = new[] { Row("a", "row", "bold"), Row("b", "row") };

        Assert.That(GridRowChecks.Evaluate("G", Parse("check G row 1 has class bold", out _), rows), Is.Null);
        Assert.That(GridRowChecks.Evaluate("G", Parse("check G row 2 has not class bold", out _), rows), Is.Null);
        Assert.That(GridRowChecks.Evaluate("G", Parse("check G row 2 has class bold", out _), rows), Does.Contain("has not class 'bold'"));
        Assert.That(GridRowChecks.Evaluate("G", Parse("check G row 1 has not class bold", out _), rows), Does.Contain("has class 'bold'"));
    }

    [Test]
    public void The_active_row_is_the_one_the_grid_marks()
    {
        var rows = new[] { Row("a", "row"), Row("b", "row", "crt-data-table-row-active") };

        Assert.That(GridRowChecks.Evaluate("G", Parse("check G active row is 2", out _), rows), Is.Null);
        Assert.That(GridRowChecks.Evaluate("G", Parse("check G active row is 1", out _), rows), Does.Contain("row 2 active"));
        Assert.That(GridRowChecks.Evaluate("G", Parse("check G active row is 1", out _), new[] { Row("a") }), Does.Contain("no active row"));
    }

    private ExecutionPlan Validate(params string[] lines)
    {
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        var catalog = CatalogBuilder.BuildPages(new PageDefinition
        {
            Name = "ItemList", Url = "/0/Shell/#Section/UsrItem_ListPage",
            Elements = new List<ElementDefinition>
            {
                CatalogBuilder.Element("DataGrid", "DataGrid", "ItemList"),
                CatalogBuilder.Element("ItemsPanel", "ExpansionPanel", "ItemList"),
                CatalogBuilder.Element("OtherPanel", "ExpansionPanel", "ItemList"),
                CatalogBuilder.Element("AddButton", "Button", "ItemList"),
            },
        });
        var context = new ValidationContext(catalog, new Dictionary<string, string>(), new[] { "tester" }, new Dictionary<string, ObjectDefinition>());
        return new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider())
            .Validate("rows", "rows.act", new ScriptParser().Parse(lines), context);
    }

    [Test]
    public void Grid_forms_and_order_validate_on_a_page()
    {
        var plan = Validate("use tester", "open ItemList",
            "check DataGrid rows are \"a\" \"b\"", "check DataGrid row 1 has class bold", "check ItemsPanel is shown",
            "check ItemsPanel is before OtherPanel");

        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
    }

    [Test]
    public void A_button_has_no_rows_and_an_unknown_second_element_is_refused()
    {
        Assert.That(Validate("use tester", "open ItemList", "check AddButton row 1 is \"a\"").Issues[0].Message, Does.Contain("no rows"));
        Assert.That(Validate("use tester", "open ItemList", "check ItemsPanel is before Nope").Issues[0].Message, Does.Contain("Nope"));
    }
}
