using CreatioAutoTests.Commands;
using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Tests.Support;
using CreatioAutoTests.Validation;
using CreatioAutoTests.Validation.Validators;
using Microsoft.Extensions.DependencyInjection;

namespace CreatioAutoTests.Tests;

/// <summary>S34-T02: 'check dialog', 'answer', 'remember dialog', 'no-answer' on 'set' and 'click'.</summary>
[TestFixture]
public sealed class DialogTests
{
    private ScriptValidator _validator = null!;
    private ScriptParser _parser = null!;
    private ElementCatalog _catalog = null!;

    [SetUp]
    public void SetUp()
    {
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        _validator = new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider());
        _parser = new ScriptParser();
        _catalog = CatalogBuilder.BuildPages(new PageDefinition
        {
            Name = "UsrOrderPage", Url = "/0/Shell/#CardModuleV2/UsrOrderPage", Type = "ClassicUI", Schema = "UsrOrderPage",
            Elements = new List<ElementDefinition>
            {
                CatalogBuilder.Element("Stage", "CasesBar", "UsrOrderPage"),
                CatalogBuilder.Element("UsrName", "Text", "UsrOrderPage"),
                CatalogBuilder.Element("CloseButton", "Button", "UsrOrderPage"),
            },
        });
    }

    private ExecutionPlan Validate(params string[] lines) =>
        _validator.Validate("dialogs", "dialogs.act", _parser.Parse(new[] { "use tester", "open UsrOrderPage" }.Concat(lines).ToArray()),
            new ValidationContext(_catalog, new Dictionary<string, string>(), new[] { "tester" }, new Dictionary<string, ObjectDefinition>()));

    [TestCase("check dialog shown")]
    [TestCase("check dialog not shown")]
    [TestCase("check dialog contains \"to the status\"")]
    [TestCase("check dialog matches \"status (Done|Closed)\"")]
    [TestCase("check dialog count eq 1")]
    [TestCase("check dialog count ge 2")]
    [TestCase("answer \"No\"")]
    [TestCase("remember dialog as $text")]
    [TestCase("set Stage \"Done\" no-answer")]
    [TestCase("click CloseButton no-answer")]
    public void The_dialog_lines_validate(string line)
    {
        var plan = Validate(line);
        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
    }

    [TestCase("check dialog")]
    [TestCase("check dialog open")]
    [TestCase("check dialog contains")]
    [TestCase("check dialog matches \"(\"")]
    [TestCase("check dialog count eq many")]
    [TestCase("check dialog count between 1")]
    [TestCase("check dialog count eq -1")]
    [TestCase("answer")]
    [TestCase("answer \"\"")]
    [TestCase("answer Yes No")]
    [TestCase("remember dialog $text")]
    [TestCase("set UsrName \"a\" no-answer")]
    [TestCase("set Stage \"Done\" yes-answer")]
    [TestCase("click CloseButton yes-answer")]
    [TestCase("click CloseButton no-answer extra")]
    public void A_bad_dialog_line_is_a_validation_error(string line)
    {
        var plan = Validate(line);
        Assert.That(plan.IsValid, Is.False, line);
        Assert.That(plan.Issues.Single().LineNumber, Is.EqualTo(3));
    }

    [Test]
    public void No_answer_on_a_plain_field_names_the_element_that_answers()
    {
        var plan = Validate("set UsrName \"a\" no-answer");
        Assert.That(plan.Issues.Single().Message, Does.Contain("stage bar").And.Contain("UsrName"));
    }

    [Test]
    public void The_remembered_dialog_text_is_a_variable_later_lines_may_use()
    {
        var plan = Validate("remember dialog as $text", "check dialog contains $text");
        Assert.That(plan.IsValid, Is.True, plan.DescribeIssues());
        Assert.That(Validate("check dialog contains $text").IsValid, Is.False);
    }

    [Test]
    public void Click_without_no_answer_and_close_stay_as_they_were()
    {
        Assert.That(Validate("click CloseButton").IsValid, Is.True);
        Assert.That(Validate("click CloseButton CloseButton").IsValid, Is.False);
    }

    private static DialogSnapshot Dialog(string text, params string[] buttons) => new(text, buttons);

    private static DialogCheck Parse(string line)
    {
        var command = new ScriptParser().Parse(new[] { line }).Single();
        Assert.That(DialogShapes.TryParseCheck(command, out var check, out var error), Is.True, error);
        return check;
    }

    [Test]
    public void Shown_and_not_shown_read_the_number_of_dialogs()
    {
        var none = Array.Empty<DialogSnapshot>();
        var one = new[] { Dialog("Done?", "Yes", "No") };

        Assert.That(Parse("check dialog shown").Holds(one), Is.True);
        Assert.That(Parse("check dialog shown").Holds(none), Is.False);
        Assert.That(Parse("check dialog not shown").Holds(none), Is.True);
        Assert.That(Parse("check dialog not shown").Holds(one), Is.False);
    }

    [Test]
    public void Contains_is_case_blind_and_matches_is_a_regex_over_the_whole_text()
    {
        var dialogs = new[] { Dialog("Change the status\nof the order to Done?", "Yes", "No") };

        Assert.That(Parse("check dialog contains \"TO DONE\"").Holds(dialogs), Is.True);
        Assert.That(Parse("check dialog contains \"cancelled\"").Holds(dialogs), Is.False);
        Assert.That(Parse("check dialog matches \"status.*order\"").Holds(dialogs), Is.True);
        Assert.That(Parse("check dialog matches \"^order\"").Holds(dialogs), Is.False);
    }

    [Test]
    public void Count_compares_with_the_operator_and_asks_for_a_pause_where_a_second_dialog_could_still_appear()
    {
        var two = new[] { Dialog("a"), Dialog("b") };

        Assert.That(Parse("check dialog count eq 2").Holds(two), Is.True);
        Assert.That(Parse("check dialog count eq 1").Holds(two), Is.False);
        Assert.That(Parse("check dialog count ge 1").Holds(two), Is.True);
        Assert.That(Parse("check dialog count ne 2").Holds(two), Is.False);
        Assert.That(Parse("check dialog count eq 1").SettleMs, Is.GreaterThan(0));
        Assert.That(Parse("check dialog count ge 1").SettleMs, Is.EqualTo(0));
        Assert.That(Parse("check dialog shown").SettleMs, Is.EqualTo(0));
    }

    [Test]
    public void A_failed_check_says_what_it_expected()
    {
        Assert.That(Parse("check dialog contains \"x\"").Describe(), Does.Contain("contains \"x\""));
        Assert.That(Parse("check dialog count eq 1").Describe(), Does.Contain("eq 1"));
    }
}
