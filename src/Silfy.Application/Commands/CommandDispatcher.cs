using Silfy.Core.Commands;

namespace Silfy.Application.Commands;

public sealed class CommandDispatcher(IEnumerable<ICommandHandler> handlers) : ICommandDispatcher
{
    private readonly IReadOnlyList<ICommandHandler> _handlers = handlers.ToArray();

    public async Task<CommandResult> DispatchAsync(string utterance, CancellationToken cancellationToken = default)
    {
        var normalized = Normalize(utterance);
        if (normalized.Length == 0)
            return CommandResult.Fail("Я не расслышала команду.");

        var candidates = _handlers
            .SelectMany(handler => handler.Phrases.Select(phrase => (Handler: handler, Phrase: Normalize(phrase))))
            .Where(item => item.Phrase.Length > 0 &&
                           (normalized == item.Phrase || normalized.StartsWith(item.Phrase + " ", StringComparison.Ordinal)))
            .OrderByDescending(item => item.Phrase.Length)
            .ToArray();

        if (candidates.Length == 0)
            return CommandResult.Fail("Пока не знаю такую команду.");

        var best = candidates[0];
        if (candidates.Length > 1 && candidates[1].Phrase.Length == best.Phrase.Length &&
            candidates[1].Handler.Id != best.Handler.Id)
            return CommandResult.Fail("Команда неоднозначна. Сформулируйте её точнее.");

        // Fail closed until an explicit confirmation/authorization service is wired in.
        // A newly registered destructive handler must never become executable by default.
        if (best.Handler.RequiredPermission != CommandPermission.Basic)
            return CommandResult.Fail("Для этой команды пока не настроено подтверждение или разрешение.");

        try
        {
            return await best.Handler.HandleAsync(utterance, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch
        {
            return CommandResult.Fail("Не удалось выполнить команду. Подробности записаны в журнал.");
        }
    }

    private static string Normalize(string value) => string.Join(' ',
        value.Trim().ToLowerInvariant().Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
}
