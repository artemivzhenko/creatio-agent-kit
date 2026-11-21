using CreatioAutoTests.Configuration;

namespace CreatioAutoTests.Validation;

/// <summary>
/// Everything the validation pass knows without a browser: the catalog, static values, users and
/// objects, plus the page the script is standing on at this point in the file.
/// </summary>
public sealed class ValidationContext
{
    /// <summary>Initializes all configuration data the static validation pass may consult.</summary>
    public ValidationContext(
        ElementCatalog catalog,
        IReadOnlyDictionary<string, string> staticValues,
        IReadOnlyCollection<string> knownUsers,
        IReadOnlyDictionary<string, ObjectDefinition> objects)
    {
        Catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
        StaticValues = staticValues ?? throw new ArgumentNullException(nameof(staticValues));
        Objects = objects ?? throw new ArgumentNullException(nameof(objects));
        KnownUsers = new HashSet<string>(knownUsers, StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>Page and element definitions used to resolve DSL codes without a browser.</summary>
    public ElementCatalog Catalog { get; }

    /// <summary>Named literal values available to assignment and comparison commands.</summary>
    public IReadOnlyDictionary<string, string> StaticValues { get; }

    /// <summary>Configured creation workflows checked by the <c>create</c> validator.</summary>
    public IReadOnlyDictionary<string, ObjectDefinition> Objects { get; }

    /// <summary>Configured user names accepted by the <c>use</c> command.</summary>
    public IReadOnlySet<string> KnownUsers { get; }

    /// <summary>Page the script has open at the command being validated. Null before the first 'open'.</summary>
    public string? CurrentPage { get; internal set; }

    private readonly List<string?> _tabNames = new() { null };
    private readonly List<string?> _tabPages = new() { null };

    /// <summary>Browser tabs the script has opened at the command being validated (S34-T01); a script starts with one.</summary>
    public int TabCount => _tabNames.Count;

    /// <summary>The tab the script works in, from 0.</summary>
    public int ActiveTab { get; private set; }

    /// <summary>The 0-based index of a tab named by its number (from 1) or its name; -1 when there is none.</summary>
    public int FindTab(string token) =>
        int.TryParse(token, out var number)
            ? number >= 1 && number <= TabCount ? number - 1 : -1
            : _tabNames.FindIndex(n => string.Equals(n, token, StringComparison.OrdinalIgnoreCase));

    internal void ResetTabs()
    {
        _tabNames.Clear();
        _tabNames.Add(null);
        _tabPages.Clear();
        _tabPages.Add(null);
        ActiveTab = 0;
    }

    /// <summary>A new blank tab becomes the active one; the page the script stood on stays with the tab it left.</summary>
    internal void AddTab(string? name)
    {
        _tabPages[ActiveTab] = CurrentPage;
        _tabNames.Add(name);
        _tabPages.Add(null);
        ActiveTab = _tabNames.Count - 1;
        CurrentPage = null;
    }

    internal void SwitchTab(int index)
    {
        _tabPages[ActiveTab] = CurrentPage;
        ActiveTab = index;
        CurrentPage = _tabPages[index];
    }

    /// <summary>Whether the environment allows <c># dev-only</c> cases (<c>AllowDevOnly</c>).</summary>
    public bool AllowDevOnly { get; init; }

    /// <summary>Folder <c>upload</c> files are checked in; null skips the check of the file (unit tests).</summary>
    public string? TestDataDirectory { get; init; }

    /// <summary>Processes a script may start, keyed by schema name. Empty when the processes directory is absent.</summary>
    public IReadOnlyDictionary<string, ProcessDefinition> Processes { get; init; } =
        new Dictionary<string, ProcessDefinition>(StringComparer.OrdinalIgnoreCase);

    /// <summary>Process the script last started at the command being validated. Null before the first 'start'.</summary>
    public string? CurrentProcess { get; internal set; }

    /// <summary>Whether a 'use' has been seen already.</summary>
    public bool UserDeclared { get; internal set; }

    /// <summary>
    /// The <c>$name</c> values defined by the lines validated so far. A name is checked here; its value
    /// exists only at run time.
    /// </summary>
    public ISet<string> Variables { get; } = new HashSet<string>(StringComparer.Ordinal);

    /// <summary>
    /// The case's header directives (<c># writes</c>, <c># ac: AC-02</c>), read by
    /// <see cref="Execution.ScriptParser.Directives"/>; keys lower case, a bare directive has an empty value.
    /// </summary>
    public IReadOnlyDictionary<string, string> Directives { get; init; } =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// Resolves an element code against the current page, producing the message the author needs
    /// when it fails: no page open, or the code is unknown on this page.
    /// </summary>
    public bool TryResolve(string code, out ResolvedTarget target, out string error)
    {
        target = null!;
        error = string.Empty;

        if (string.IsNullOrWhiteSpace(CurrentPage))
        {
            error = "no page is open; use 'open <page>' before addressing '" + code + "'";
            return false;
        }

        if (!Catalog.TryGetElement(CurrentPage, code, out var entry))
        {
            var codes = Catalog.CodesOnPage(CurrentPage);
            error = "element '" + code + "' is not configured on page '" + CurrentPage + "'. Known there: " +
                    (codes.Count == 0 ? "(none)" : string.Join(", ", codes)) +
                    ". To add a control the page file lacks: 'pages.py from-schema <package> <page>' or 'analyse --include-hidden'";
            return false;
        }

        target = new ResolvedTarget(code, entry);
        return true;
    }
}
