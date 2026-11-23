using System.Diagnostics;
using CreatioAutoTests.Validation;
using CreatioAutoTests.Commands;
using CreatioAutoTests.Frontend;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace CreatioAutoTests.Execution;

/// <summary>
/// The second of the two passes. Runs an already validated plan: nothing is parsed, resolved or
/// type checked here, so this layer only deals with what the browser actually does.
/// </summary>
public sealed class CommandExecutor
{
    private readonly IServiceProvider _services;
    private readonly ILoggerFactory _loggerFactory;
    private readonly ILogger<CommandExecutor> _logger;

    /// <summary>Initializes command activation and logger creation for executing validated plan steps.</summary>
    public CommandExecutor(IServiceProvider services, ILoggerFactory loggerFactory)
    {
        _services = services ?? throw new ArgumentNullException(nameof(services));
        _loggerFactory = loggerFactory ?? throw new ArgumentNullException(nameof(loggerFactory));
        _logger = loggerFactory.CreateLogger<CommandExecutor>();
    }

    /// <summary>
    /// Executes every step of the plan. Stops at the first failure unless the run settings ask for
    /// the whole case to be attempted.
    /// </summary>
    public async Task<TestCaseResult> ExecuteAsync(
        ExecutionPlan plan,
        IExecutionSession session,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(plan);
        ArgumentNullException.ThrowIfNull(session);

        var result = new TestCaseResult
        {
            Name = plan.TestName,
            FilePath = plan.FilePath,
            ValidationIssues = plan.Issues,
            AcceptanceCriterion = plan.AcceptanceCriterion,
        };

        if (!plan.IsValid)
        {
            return result;
        }

        var stopwatch = Stopwatch.StartNew();

        try
        {
            foreach (var step in plan.Steps)
            {
                var outcome = await ExecuteStepAsync(step, session, cancellationToken).ConfigureAwait(false);
                result.Outcomes.Add(outcome);

                if (outcome.Success)
                {
                    continue;
                }

                result.Screenshot ??= await TakeScreenshotAsync(session, plan.TestName).ConfigureAwait(false);

                // A case that writes stops at its first failure: a later Save must not land after a step that did not happen.
                if (!session.Settings.ContinueOnFailure || plan.StopOnFailure)
                {
                    break;
                }
            }
        }
        finally
        {
            // The records the case inserted go whatever happened; a record that stays is a broken run, not a pass.
            var left = await session.CleanupAsync(CancellationToken.None).ConfigureAwait(false);
            if (left.Count > 0)
            {
                result.RunError = "cleanup left " + left.Count + " record(s): " + string.Join("; ", left);
                _logger.LogError("{Name}: {Error}", plan.TestName, result.RunError);
            }

            if (session.Settings.CaptureConsole)
            {
                result.ConsoleErrors = session.ConsoleErrors.ToArray();
            }

            result.DevNotes = session.DevNotes.ToArray();
            result.ConsoleLog = session.ConsoleLog.ToArray();
            result.Network = session.Network.ToArray();
        }

        stopwatch.Stop();
        result.Duration = stopwatch.Elapsed;

        return result;
    }

    // The page as it was when the command failed, before a later command or the cleanup changes it.
    private async Task<string?> TakeScreenshotAsync(IExecutionSession session, string caseName)
    {
        var safe = string.Concat(caseName.Select(c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c));
        var path = Path.GetFullPath(Path.Combine(session.Settings.ReportsDirectory, "screenshots", safe + ".png"));
        try
        {
            return await session.ScreenshotAsync(path).ConfigureAwait(false) ? path : null;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _logger.LogWarning("{Name}: no screenshot: {Message}", caseName, ex.Message);
            return null;
        }
    }

    /// <summary>Lines after which a page rule may still be hiding or showing controls: 'check X not exists' waits for it (S11-T13).</summary>
    private static readonly HashSet<string> ChangingKeywords = new(new[] { "set", "clear", "click", "answer", "upload" }, StringComparer.OrdinalIgnoreCase);

    private async Task<CommandOutcome> ExecuteStepAsync(
        ExecutionStep step,
        IExecutionSession session,
        CancellationToken cancellationToken)
    {
        var stopwatch = Stopwatch.StartNew();

        try
        {
            // A run of 'check-process' lines all look back from the same moment: the line before the action they are about.
            if (!string.Equals(step.Registration.Keyword, "check-process", StringComparison.OrdinalIgnoreCase))
            {
                session.MarkLineStart();
            }

            var tabBefore = session.ActiveTabCode;
            await EnsureTabsAsync(step, session, cancellationToken).ConfigureAwait(false);
            if (session.ActiveTabCode != tabBefore)
            {
                _logger.LogDebug("line {Line}: opened tab {Tab} for the elements of the line.", step.Command.LineNumber, session.ActiveTabCode);
            }

            var elements = MaterializeTargets(step, session);
            var logger = _loggerFactory.CreateLogger(step.Registration.ImplementationType);
            var context = new CommandContext(step, elements, session, logger);

            var command = (ICommand)ActivatorUtilities.GetServiceOrCreateInstance(
                _services,
                step.Registration.ImplementationType);

            _logger.LogDebug("line {Line}: {Text}", step.Command.LineNumber, step.Command.RawText);

            await command.ExecuteAsync(context, cancellationToken).ConfigureAwait(false);

            TrackTab(step, session);
            if (ChangingKeywords.Contains(step.Registration.Keyword))
            {
                session.MarkChange();
            }

            stopwatch.Stop();
            return new CommandOutcome(step, true, null, stopwatch.Elapsed);
        }
        catch (CommandFailedException ex)
        {
            stopwatch.Stop();
            _logger.LogWarning("line {Line} failed: {Message}", step.Command.LineNumber, ex.Message);
            return new CommandOutcome(step, false, ex.Message, stopwatch.Elapsed);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            stopwatch.Stop();
            _logger.LogError(ex, "line {Line} threw.", step.Command.LineNumber);
            return new CommandOutcome(step, false, ex.GetType().Name + ": " + ex.Message, stopwatch.Elapsed);
        }
    }

    private static bool IsTabControl(ResolvedTarget target) =>
        target.Definition.Type is "Tab" or "TabPanel" or "ToggleTab";

    /// <summary>
    /// A command on an element that lies on another tab of the page opens that tab first, so a case no longer starts with 'click GeneralInfoTab'
    /// (S11-T06). Validation inserts nothing; the page's tab is unknown after 'open', so the first command clicks its tab once.
    /// </summary>
    internal static async Task EnsureTabsAsync(ExecutionStep step, IExecutionSession session, CancellationToken cancellationToken)
    {
        foreach (var target in step.Targets)
        {
            var code = target.Definition.Tab;
            if (string.IsNullOrWhiteSpace(code) || IsTabControl(target) || string.Equals(code, session.ActiveTabCode, StringComparison.Ordinal))
            {
                continue;
            }

            if (!session.Catalog.TryGetElement(target.Page, code, out var entry) || entry.Definition.Type != "Tab")
            {
                continue;
            }

            if (session.Materialize(new ResolvedTarget(code, entry)) is IClickable tab)
            {
                await tab.ClickAsync(cancellationToken).ConfigureAwait(false);
                session.ActiveTabCode = code;
            }
        }
    }

    /// <summary>What the line left open: a clicked tab is known, a tab panel set by caption is not.</summary>
    private static void TrackTab(ExecutionStep step, IExecutionSession session)
    {
        if (step.Targets.Count == 0)
        {
            return;
        }

        var keyword = step.Registration.Keyword;
        if (keyword.Equals("click", StringComparison.OrdinalIgnoreCase) && step.Targets[0].Definition.Type == "Tab")
        {
            session.ActiveTabCode = step.Targets[0].Code;
        }
        else if (keyword.Equals("set", StringComparison.OrdinalIgnoreCase) && step.Targets[0].Definition.Type is "TabPanel" or "ToggleTab")
        {
            session.ActiveTabCode = null;
        }
    }

    /// <summary>Turns the targets the validator resolved into live elements on the open page.</summary>
    private static IReadOnlyList<IUiElement> MaterializeTargets(ExecutionStep step, IExecutionSession session)
    {
        if (step.Targets.Count == 0)
        {
            return Array.Empty<IUiElement>();
        }

        var elements = new IUiElement[step.Targets.Count];
        for (var i = 0; i < step.Targets.Count; i++)
        {
            elements[i] = session.Materialize(step.Targets[i]);
        }

        return elements;
    }
}
