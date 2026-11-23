using System.Reflection;
using CreatioAutoTests.Frontend.Fields;
using Microsoft.Playwright;

namespace CreatioAutoTests.Tests;

/// <summary>The first-run flake of 'set' on a lookup: the row found in the unfiltered list is gone by the click.</summary>
[TestFixture]
public sealed class LookupPickTests
{
    public class Nothing : DispatchProxy
    {
        protected override object? Invoke(MethodInfo? targetMethod, object?[]? args) => null;
    }

    private static readonly ILocator Option = DispatchProxy.Create<ILocator, Nothing>();

    [Test]
    public async Task A_click_that_misses_resolves_the_option_again_and_succeeds()
    {
        var resolved = 0;
        var clicks = 0;
        var picked = await LookupField.PickAsync(
            () => { resolved++; return Task.FromResult<ILocator?>(Option); },
            _ => ++clicks == 1 ? throw new System.TimeoutException("Nth(3) is gone") : Task.CompletedTask);

        Assert.That(picked, Is.True);
        Assert.That((resolved, clicks), Is.EqualTo((2, 2)));
    }

    [Test]
    public async Task An_option_that_is_not_offered_is_not_picked_and_a_click_that_always_misses_gives_up_after_the_attempts()
    {
        Assert.That(await LookupField.PickAsync(() => Task.FromResult<ILocator?>(null), _ => Task.CompletedTask), Is.False);

        var clicks = 0;
        Assert.ThrowsAsync<System.TimeoutException>(() => LookupField.PickAsync(
            () => Task.FromResult<ILocator?>(Option), _ => { clicks++; throw new System.TimeoutException("gone"); }, attempts: 3));
        Assert.That(clicks, Is.EqualTo(3));
    }
}
