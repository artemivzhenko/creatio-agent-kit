using CreatioAutoTests.Configuration;
using CreatioAutoTests.Frontend;
using CreatioAutoTests.Validation;
using Microsoft.Playwright;

namespace CreatioAutoTests.Execution;

/// <summary>
/// The seam between commands and everything stateful: the logged in user, the open page and the
/// factory that turns a resolved target into a live element. Commands never touch Playwright
/// directly except through the page this exposes.
/// </summary>
public interface IExecutionSession
{
    /// <summary>Runtime timeouts and failure-continuation settings that commands honor.</summary>
    RunSettings Settings { get; }

    /// <summary>Current static page and element catalog from which commands materialize targets.</summary>
    ElementCatalog Catalog { get; }

    /// <summary>Named scalar values available for command argument expansion.</summary>
    IReadOnlyDictionary<string, string> StaticValues { get; }

    /// <summary>Configured business-object workflows used by the <c>create</c> command.</summary>
    IReadOnlyDictionary<string, ObjectDefinition> Objects { get; }

    /// <summary>User selected by the last 'use', or null before it runs.</summary>
    string? CurrentUser { get; }

    /// <summary>Page opened by the last 'open' or 'create', or null before that.</summary>
    string? CurrentPage { get; }

    /// <summary>Switches the active user. Sessions are cached, so repeat calls are cheap.</summary>
    Task UseUserAsync(string username, CancellationToken cancellationToken = default);

    /// <summary>
    /// Opens a configured page, optionally an existing record, and waits for Creatio to settle.
    /// </summary>
    Task OpenPageAsync(string pageName, string? recordId, CancellationToken cancellationToken = default);

    /// <summary>
    /// Rebinds the current browser page to another configured page without navigating. Used after
    /// Creatio itself navigates, for example when the New button opens a form.
    /// </summary>
    Task AdoptPageAsync(string pageName, CancellationToken cancellationToken = default);

    /// <summary>
    /// Navigates to a raw path under the base URL, without it having to be a configured page.
    /// Used by 'analyse', which exists precisely to produce that configuration.
    /// </summary>
    Task NavigateAsync(string path, CancellationToken cancellationToken = default);

    /// <summary>Opens a blank tab of the same browser context (cookies and session shared) and makes it the active one.</summary>
    Task NewTabAsync(string? name, CancellationToken cancellationToken = default);

    /// <summary>Moves the current tab to a configured page through the Shell address, without loading the application again.</summary>
    Task NavigatePageAsync(string pageName, string? recordId, CancellationToken cancellationToken = default);

    /// <summary>Called by the executor after a line that changes the page (set, clear, click, answer, upload).</summary>
    void MarkChange();

    /// <summary>When the last such line finished (UTC); <see cref="DateTime.MinValue"/> before the first.</summary>
    DateTime LastChangeUtc { get; }

    /// <summary>Called by the executor as each line begins; 'check-process' reads when the line before it began.</summary>
    void MarkLineStart();

    /// <summary>When the line before the current one began (UTC); the start of the case for the first line.</summary>
    DateTime PreviousLineStartedUtc { get; }

    /// <summary>The SQL channel of the dev-only commands (clio), or null when the environment names none.</summary>
    Session.IDevSql? DevSql { get; }

    /// <summary>One line per dev-only action (<c>seed</c>, <c>fire-timer</c>); the report prints them.</summary>
    IList<string> DevNotes { get; }

    /// <summary>When the case began (UTC).</summary>
    DateTime CaseStartedUtc { get; }

    /// <summary>Name of the case this session runs (the snapshots and the trace are named after it).</summary>
    string CaseName { get; }

    /// <summary>Number (from 1) of the browser tab the case works in.</summary>
    int ActiveTab { get; }

    /// <summary>Makes another open tab the active one, by number (from 1) or name; every tab stays open until the case ends.</summary>
    Task SwitchTabAsync(string numberOrName, CancellationToken cancellationToken = default);

    /// <summary>The open Playwright page of the active tab, or an error explaining that nothing is open yet.</summary>
    IPage RequirePage();

    /// <summary>Creates the live element for a target the validator resolved earlier.</summary>
    IUiElement Materialize(ResolvedTarget target);

    /// <summary>Processes a script may start, keyed by schema name.</summary>
    IReadOnlyDictionary<string, ProcessDefinition> Processes { get; }

    /// <summary>What the last 'start' produced, or null before one ran.</summary>
    Session.ProcessRunResult? LastProcess { get; }

    /// <summary>
    /// Starts a configured process over the process engine service, asking for every output
    /// parameter back, and remembers the outcome for 'check-result'. Needs no page.
    /// </summary>
    Task<Session.ProcessRunResult> StartProcessAsync(
        string process,
        IReadOnlyDictionary<string, string> values,
        CancellationToken cancellationToken = default);

    /// <summary>Whether at least one record of the object matches the OData filter.</summary>
    Task<bool> RecordExistsAsync(string entity, string filter, CancellationToken cancellationToken = default);

    /// <summary>
    /// The case's <c>$name</c> values: insert aliases and remembered values, one table. Substituted into
    /// unquoted arguments before a line runs (<see cref="CaseVariables.Substitute"/>).
    /// </summary>
    IDictionary<string, string> Variables { get; }

    /// <summary>
    /// Inserts a record over OData as the case's backend user and returns its Id. Unless <paramref name="keep"/>
    /// is set, the record joins the cleanup list and is deleted when the case ends, passed or not.
    /// </summary>
    Task<string> InsertRecordAsync(string entity, IReadOnlyList<RecordAssignment> values, bool keep, CancellationToken cancellationToken = default);

    /// <summary>Changes columns of one record over OData.</summary>
    Task UpdateRecordAsync(string entity, string id, IReadOnlyList<RecordAssignment> values, CancellationToken cancellationToken = default);

    /// <summary>Deletes one record over OData; a record the case inserted leaves the cleanup list.</summary>
    Task DeleteRecordAsync(string entity, string id, CancellationToken cancellationToken = default);

    /// <summary>Reads at most <paramref name="top"/> rows of the filtered set, the selected columns as text.</summary>
    Task<IReadOnlyList<IReadOnlyDictionary<string, string>>> QueryRecordsAsync(
        string entity, IReadOnlyList<string> select, string filter, int top, CancellationToken cancellationToken = default);

    /// <summary>Counts the records matching the filter.</summary>
    Task<long> CountRecordsAsync(string entity, string filter, CancellationToken cancellationToken = default);

    /// <summary>
    /// Deletes what the case inserted and did not delete, newest first. Returns one line per record that
    /// could not be deleted; the list is empty afterwards either way.
    /// </summary>
    Task<IReadOnlyList<string>> CleanupAsync(CancellationToken cancellationToken = default);

    /// <summary>Browser console errors and uncaught page errors seen since the case started.</summary>
    IReadOnlyList<string> ConsoleErrors { get; }

    /// <summary>Every console message, page error and failed or 4xx / 5xx request since the case started, timestamped.</summary>
    IReadOnlyList<string> ConsoleLog { get; }

    /// <summary>Every request the pages of the case finished or failed, with its duration.</summary>
    IReadOnlyList<NetworkEntry> Network { get; }

    /// <summary>Saves a screenshot of the open page to <paramref name="path"/>; false when no page is open.</summary>
    Task<bool> ScreenshotAsync(string path);
}
