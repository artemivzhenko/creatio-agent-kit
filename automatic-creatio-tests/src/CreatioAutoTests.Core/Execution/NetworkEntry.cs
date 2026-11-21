namespace CreatioAutoTests.Execution;

/// <summary>One finished or failed browser request of a case: what the report's network log and 'check network' read.</summary>
public sealed record NetworkEntry(string Method, string Url, int Status, int Milliseconds, string? Failure = null)
{
    /// <summary>A failed request, or a 4xx / 5xx answer.</summary>
    public bool IsError => Failure is not null || Status >= 400;

    /// <summary>`  1234 ms  200  GET https://...` (a failed request shows its reason instead of the status).</summary>
    public override string ToString() =>
        Milliseconds.ToString(System.Globalization.CultureInfo.InvariantCulture).PadLeft(6) + " ms  " +
        (Failure is null ? Status.ToString(System.Globalization.CultureInfo.InvariantCulture) : "FAILED " + Failure) + "  " + Method + " " + Url;
}
