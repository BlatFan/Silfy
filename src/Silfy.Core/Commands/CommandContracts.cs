namespace Silfy.Core.Commands;

public enum CommandPermission
{
    Basic,
    Elevated,
    Destructive
}

public sealed record CommandResult(bool Success, string Message, string? Speech = null)
{
    public static CommandResult Ok(string message, string? speech = null) => new(true, message, speech ?? message);
    public static CommandResult Fail(string message) => new(false, message, message);
}

public interface ICommandHandler
{
    string Id { get; }
    string Description { get; }
    IReadOnlyCollection<string> Phrases { get; }
    CommandPermission RequiredPermission { get; }
    Task<CommandResult> HandleAsync(string utterance, CancellationToken cancellationToken);
}

public interface ICommandDispatcher
{
    Task<CommandResult> DispatchAsync(string utterance, CancellationToken cancellationToken = default);
}
