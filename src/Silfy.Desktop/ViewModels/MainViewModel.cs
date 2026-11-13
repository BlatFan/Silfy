using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Windows;
using System.Windows.Input;
using Silfy.Core.Commands;
using Silfy.Core.Voice;

namespace Silfy.Desktop.ViewModels;

public sealed class MainViewModel : INotifyPropertyChanged
{
    private readonly IVoiceEngineClient _voice;
    private readonly ICommandDispatcher _commands;
    private string _statusText = "Не запущена";
    private string _engineText = "Ожидание запуска";
    private string _microphoneText = "Не активен";
    private string _lastRecognizedText = "Пока нет распознанных команд";
    private string _operationText = "Ожидание";
    private string _errorText = "";
    private bool _busy;

    public event PropertyChangedEventHandler? PropertyChanged;
    public string StatusText { get => _statusText; private set => Set(ref _statusText, value); }
    public string EngineText { get => _engineText; private set => Set(ref _engineText, value); }
    public string MicrophoneText { get => _microphoneText; private set => Set(ref _microphoneText, value); }
    public string LastRecognizedText { get => _lastRecognizedText; private set => Set(ref _lastRecognizedText, value); }
    public string OperationText { get => _operationText; private set => Set(ref _operationText, value); }
    public string ErrorText { get => _errorText; private set => Set(ref _errorText, value); }
    public System.Windows.Media.Brush StatusBrush => _statusText == "Слушаю" ?
        System.Windows.Media.Brushes.LightGreen : System.Windows.Media.Brushes.MediumPurple;
    public bool CanStart => !_busy && _statusText != "Слушаю";
    public bool CanStop => !_busy && _statusText == "Слушаю";
    public ICommand StartCommand { get; }
    public ICommand StopCommand { get; }

    public MainViewModel(IVoiceEngineClient voice, ICommandDispatcher commands)
    {
        _voice = voice;
        _commands = commands;
        _voice.EventReceived += OnVoiceEvent;
        StartCommand = new AsyncCommand(StartListeningAsync, () => CanStart);
        StopCommand = new AsyncCommand(StopListeningAsync, () => CanStop);
    }

    public async Task StartListeningAsync()
    {
        if (_busy) return;
        _busy = true; RefreshCommands(); ErrorText = "";
        try
        {
            await _voice.StartAsync();
            var result = await _voice.RequestAsync("start_listening");
            EngineText = "Работает"; MicrophoneText = "Активен";
            StatusText = "Слушаю"; OperationText = "Ожидаю ключевую фразу «Сильфи»";
        }
        catch (Exception ex)
        {
            StatusText = "Ошибка"; EngineText = "Не готов"; MicrophoneText = "Недоступен";
            ErrorText = ex.Message; OperationText = "Проверьте модели и конфигурацию голосового движка.";
        }
        finally { _busy = false; RefreshCommands(); }
    }

    public async Task StopListeningAsync()
    {
        if (_busy) return;
        _busy = true; RefreshCommands();
        try
        {
            if (_voice.IsRunning) await _voice.RequestAsync("stop_listening");
            StatusText = "Остановлена"; MicrophoneText = "Не активен";
            OperationText = "Прослушивание выключено пользователем.";
        }
        catch (Exception ex) { ErrorText = ex.Message; }
        finally { _busy = false; RefreshCommands(); }
    }

    private void OnVoiceEvent(object? sender, VoiceEvent e)
    {
        _ = ProcessVoiceEventAsync(e);
    }

    private async Task ProcessVoiceEventAsync(VoiceEvent e)
    {
        try
        {
            if (e.Event == "recognized" && e.Data.TryGetProperty("text", out var text))
            {
                var recognizedText = text.GetString() ?? "";
                await global::System.Windows.Application.Current.Dispatcher.InvokeAsync(() =>
                {
                    LastRecognizedText = recognizedText;
                    OperationText = "Обрабатываю команду";
                }).Task.ConfigureAwait(false);

                var result = await _commands.DispatchAsync(recognizedText).ConfigureAwait(false);
                await global::System.Windows.Application.Current.Dispatcher.InvokeAsync(() =>
                {
                    OperationText = result.Message;
                    RefreshCommands();
                }).Task.ConfigureAwait(false);

                if (!string.IsNullOrWhiteSpace(result.Speech) && _voice.IsRunning)
                {
                    await _voice.RequestAsync("speak", new { text = result.Speech }).ConfigureAwait(false);
                }
                return;
            }

            await global::System.Windows.Application.Current.Dispatcher.InvokeAsync(() =>
            {
                if (e.Event == "state" && e.Data.TryGetProperty("state", out var state))
                {
                    var value = state.GetString() ?? "unknown";
                    OperationText = value switch
                    {
                        "listening" => "Ожидаю ключевую фразу «Сильфи»",
                        "thinking" => "Ключевая фраза обнаружена, распознаю команду",
                        "speaking" => "Сильфи отвечает",
                        "error" => "Ошибка голосового движка",
                        _ => value
                    };
                }
                else if (e.Event == "error" && e.Data.TryGetProperty("message", out var message))
                {
                    ErrorText = message.GetString() ?? "Ошибка голосового движка";
                    StatusText = "Ошибка";
                }
                RefreshCommands();
            }).Task.ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            try
            {
                await global::System.Windows.Application.Current.Dispatcher.InvokeAsync(() => ErrorText = ex.Message).Task.ConfigureAwait(false);
            }
            catch { /* Desktop may already be shutting down. */ }
        }
    }

    private void RefreshCommands()
    {
        OnPropertyChanged(nameof(CanStart)); OnPropertyChanged(nameof(CanStop));
        OnPropertyChanged(nameof(StatusBrush));
        (StartCommand as AsyncCommand)?.RaiseCanExecuteChanged();
        (StopCommand as AsyncCommand)?.RaiseCanExecuteChanged();
    }

    private void Set<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return;
        field = value; OnPropertyChanged(propertyName);
    }
    private void OnPropertyChanged(string? propertyName) => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

    private sealed class AsyncCommand(Func<Task> execute, Func<bool> canExecute) : ICommand
    {
        public event EventHandler? CanExecuteChanged;
        public bool CanExecute(object? parameter) => canExecute();
        public async void Execute(object? parameter) => await execute();
        public void RaiseCanExecuteChanged() => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
    }
}
