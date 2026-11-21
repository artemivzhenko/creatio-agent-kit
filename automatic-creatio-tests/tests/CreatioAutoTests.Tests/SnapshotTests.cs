using System.Text.Json;
using CreatioAutoTests.Commands;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Tests.Support;
using CreatioAutoTests.Validation;
using Microsoft.Extensions.DependencyInjection;

namespace CreatioAutoTests.Tests;

/// <summary>S34-T05: 'snapshot "<name>"' shapes the screen's state into one document and checks nothing.</summary>
[TestFixture]
public sealed class SnapshotTests
{
    private static JsonElement Raw(string json) => JsonDocument.Parse(json).RootElement.Clone();

    [Test]
    public void The_document_carries_menus_dialogs_masks_stage_tabs_url_and_the_tab_number()
    {
        var raw = Raw("""
            {"menus":[{"items":["Edit","Delete"]}],"masks":["div.cdk-overlay-backdrop"],"stage":"Done",
             "tabs":[{"caption":"General","active":true},{"caption":"Files","active":false}],"url":"https://site/0/Shell/#Card/Order/edit/1"}
            """);
        var doc = ScreenSnapshot.Build(raw, new[] { new DialogSnapshot("Save the changes?", new[] { "Cancel", "Save" }) }, "after-stage", "case-1", 2,
            new DateTime(2026, 11, 21, 9, 0, 0));

        Assert.That((string?)doc["name"], Is.EqualTo("after-stage"));
        Assert.That((string?)doc["case"], Is.EqualTo("case-1"));
        Assert.That((int?)doc["tab"], Is.EqualTo(2));
        Assert.That((string?)doc["at"], Is.EqualTo("2026-11-21T09:00:00"));
        Assert.That((string?)doc["stage"], Is.EqualTo("Done"));
        Assert.That((string?)doc["url"], Does.EndWith("/edit/1"));
        Assert.That((string?)doc["menus"]![0]!["items"]![1], Is.EqualTo("Delete"));
        Assert.That((string?)doc["masks"]![0], Is.EqualTo("div.cdk-overlay-backdrop"));
        Assert.That((string?)doc["dialogs"]![0]!["buttons"]![1], Is.EqualTo("Save"));
        Assert.That(doc["tabs"]!.AsArray(), Has.Count.EqualTo(2));
    }

    [Test]
    public void A_screen_with_nothing_open_gives_empty_lists_and_a_null_stage()
    {
        var doc = ScreenSnapshot.Build(Raw("""{"url":"u"}"""), Array.Empty<DialogSnapshot>(), "n", "c", 1, DateTime.Now);

        Assert.That(doc["dialogs"]!.AsArray(), Is.Empty);
        Assert.That(doc["menus"]!.AsArray(), Is.Empty);
        Assert.That(doc["stage"], Is.Null);
    }

    [Test]
    public void The_file_is_named_after_the_case_and_the_name_and_a_bad_character_is_replaced()
    {
        var path = ScreenSnapshot.PathFor("Reports", "my-case", "after: menu/1");

        Assert.That(Path.GetFileName(path), Is.EqualTo("my-case-after_ menu_1.json"));
        Assert.That(Path.GetFileName(Path.GetDirectoryName(path)!), Is.EqualTo("snapshots"));
    }

    [TestCase("snapshot \"x\"", true)]
    [TestCase("snapshot", false)]
    [TestCase("snapshot a b", false)]
    [TestCase("snapshot \"\"", false)]
    public void The_shape_is_one_name(string line, bool valid)
    {
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        var plan = new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider()).Validate("s", "s.act",
            new ScriptParser().Parse(new[] { "use tester", "open TestPage", line }),
            new ValidationContext(CatalogBuilder.Default(), new Dictionary<string, string>(), new[] { "tester" }, new Dictionary<string, CreatioAutoTests.Configuration.ObjectDefinition>()));

        Assert.That(plan.IsValid, Is.EqualTo(valid), plan.DescribeIssues());
    }
}
