using System;
using Terrasoft.Common;
using Terrasoft.Core.Process;

/// <summary>
/// Demonstrates how to read a collection parameter (the rows a Read data element or a sub-process returned) in a Script Task.
/// Get&lt;CompositeObjectList&lt;CompositeObject&gt;&gt;("UsrRows") gives the list; each row is an ICompositeObject keyed by the
/// collection's column codes as declared on the parameter, and TryGetValue&lt;T&gt;(code, out value) is the read that
/// answers false for a key the row does not hold instead of throwing.
/// A null list (the parameter never filled) is the common first-run failure - guard it. To WRITE a collection see
/// HowToWorkWithScriptTaskParameters. The class here is the shape the platform generates around a script task
/// (a ProcessModel with the Get / Set the body uses); the body between the markers is what goes into the designer.
/// </summary>
class UsrSumRows_ProcessScript : ProcessModel {

    public UsrSumRows_ProcessScript(Process process) : base(process) {
    }

    public bool Execute(ProcessExecutingContext context) {
        // --- the script task body ---
        var rows = Get<CompositeObjectList<CompositeObject>>("UsrRows");
        decimal total = 0m;
        int withContact = 0;
        if (rows != null) {
            foreach (ICompositeObject row in rows) {
                if (row.TryGetValue<decimal>("UsrAmount", out decimal amount)) {
                    total += amount;
                }
                if (row.TryGetValue<Guid>("UsrContactId", out Guid contactId) && contactId != Guid.Empty) {
                    withContact++;
                }
            }
        }
        Set("UsrTotal", total);
        Set("UsrRowsWithContact", withContact);
        return true;
        // --- end of the body ---
    }
}
