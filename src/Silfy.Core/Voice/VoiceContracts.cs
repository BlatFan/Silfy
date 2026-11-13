namespace Silfy.Core.Voice;

public sealed class VoiceEvent(string eventName, System.Text.Json.JsonElement data) : EventArgs
{
    public string Event { get; } = eventName;
    public System.Text.Json.JsonElement Data { get; } = data;
}

public interface IVoiceEngineClient : IAsyncDisposable
{
    event EventHandler<VoiceEvent>? EventReceived;
    bool IsRunning { get; }
    Task StartAsync(CancellationToken cancellationToken = default);
    Task<System.Text.Json.JsonElement> RequestAsync(string command, object? payload = null,
        CancellationToken cancellationToken = default);
}
