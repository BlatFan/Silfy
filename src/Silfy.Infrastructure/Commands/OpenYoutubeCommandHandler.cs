using System.Diagnostics;
using Silfy.Core.Commands;

namespace Silfy.Infrastructure.Commands;

public sealed class OpenYoutubeCommandHandler : ICommandHandler
{
    public string Id => "web.open-youtube";
    public string Description => "Открыть YouTube в браузере";
    public IReadOnlyCollection<string> Phrases => ["открой youtube", "открой ютуб"];
    public CommandPermission RequiredPermission => CommandPermission.Basic;

    public Task<CommandResult> HandleAsync(string utterance, CancellationToken cancellationToken)
    {
        Process.Start(new ProcessStartInfo("https://www.youtube.com") { UseShellExecute = true });
        return Task.FromResult(CommandResult.Ok("Открываю YouTube."));
    }
}
