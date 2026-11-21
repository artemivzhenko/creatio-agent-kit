using CreatioAutoTests.Execution;

namespace CreatioAutoTests.Tests;

[TestFixture]
public sealed class ODataValuesTests
{
    private const string Guid1 = "0c48c818-08f0-4f70-9b58-be512227f3bf";

    [Test]
    public void A_lookup_is_a_path_in_a_filter_and_an_Id_column_in_a_select_and_a_body()
    {
        Assert.That(ODataValues.FilterColumn("UsrContact", Guid1), Is.EqualTo("UsrContact/Id"));
        Assert.That(ODataValues.ColumnFor("UsrContact", Guid1), Is.EqualTo("UsrContactId"));
        Assert.That(ODataValues.Body(new[] { new RecordAssignment("UsrContact", Guid1) }).Keys, Is.EqualTo(new[] { "UsrContactId" }));
    }

    [TestCase("Id")]
    [TestCase("UsrContact/Id")]
    [TestCase("UsrOwnerId")]
    public void A_column_that_already_ends_in_Id_is_left_alone(string column) =>
        Assert.That(ODataValues.FilterColumn(column, Guid1), Is.EqualTo(column));

    [TestCase("UsrName", "Bed")]
    [TestCase("UsrAmount", "10")]
    [TestCase("UsrActive", "true")]
    public void Only_a_guid_value_makes_a_column_a_lookup_path(string column, string value) =>
        Assert.That(ODataValues.FilterColumn(column, value), Is.EqualTo(column));
}
