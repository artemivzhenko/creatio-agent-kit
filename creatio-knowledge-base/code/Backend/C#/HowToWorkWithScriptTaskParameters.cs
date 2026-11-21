using System;
using System.Globalization;
using Terrasoft.Common;
using Terrasoft.Core.Process;

/// <summary>
/// Demonstrates how to read and write business process parameters of all supported types
/// inside a Script Task element.
/// Get&lt;T&gt;("ParameterName") reads the current value; Set&lt;T&gt;("ParameterName", value) writes it back.
/// Both methods are process instance methods — available only inside a Script Task.
/// The parameter must be declared in the process designer with a matching type.
/// Supported types: int, decimal, DateTime, Guid, bool, string, LocalizableString, CompositeObjectList.
/// A script task is generated into namespace Terrasoft.Core.Process with the usings of the process's own
/// settings, which differ from process to process: a configuration class called by its short name compiles in one
/// process and fails in another with CS0103 "The name 'UsrOrderHelper' does not exist in the current context" -
/// and while the process does not compile, every start says it "must be published" and writes no SysProcessLog
/// row. Call configuration classes by their full name, Terrasoft.Configuration.UsrOrderHelper (seen on 8.3: both
/// generated sources read from SysSchemaSource, the error from the site's compiler; push.py compiles them).
/// </summary>
class HowToWorkWithScriptTaskParameters {

    // Paste this method body into the Script Task element in the process designer
    public bool Execute(ProcessExecutingContext context) {

        // --- A configuration class: by its full name, the process may not have `using Terrasoft.Configuration` ---
        // var total = new Terrasoft.Configuration.UsrOrderHelper(UserConnection).GetTotal(Get<Guid>("OrderId"));

        // --- Integer ---
        int intValue = Get<int>("IntegerParameter");
        Set("IntegerParameter", intValue + 5);

        // --- String (Text) ---
        string textValue = Get<string>("TextParameter");
        Set("TextParameter", textValue + " updated");

        // --- Guid (Lookup) ---
        Guid lookupValue = Get<Guid>("LookupParameter");
        if (lookupValue == Guid.Empty) {
            // Read a system value — CurrentUserContact is a built-in system value
            lookupValue = (Guid)UserConnection.SystemValueManager
                .GetValue(UserConnection, "CurrentUserContact");
            Set("LookupParameter", lookupValue);
        }

        // --- DateTime ---
        DateTime dateTime = Get<DateTime>("DateTimeParameter");
        Set("DateTimeParameter", dateTime.AddDays(1));

        // --- Decimal (also used for Currency parameters) ---
        decimal decValue = Get<decimal>("DecimalParameter");
        Set("DecimalParameter", decValue + 5.5m);

        // --- Boolean ---
        bool boolValue = Get<bool>("BooleanParameter");
        Set("BooleanParameter", !boolValue);

        // --- LocalizableString ---
        LocalizableString locValue = Get<LocalizableString>("LocalizableStringParameter");
        locValue.SetCultureValue(CultureInfo.GetCultureInfo("en-US"), "Hello");
        locValue.SetCultureValue(CultureInfo.GetCultureInfo("fr-FR"), "Bonjour");
        Set("LocalizableStringParameter", locValue);

        // --- CompositeObjectList (collection or record list parameter) ---
        var list = new CompositeObjectList<CompositeObject>();
        var item = new CompositeObject();
        item["Field1"] = "Value1";
        item["Field2"] = 42;
        list.Add(item);
        Set("CollectionParameter", list);

        // Return true to allow the process flow to continue to the next element
        return true;
    }
}
