using CreatioAutoTests.Commands;
using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Tests.Support;
using CreatioAutoTests.Validation;
using CreatioAutoTests.Validation.Validators;
using Microsoft.Extensions.DependencyInjection;

namespace CreatioAutoTests.Tests;

/// <summary>S34-T04: 'upload' resolves its file under the test data directory before a browser opens.</summary>
[TestFixture]
public sealed class UploadTests
{
    private string _dir = null!;
    private ScriptValidator _validator = null!;

    [SetUp]
    public void SetUp()
    {
        _dir = Path.Combine(Path.GetTempPath(), "act-testdata-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.Combine(_dir, "sub"));
        File.WriteAllText(Path.Combine(_dir, "ok.xlsx"), "x");
        File.WriteAllText(Path.Combine(_dir, "sub", "deep.txt"), "x");
        var services = new ServiceCollection();
        services.AddSingleton<ValueCompatibilityPolicy>();
        _validator = new ScriptValidator(CommandRegistry.Discover(), services.BuildServiceProvider());
    }

    [TearDown]
    public void TearDown() => Directory.Delete(_dir, true);

    private ExecutionPlan Validate(string? dir, params string[] lines)
    {
        var catalog = CatalogBuilder.Build(
            CatalogBuilder.Element("FilesList", "FileUpload", "UsrOrderPage"),
            CatalogBuilder.Element("UsrName", "Text", "UsrOrderPage"));
        var context = new ValidationContext(catalog, new Dictionary<string, string>(), new[] { "tester" }, new Dictionary<string, ObjectDefinition>())
        {
            TestDataDirectory = dir,
        };
        return _validator.Validate("up", "up.act", new ScriptParser().Parse(new[] { "use tester", "open UsrOrderPage" }.Concat(lines).ToArray()), context);
    }

    [TestCase("upload FilesList \"ok.xlsx\"")]
    [TestCase("upload FilesList \"sub/deep.txt\"")]
    public void A_file_under_the_directory_validates(string line) =>
        Assert.That(Validate(_dir, line).IsValid, Is.True);

    [Test]
    public void A_missing_file_is_a_validation_error_naming_the_directory()
    {
        var plan = Validate(_dir, "upload FilesList \"nope.xlsx\"");
        Assert.That(plan.Issues.Single().Message, Does.Contain("there is no file 'nope.xlsx'").And.Contain(_dir));
    }

    [TestCase("upload FilesList \"../outside.txt\"", "leaves the test data directory")]
    [TestCase("upload FilesList \"sub/../../x\"", "leaves the test data directory")]
    [TestCase("upload FilesList \"C:\\Windows\\win.ini\"", "relative")]
    public void A_path_outside_the_directory_is_refused(string line, string reason)
    {
        var plan = Validate(_dir, line);
        Assert.That(plan.IsValid, Is.False);
        Assert.That(plan.Issues.Single().Message, Does.Contain(reason));
    }

    [TestCase("upload FilesList")]
    [TestCase("upload FilesList ok.xlsx")]
    [TestCase("upload FilesList \"ok.xlsx\" extra")]
    [TestCase("upload FilesList \"\"")]
    [TestCase("upload Missing \"ok.xlsx\"")]
    [TestCase("upload UsrName \"ok.xlsx\"")]
    public void A_malformed_upload_or_a_target_that_takes_no_file_is_an_error(string line) =>
        Assert.That(Validate(_dir, line).IsValid, Is.False, line);

    [Test]
    public void Without_a_directory_only_the_shape_is_checked() =>
        Assert.That(Validate(null, "upload FilesList \"anything.bin\"").IsValid, Is.True);

    [Test]
    public void Resolve_keeps_the_file_inside_the_directory()
    {
        Assert.That(UploadValidator.Resolve(_dir, "sub/deep.txt", out _), Is.EqualTo(Path.GetFullPath(Path.Combine(_dir, "sub", "deep.txt"))));
        Assert.That(UploadValidator.Resolve(_dir, "..", out var problem), Is.Null);
        Assert.That(problem, Is.Not.Empty);
    }
}
