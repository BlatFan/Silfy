using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text.Json;
using Silfy.Core.Voice;

namespace Silfy.Infrastructure.Voice;

public sealed class JsonLinesVoiceEngineClient : IVoiceEngineClient
{
    private readonly string _pythonExecutable;
    private readonly string _pythonRoot;
    private readonly TimeSpan _requestTimeout;
    private readonly ConcurrentDictionary<string, TaskCompletionSource<JsonElement>> _pending = new();
    private readonly SemaphoreSlim _writeLock = new(1, 1);
    private Process? _process;
    private Task? _stdoutTask;
    private Task? _stderrTask;

    public event EventHandler<VoiceEvent>? EventReceived;
    public bool IsRunning => _process is { HasExited: false };

    public JsonLinesVoiceEngineClient(string pythonExecutable, string pythonRoot,
        TimeSpan? requestTimeout = null)
    {
        _pythonExecutable = pythonExecutable;
        _pythonRoot = Path.GetFullPath(pythonRoot);
        _requestTimeout = requestTimeout ?? TimeSpan.FromSeconds(30);
    }

    public Task StartAsync(CancellationToken cancellationToken = default)
    {
        if (IsRunning) return Task.CompletedTask;
        if (!Directory.Exists(_pythonRoot))
            throw new DirectoryNotFoundException($"Python directory not found: {_pythonRoot}");

        var start = new ProcessStartInfo
        {
            FileName = _pythonExecutable,
            WorkingDirectory = _pythonRoot,
            UseShellExecute = false,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };
        if (Path.GetFileNameWithoutExtension(_pythonExecutable).Equals("py", StringComparison.OrdinalIgnoreCase))
            start.ArgumentList.Add("-3.15");
        start.ArgumentList.Add("-m");
        start.ArgumentList.Add("voice_engine");
        start.Environment["PYTHONPATH"] = _pythonRoot;
        start.Environment["SILFY_ROOT"] = Directory.GetParent(_pythonRoot)?.FullName ?? _pythonRoot;

        _process = new Process { StartInfo = start, EnableRaisingEvents = true };
        if (!_process.Start()) throw new InvalidOperationException("Python voice process did not start.");
        _stdoutTask = ReadStdoutAsync(_process, cancellationToken);
        _stderrTask = ReadStderrAsync(_process, cancellationToken);
        return Task.CompletedTask;
    }

    public async Task<JsonElement> RequestAsync(string command, object? payload = null,
        CancellationToken cancellationToken = default)
    {
        if (!IsRunning) await StartAsync(cancellationToken).ConfigureAwait(false);
        var id = Guid.NewGuid().ToString("N");
        var completion = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        if (!_pending.TryAdd(id, completion)) throw new InvalidOperationException("Request ID collision.");
        var message = JsonSerializer.Serialize(new { id, command, payload = payload ?? new { } });

        try
        {
            await _writeLock.WaitAsync(cancellationToken).ConfigureAwait(false);
            try
            {
                await _process!.StandardInput.WriteLineAsync(message.AsMemory(), cancellationToken).ConfigureAwait(false);
                await _process.StandardInput.FlushAsync(cancellationToken).ConfigureAwait(false);
            }
            finally { _writeLock.Release(); }

            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(_requestTimeout);
            return await completion.Task.WaitAsync(timeout.Token).ConfigureAwait(false);
        }
        finally { _pending.TryRemove(id, out _); }
    }

    private async Task ReadStdoutAsync(Process process, CancellationToken cancellationToken)
    {
        try
        {
            while (!process.HasExited && !cancellationToken.IsCancellationRequested)
            {
                var line = await process.StandardOutput.ReadLineAsync(cancellationToken).ConfigureAwait(false);
                if (line is null) break;
                using var document = JsonDocument.Parse(line);
                var root = document.RootElement;
                if (root.TryGetProperty("type", out var type) && type.GetString() == "event")
                {
                    var eventName = root.GetProperty("event").GetString() ?? "unknown";
                    var data = root.TryGetProperty("data", out var dataElement) ? dataElement.Clone() : default;
                    EventReceived?.Invoke(this, new VoiceEvent(eventName, data));
                    continue;
                }
                if (root.TryGetProperty("id", out var idElement) &&
                    _pending.TryGetValue(idElement.GetString() ?? string.Empty, out var waiter))
                {
                    if (root.TryGetProperty("ok", out var ok) && ok.GetBoolean())
                        waiter.TrySetResult(root.TryGetProperty("data", out var data) ? data.Clone() : default);
                    else
                        waiter.TrySetException(new InvalidOperationException(
                            root.TryGetProperty("error", out var error) && error.TryGetProperty("message", out var text)
                                ? text.GetString() ?? "Python request failed" : "Python request failed"));
                }
            }
            var exitError = new EndOfStreamException("Python voice process closed its protocol output.");
            foreach (var waiter in _pending.Values) waiter.TrySetException(exitError);
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            foreach (var waiter in _pending.Values) waiter.TrySetException(ex);
        }
    }

    private static async Task ReadStderrAsync(Process process, CancellationToken cancellationToken)
    {
        try
        {
            while (!process.HasExited && !cancellationToken.IsCancellationRequested)
            {
                var line = await process.StandardError.ReadLineAsync(cancellationToken).ConfigureAwait(false);
                if (line is null) break;
                System.Diagnostics.Trace.WriteLine($"[Silfy Voice] {line}");
            }
        }
        catch (OperationCanceledException) { }
    }

    public async ValueTask DisposeAsync()
    {
        try
        {
            if (IsRunning)
            {
                using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(3));
                try { await RequestAsync("shutdown", cancellationToken: cts.Token).ConfigureAwait(false); }
                catch { }
                if (!(_process?.HasExited ?? true)) _process!.Kill(entireProcessTree: true);
            }
        }
        finally
        {
            _process?.Dispose();
            _process = null;
            _writeLock.Dispose();
        }
    }
}
