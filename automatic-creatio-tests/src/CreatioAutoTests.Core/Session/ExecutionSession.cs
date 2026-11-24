using CreatioAutoTests.Configuration;
using CreatioAutoTests.Execution;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Frontend.Registry;
using CreatioAutoTests.Frontend.Runtime;
using CreatioAutoTests.Validation;
using Microsoft.Extensions.Logging;
using Microsoft.Playwright;

namespace CreatioAutoTests.Session;

/// <summary>
/// Runtime state of a single test case: who is logged in, which page is open, and how a resolved
/// target becomes a live element. One instance per test case, so cases cannot leak state into
/// each other, while browser contexts stay shared through the pool.
/// </summary>
public sealed class ExecutionSession : IExecutionSession, IAsyncDisposable
{
    private readonly BrowserSessionPool _pool;
    private readonly UiElementFactory _factory;
    private readonly CreatioODataClient _backend;
    private readonly ILogger<ExecutionSession> _logger;

    private readonly List<(string Entity, Guid Id)> _cleanup = new();
    private readonly List<string> _consoleErrors = new();
    private readonly List<string> _consoleLog = new();
    private readonly List<NetworkEntry> _network = new();
    private IBrowserContext? _traced;
    private string? _tracedUser;

    // One entry per browser tab of the case (S34-T01): 'open' and 'navigate' work in the active one, 'tab new' adds one.
    internal sealed class Tab
    {
        private IPage? _page;
        private string? _currentPage;

        // An element is a thin wrapper over lazy locators bound to this tab's page, so one per page and code serves every command
        // (S11-T10). Any change of the page or of the page the case treats as current drops them all: a locator of a closed page is stale.
        public readonly Dictionary<string, IUiElement> Elements = new(StringComparer.Ordinal);

        public IPage? Page
        {
            get => _page;
            set { _page = value; Elements.Clear(); }
        }

        public string? Name;

        public string? CurrentPage
        {
            get => _currentPage;
            set { _currentPage = value; Elements.Clear(); }
        }

        public string? ActiveCode;
        public int Ordinal;
    }

    private readonly List<Tab> _tabs = new();
    private int _active;
    private string? _currentUser;

    private Tab? CurrentTab => _tabs.Count > 0 ? _tabs[_active] : null;

    private IPage? _page => CurrentTab?.Page;

    /// <summary>Initializes isolated per-case state over shared authenticated browser contexts.</summary>
    public ExecutionSession(
        BrowserSessionPool pool,
        UiElementFactory factory,
        CreatioODataClient backend,
        ElementCatalog catalog,
        RunSettings settings,
        IReadOnlyDictionary<string, string> staticValues,
        IReadOnlyDictionary<string, ObjectDefinition> objects,
        IReadOnlyDictionary<string, ProcessDefinition> processes,
        ILogger<ExecutionSession> logger)
    {
        _pool = pool ?? throw new ArgumentNullException(nameof(pool));
        _factory = factory ?? throw new ArgumentNullException(nameof(factory));
        _backend = backend ?? throw new ArgumentNullException(nameof(backend));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));

        Catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
        Settings = settings ?? throw new ArgumentNullException(nameof(settings));
        StaticValues = staticValues ?? throw new ArgumentNullException(nameof(staticValues));
        Objects = objects ?? throw new ArgumentNullException(nameof(objects));
        Processes = processes ?? throw new ArgumentNullException(nameof(processes));
    }

    /// <summary>Name of the case this session runs: the trace file and the screenshot are named after it.</summary>
    public string CaseName { get; init; } = "case";

    /// <summary>The SQL channel of the dev-only commands, or null.</summary>
    public IDevSql? DevSql { get; init; }

    /// <summary>One line per dev-only action of the case.</summary>
    public IList<string> DevNotes { get; } = new List<string>();

    /// <summary>When the case began (UTC).</summary>
    public DateTime CaseStartedUtc { get; } = DateTime.UtcNow;

    private DateTime _lineStarted = DateTime.UtcNow;
    private DateTime _previousLineStarted = DateTime.UtcNow;

    /// <inheritdoc />
    public string? ActiveTabCode
    {
        get => CurrentTab?.ActiveCode;
        set
        {
            if (CurrentTab is { } tab)
            {
                tab.ActiveCode = value;
            }
        }
    }

    /// <summary>Records that a line just changed the page.</summary>
    public void MarkChange() => LastChangeUtc = DateTime.UtcNow;

    /// <summary>When the last changing line finished (UTC).</summary>
    public DateTime LastChangeUtc { get; private set; } = DateTime.MinValue;

    /// <summary>Records the start of the line about to run.</summary>
    public void MarkLineStart()
    {
        _previousLineStarted = _lineStarted;
        _lineStarted = DateTime.UtcNow;
    }

    /// <summary>When the line before the current one began (UTC); the session's creation for the first line.</summary>
    public DateTime PreviousLineStartedUtc => _previousLineStarted;

    /// <summary>Number (from 1) of the browser tab the case works in.</summary>
    public int ActiveTab => _tabs.Count == 0 ? 1 : _active + 1;

    /// <summary>Processes a script may start, from the processes directory.</summary>
    public IReadOnlyDictionary<string, ProcessDefinition> Processes { get; }

    /// <summary>Outcome of the last 'start' in this case.</summary>
    public ProcessRunResult? LastProcess { get; private set; }

    /// <summary>Starts the process over the engine service as the first configured user and keeps the result.</summary>
    public async Task<ProcessRunResult> StartProcessAsync(
        string process,
        IReadOnlyDictionary<string, string> values,
        CancellationToken cancellationToken = default)
    {
        if (!Processes.TryGetValue(process, out var definition))
        {
            throw new InvalidOperationException("Process '" + process + "' is not configured.");
        }

        var outputs = definition.Outputs.Select(p => p.Code).ToArray();
        LastProcess = await _backend.RunProcessAsync(process, values, outputs, cancellationToken).ConfigureAwait(false);
        return LastProcess;
    }

    /// <summary>Reads at most one row of the object with the filter over OData.</summary>
    public async Task<bool> RecordExistsAsync(string entity, string filter, CancellationToken cancellationToken = default)
    {
        var rows = await _backend.QueryAsync(entity, new[] { "Id" }, filter, top: 1, cancellationToken).ConfigureAwait(false);
        return rows.Count > 0;
    }

    /// <summary>The case's <c>$name</c> values.</summary>
    public IDictionary<string, string> Variables { get; } = new Dictionary<string, string>(StringComparer.Ordinal);

    /// <summary>Browser console errors and page errors of every page this case opened.</summary>
    public IReadOnlyList<string> ConsoleErrors => _consoleErrors;

    /// <summary>Every console message, page error, failed request and 4xx / 5xx response of every page this case opened, in order.</summary>
    public IReadOnlyList<string> ConsoleLog => _consoleLog;

    /// <summary>Inserts over OData; the record is deleted at the end of the case unless kept.</summary>
    public async Task<string> InsertRecordAsync(string entity, IReadOnlyList<RecordAssignment> values, bool keep, CancellationToken cancellationToken = default)
    {
        var id = await _backend.InsertAsync(entity, ODataValues.Body(values), cancellationToken).ConfigureAwait(false);
        if (!keep)
        {
            _cleanup.Add((entity, id));
        }

        _logger.LogDebug("Inserted {Entity} {Id}{Keep}.", entity, id, keep ? " (kept)" : string.Empty);
        return id.ToString();
    }

    /// <summary>Changes columns of one record over OData.</summary>
    public Task UpdateRecordAsync(string entity, string id, IReadOnlyList<RecordAssignment> values, CancellationToken cancellationToken = default) =>
        _backend.UpdateAsync(entity, ParseId(id), ODataValues.Body(values), cancellationToken);

    /// <summary>Deletes one record over OData and forgets it in the cleanup list.</summary>
    public async Task DeleteRecordAsync(string entity, string id, CancellationToken cancellationToken = default)
    {
        var guid = ParseId(id);
        await _backend.DeleteAsync(entity, guid, cancellationToken).ConfigureAwait(false);
        _cleanup.RemoveAll(r => r.Id == guid && string.Equals(r.Entity, entity, StringComparison.OrdinalIgnoreCase));
    }

    /// <summary>Reads the filtered rows, every selected column as text (a null as empty).</summary>
    public async Task<IReadOnlyList<IReadOnlyDictionary<string, string>>> QueryRecordsAsync(
        string entity, IReadOnlyList<string> select, string filter, int top, CancellationToken cancellationToken = default)
    {
        var rows = await _backend.QueryAsync(entity, select, filter, top, cancellationToken).ConfigureAwait(false);
        return rows.Select(row => (IReadOnlyDictionary<string, string>)select.ToDictionary(
            column => column,
            column => row.TryGetProperty(column, out var value) ? AsText(value) : string.Empty,
            StringComparer.OrdinalIgnoreCase)).ToArray();
    }

    /// <summary>Counts the records matching the filter over OData.</summary>
    public Task<long> CountRecordsAsync(string entity, string filter, CancellationToken cancellationToken = default) =>
        _backend.CountAsync(entity, filter, cancellationToken);

    /// <summary>Deletes the inserted records the case left, newest first; reports the ones that stayed.</summary>
    public async Task<IReadOnlyList<string>> CleanupAsync(CancellationToken cancellationToken = default)
    {
        var failures = new List<string>();
        for (var i = _cleanup.Count - 1; i >= 0; i--)
        {
            var (entity, id) = _cleanup[i];
            try
            {
                await _backend.DeleteAsync(entity, id, cancellationToken).ConfigureAwait(false);
                _logger.LogDebug("Cleanup deleted {Entity} {Id}.", entity, id);
                DevNotes.Add("cleanup: deleted " + entity + " " + id);
            }
            catch (Exception ex) when (ex is InvalidOperationException or HttpRequestException)
            {
                failures.Add(entity + " " + id + ": " + ex.Message);
            }
        }

        _cleanup.Clear();
        return failures;
    }

    private static Guid ParseId(string id) =>
        Guid.TryParse(id, out var guid) ? guid : throw new CommandFailedException("'" + id + "' is not a record id (a GUID).");

    private static string AsText(System.Text.Json.JsonElement value) => value.ValueKind switch
    {
        System.Text.Json.JsonValueKind.String => value.GetString() ?? string.Empty,
        System.Text.Json.JsonValueKind.Null or System.Text.Json.JsonValueKind.Undefined => string.Empty,
        System.Text.Json.JsonValueKind.True => "true",
        System.Text.Json.JsonValueKind.False => "false",
        _ => value.GetRawText(),
    };

    // Subscribed on every page the case opens, so 'check console' and the report see errors of all of them.
    private void Watch(IPage page, int ordinal)
    {
        page.Console += (_, message) =>
        {
            if (string.Equals(message.Type, "error", StringComparison.OrdinalIgnoreCase))
            {
                _consoleErrors.Add(message.Text);
            }

            var at = message.Location;
            Log(message.Type, message.Text + (string.IsNullOrEmpty(at) ? string.Empty : "  @ " + at), ordinal);
        };
        page.PageError += (_, error) =>
        {
            _consoleErrors.Add(error);
            Log("pageerror", error, ordinal);
        };
        page.RequestFailed += (_, request) =>
        {
            Log("requestfailed", request.Method + " " + request.Url + "  " + request.Failure, ordinal);
            AddNetwork(new NetworkEntry(request.Method, request.Url, 0, 0, request.Failure ?? "failed"));
        };
        page.RequestFinished += async (_, request) =>
        {
            try
            {
                var response = await request.ResponseAsync().ConfigureAwait(false);
                AddNetwork(new NetworkEntry(request.Method, request.Url, response?.Status ?? 0, (int)Math.Max(request.Timing.ResponseEnd, 0)));
            }
            catch (PlaywrightException)
            {
                // the page closed while the request was being read: it is not part of the case any more
            }
        };
        page.Response += (_, response) =>
        {
            if (response.Status >= 400)
            {
                Log("http " + response.Status, response.Request.Method + " " + response.Url, ordinal);
            }
        };
    }

    private void AddNetwork(NetworkEntry entry)
    {
        lock (_network)
        {
            _network.Add(entry);
        }
    }

    /// <summary>Every request the pages of the case finished or failed, with its duration.</summary>
    public IReadOnlyList<NetworkEntry> Network
    {
        get
        {
            lock (_network)
            {
                return _network.ToArray();
            }
        }
    }

    /// <summary>Saves a screenshot of the open page; false when no page is open.</summary>
    public async Task<bool> ScreenshotAsync(string path)
    {
        if (_page is null || _page.IsClosed)
        {
            return false;
        }

        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        await _page.ScreenshotAsync(new PageScreenshotOptions { Path = path }).ConfigureAwait(false);
        return true;
    }

    private bool _traceStarted;

    /// <summary>The current user's browser context, launching the browser and logging in on first use.</summary>
    private async Task<IBrowserContext> ContextAsync(CancellationToken cancellationToken)
    {
        var context = await _pool.GetContextAsync(_currentUser!, cancellationToken).ConfigureAwait(false);
        if (!_traceStarted)
        {
            _traceStarted = true;
            await StartTraceAsync(context, _currentUser!).ConfigureAwait(false);
        }

        return context;
    }

    // One trace chunk per (case, user): the context is shared by the cases of a run, the chunk is this case's part of it.
    private async Task StartTraceAsync(IBrowserContext context, string user)
    {
        if (!Settings.Trace)
        {
            return;
        }

        await context.Tracing.StartChunkAsync(new TracingStartChunkOptions { Title = CaseName }).ConfigureAwait(false);
        _traced = context;
        _tracedUser = user;
    }

    private async Task StopTraceAsync()
    {
        if (_traced is null)
        {
            return;
        }

        var safe = string.Concat((CaseName + "-" + _tracedUser).Select(c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c));
        var path = Path.GetFullPath(Path.Combine(Settings.ReportsDirectory, "traces", safe + ".zip"));
        var context = _traced;
        _traced = null;
        try
        {
            await context.Tracing.StopChunkAsync(new TracingStopChunkOptions { Path = path }).ConfigureAwait(false);
            _logger.LogInformation("Trace: {Path}", path);
        }
        catch (PlaywrightException ex)
        {
            _logger.LogWarning("No trace for {Case}: {Message}", CaseName, ex.Message);
        }
    }

    private void Log(string kind, string text, int ordinal)
    {
        // Once the case has several tabs, every line says which one it came from.
        _consoleLog.Add(DateTime.Now.ToString("HH:mm:ss.fff", System.Globalization.CultureInfo.InvariantCulture) + "  " +
                        (_tabs.Count > 1 ? "[tab " + ordinal + "] " : string.Empty) + kind + "  " + text);
    }

    /// <summary>Runtime timeouts and continuation behavior for this case.</summary>
    public RunSettings Settings { get; }

    /// <summary>Static catalog used to bind configured page controls to live elements.</summary>
    public ElementCatalog Catalog { get; }

    /// <summary>Named scalar values resolved by command arguments.</summary>
    public IReadOnlyDictionary<string, string> StaticValues { get; }

    /// <summary>Configured workflows used when creating business objects.</summary>
    public IReadOnlyDictionary<string, ObjectDefinition> Objects { get; }

    /// <summary>User whose browser context currently owns the open page, if one is selected.</summary>
    public string? CurrentUser => _currentUser;

    /// <summary>Configured page currently bound to the browser, or null for a raw analysis address.</summary>
    public string? CurrentPage
    {
        get => CurrentTab?.CurrentPage;
        private set
        {
            if (CurrentTab is { } tab)
            {
                tab.CurrentPage = value;
            }
        }
    }

    /// <summary>Browser tabs the case has open; one once a page is open.</summary>
    public int TabCount => _tabs.Count;

    /// <summary>Opens a blank tab in the user's context (cookies and session shared) and makes it the active one.</summary>
    public async Task NewTabAsync(string? name, CancellationToken cancellationToken = default)
    {
        if (_currentUser is null || _tabs.Count == 0)
        {
            throw new CommandFailedException("'tab new' needs an open page first: 'open <page>' runs before it.");
        }

        var tab = new Tab { Name = name, Ordinal = _tabs.Count + 1 };
        var context = await ContextAsync(cancellationToken).ConfigureAwait(false);
        await StartPageAsync(context, tab).ConfigureAwait(false);
        _tabs.Add(tab);
        _active = _tabs.Count - 1;
        await tab.Page!.BringToFrontAsync().ConfigureAwait(false);
        _logger.LogDebug("Tab {Ordinal} opened{Name}.", tab.Ordinal, name is null ? string.Empty : " as " + name);
    }

    /// <summary>Makes another tab the active one, by its number (from 1) or its name; the tabs stay open.</summary>
    public async Task SwitchTabAsync(string numberOrName, CancellationToken cancellationToken = default)
    {
        var index = int.TryParse(numberOrName, out var number)
            ? number - 1
            : _tabs.FindIndex(t => string.Equals(t.Name, numberOrName, StringComparison.OrdinalIgnoreCase));
        if (index < 0 || index >= _tabs.Count || _tabs[index].Page is null)
        {
            throw new CommandFailedException("there is no tab '" + numberOrName + "'; the case has " + _tabs.Count + " open.");
        }

        _active = index;
        await _tabs[index].Page!.BringToFrontAsync().ConfigureAwait(false);
    }

    private async Task StartPageAsync(IBrowserContext context, Tab tab)
    {
        var page = await context.NewPageAsync().ConfigureAwait(false);
        page.SetDefaultTimeout(Settings.ElementTimeoutMs);
        tab.Page = page;
        tab.ActiveCode = null;
        Watch(page, tab.Ordinal);
    }

    /// <summary>Switches to a user's shared authenticated context and discards the prior user's open page.</summary>
    public async Task UseUserAsync(string username, CancellationToken cancellationToken = default)
    {
        if (string.Equals(_currentUser, username, StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        // A page belongs to the previous user's context, so none of the tabs can survive the switch.
        await CloseAllTabsAsync().ConfigureAwait(false);
        await StopTraceAsync().ConfigureAwait(false);

        // No browser yet: a backend case only needs the name (its OData calls log in on their own); the first page that is opened asks for the context.
        _currentUser = username;
        _traceStarted = false;

        _logger.LogDebug("Session now runs as {User}.", username);
    }

    /// <summary>
    /// Opens a configured page and waits for both the loading overlay and Freedom UI's control count
    /// to settle. The explicit Playwright default timeout prevents missing sub-elements from using
    /// Playwright's longer 30-second default.
    /// </summary>
    public async Task OpenPageAsync(
        string pageName,
        string? recordId,
        CancellationToken cancellationToken = default)
    {
        if (_currentUser is null)
        {
            throw new InvalidOperationException("No user is selected; 'use' must run before a page is opened.");
        }

        if (!Catalog.TryGetPage(pageName, out var page))
        {
            throw new InvalidOperationException("Page '" + pageName + "' is not configured.");
        }

        // The page's generation decides how the framework waits for it to be built.
        var runtime = PageRuntimes.For(page);
        var url = runtime.BuildUrl(page.Url, recordId);

        await ClosePageAsync().ConfigureAwait(false);

        var context = await ContextAsync(cancellationToken).ConfigureAwait(false);
        await StartPageAsync(context, CurrentTab ?? AddFirstTab()).ConfigureAwait(false);

        await RequirePage().GotoAsync(url, new PageGotoOptions
        {
            WaitUntil = WaitUntilState.NetworkIdle,
            Timeout = Settings.PageLoadTimeoutMs
        }).ConfigureAwait(false);

        await runtime.WaitForReadyAsync(RequirePage(), page, Settings, _logger, cancellationToken).ConfigureAwait(false);

        CurrentPage = page.Name;
        _logger.LogDebug("Opened {Page} at {Url}.", page.Name, url);
    }

    /// <summary>
    /// Changes <c>location.hash</c> of the open page to the configured page's Shell address, so the application navigates itself
    /// (no reload; a marker set on <c>window</c> that survives proves it) and waits for the new page to be ready.
    /// </summary>
    public async Task NavigatePageAsync(string pageName, string? recordId, CancellationToken cancellationToken = default)
    {
        var browser = _page ?? throw new CommandFailedException("'navigate' needs a page open in this tab: 'open <page>' comes first.");
        if (!Catalog.TryGetPage(pageName, out var page))
        {
            throw new InvalidOperationException("Page '" + pageName + "' is not configured.");
        }

        var runtime = PageRuntimes.For(page);
        var url = runtime.BuildUrl(page.Url, recordId);
        var at = url.IndexOf('#');
        if (at < 0)
        {
            throw new CommandFailedException("page '" + pageName + "' has no Shell address (" + url + "): 'navigate' needs a '#' address; use 'open'.");
        }

        await browser.EvaluateAsync("hash => { window.__actNavigation = true; location.hash = hash; }", url[at..]).ConfigureAwait(false);
        await runtime.WaitForReadyAsync(browser, page, Settings, _logger, cancellationToken).ConfigureAwait(false);
        if (!await browser.EvaluateAsync<bool>("() => window.__actNavigation === true").ConfigureAwait(false))
        {
            _logger.LogWarning("'navigate {Page}' reloaded the application: the address was not a Shell hash change.", pageName);
        }

        CurrentPage = page.Name;
        ActiveTabCode = null;
        _logger.LogDebug("Navigated to {Page} through {Hash}.", page.Name, url[at..]);
    }

    /// <summary>Opens an unconfigured raw path for analysis and leaves no configured current page bound.</summary>
    public async Task NavigateAsync(string path, CancellationToken cancellationToken = default)
    {
        if (_currentUser is null)
        {
            throw new InvalidOperationException("No user is selected; 'use' must run before navigating.");
        }

        var url = path.StartsWith('/') ? path : "/" + path;

        await ClosePageAsync().ConfigureAwait(false);

        var context = await ContextAsync(cancellationToken).ConfigureAwait(false);
        await StartPageAsync(context, CurrentTab ?? AddFirstTab()).ConfigureAwait(false);

        await RequirePage().GotoAsync(url, new PageGotoOptions
        {
            WaitUntil = WaitUntilState.NetworkIdle,
            Timeout = Settings.PageLoadTimeoutMs
        }).ConfigureAwait(false);

        // No configured page, so the generation is read off the address itself.
        await PageRuntimes.ForAddress(url)
            .WaitForReadyAsync(RequirePage(), null, Settings, _logger, cancellationToken).ConfigureAwait(false);

        // The address is not a configured page, so there is no page name to report.
        CurrentPage = null;
        _logger.LogDebug("Navigated to {Url}.", url);
    }

    /// <summary>Rebinds the current page after Creatio navigates itself, without issuing another navigation.</summary>
    public async Task AdoptPageAsync(string pageName, CancellationToken cancellationToken = default)
    {
        if (_page is null)
        {
            throw new InvalidOperationException("Nothing is open, so there is no page to adopt.");
        }

        if (!Catalog.TryGetPage(pageName, out var page))
        {
            throw new InvalidOperationException("Page '" + pageName + "' is not configured.");
        }

        await PageRuntimes.For(page)
            .WaitForReadyAsync(_page, page, Settings, _logger, cancellationToken).ConfigureAwait(false);

        // Elements on no tab come first: a control on a closed tab is legitimately absent.
        var sample = Catalog.Entries
            .Where(e => string.Equals(e.Page, pageName, StringComparison.OrdinalIgnoreCase) && e.Supports(typeof(IExistable)))
            .OrderBy(e => string.IsNullOrWhiteSpace(e.Definition.Tab) ? 0 : 1)
            .Take(PageProbe.Sample)
            .ToArray();
        var probes = sample.Select(e => (IExistable)_factory.Create(e.Definition, page, _page, Settings)).ToArray();
        if (!await PageProbe.AnyPresentAsync(probes, Settings.PageCheckTimeoutMs, cancellationToken).ConfigureAwait(false))
        {
            throw new CommandFailedException(
                "the browser is not on '" + pageName + "': none of " + string.Join(", ", sample.Select(e => e.Code)) +
                " appeared within " + Settings.PageCheckTimeoutMs + " ms (" + _page.Url + ").");
        }

        CurrentPage = pageName;
        _logger.LogDebug("Current page is now treated as {Page} ({Url}).", pageName, _page.Url);
    }

    /// <summary>Returns the open Playwright page or explains that a command must open one first.</summary>
    public IPage RequirePage() =>
        _page ?? throw new InvalidOperationException("No page is open; 'open' must run first.");

    /// <summary>Creates a live element from a target that validation resolved statically.</summary>
    public IUiElement Materialize(ResolvedTarget target)
    {
        ArgumentNullException.ThrowIfNull(target);

        var tab = CurrentTab;
        var key = target.Definition.Page + "/" + target.Code;
        if (tab is not null && tab.Elements.TryGetValue(key, out var known))
        {
            return known;
        }

        Catalog.TryGetPage(target.Definition.Page, out var pageDefinition);
        var element = _factory.Create(target.Definition, pageDefinition, RequirePage(), Settings);
        if (tab is not null)
        {
            tab.Elements[key] = element;
        }

        return element;
    }

    private Tab AddFirstTab()
    {
        var tab = new Tab { Ordinal = 1 };
        _tabs.Add(tab);
        _active = 0;
        return tab;
    }

    // The page of the active tab: 'open' replaces it, the other tabs stay as they are.
    private async Task ClosePageAsync()
    {
        if (CurrentTab is not { } tab)
        {
            return;
        }

        await CloseAsync(tab).ConfigureAwait(false);
        tab.CurrentPage = null;
    }

    private async Task CloseAllTabsAsync()
    {
        foreach (var tab in _tabs)
        {
            await CloseAsync(tab).ConfigureAwait(false);
        }

        _tabs.Clear();
        _active = 0;
    }

    private async Task CloseAsync(Tab tab)
    {
        if (tab.Page is null)
        {
            return;
        }

        try
        {
            await tab.Page.CloseAsync().ConfigureAwait(false);
        }
        catch (PlaywrightException ex)
        {
            _logger.LogDebug(ex, "Closing the page failed.");
        }

        tab.Page = null;
    }

    /// <summary>Closes this test case's page while retaining shared contexts in the session pool.</summary>
    public async ValueTask DisposeAsync()
    {
        await CloseAllTabsAsync().ConfigureAwait(false);
        await StopTraceAsync().ConfigureAwait(false);
    }
}
