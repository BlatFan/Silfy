using Silfy.Core.Commands;

namespace Silfy.Infrastructure.Commands;

public sealed class GetTimeCommandHandler : ICommandHandler
{
    public string Id => "system.time";
    public string Description => "Сказать текущее локальное время";
    public IReadOnlyCollection<string> Phrases => ["который час", "скажи время", "время"];
    public CommandPermission RequiredPermission => CommandPermission.Basic;

    public Task<CommandResult> HandleAsync(string utterance, CancellationToken cancellationToken)
    {
        var value = DateTimeOffset.Now.ToString("HH:mm");
        return Task.FromResult(CommandResult.Ok($"Сейчас {value}.", $"Сейчас {value}"));
    }
}
