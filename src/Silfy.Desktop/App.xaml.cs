using System.IO;
using System.Threading;
using System.Windows;
using System.Windows.Forms;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Silfy.Application.Commands;
using Silfy.Core.Commands;
using Silfy.Core.Voice;
using Silfy.Desktop.ViewModels;
using Silfy.Infrastructure.Commands;
using Silfy.Infrastructure.Voice;

namespace Silfy.Desktop;

public partial class App : System.Windows.Application
{
    private const string MutexName = "Local\\Silfy.Desktop.SingleInstance.v1";
    private Mutex? _mutex;
    private bool _ownsMutex;
    private IHost? _host;
    private NotifyIcon? _tray;
    private bool _allowExit;

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        _mutex = new Mutex(true, MutexName, out var createdNew);
        if (!createdNew)
        {
            _mutex.Dispose();
            _mutex = null;
            Shutdown();
            return;
        }
        _ownsMutex = true;

        var projectRoot = Environment.GetEnvironmentVariable("SILFY_ROOT") ??
            Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", ".."));
        var pythonRoot = Path.Combine(projectRoot, "python");
        var pythonExe = Environment.GetEnvironmentVariable("SILFY_PYTHON") ?? "py";
        _host = Host.CreateDefaultBuilder()
            .ConfigureServices(services =>
            {
                services.AddSingleton<IVoiceEngineClient>(_ => new JsonLinesVoiceEngineClient(pythonExe, pythonRoot));
                services.AddSingleton<ICommandHandler, GetTimeCommandHandler>();
                services.AddSingleton<ICommandHandler, OpenYoutubeCommandHandler>();
                services.AddSingleton<ICommandDispatcher, CommandDispatcher>();
                services.AddSingleton<MainViewModel>();
                services.AddSingleton<MainWindow>();
            }).Build();
        await _host.StartAsync();
        var window = _host.Services.GetRequiredService<MainWindow>();
        MainWindow = window;
        window.Show();
        CreateTrayIcon(window);
    }

    private void CreateTrayIcon(MainWindow window)
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add("Открыть Silfy", null, (_, _) =>
        {
            window.Show();
            window.WindowState = WindowState.Normal;
            window.Activate();
        });
        menu.Items.Add("Начать прослушивание", null, async (_, _) => await window.StartListeningFromTrayAsync());
        menu.Items.Add("Остановить прослушивание", null, async (_, _) => await window.StopListeningFromTrayAsync());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Полностью завершить", null, async (_, _) => await ExitAsync());
        _tray = new NotifyIcon
        {
            Text = "Silfy",
            Icon = System.Drawing.SystemIcons.Application,
            ContextMenuStrip = menu,
            Visible = true
        };
        _tray.DoubleClick += (_, _) =>
        {
            window.Show();
            window.WindowState = WindowState.Normal;
            window.Activate();
        };
    }

    public async Task ExitAsync()
    {
        _allowExit = true;
        _tray?.Dispose();
        _tray = null;
        if (_host is not null)
        {
            await _host.StopAsync(TimeSpan.FromSeconds(5));
            if (_host is IAsyncDisposable asyncDisposable)
            {
                await asyncDisposable.DisposeAsync().ConfigureAwait(false);
            }
        }
        Shutdown();
    }

    public bool AllowExit => _allowExit;

    protected override void OnExit(ExitEventArgs e)
    {
        _tray?.Dispose();
        if (_ownsMutex) _mutex?.ReleaseMutex();
        _mutex?.Dispose();
        base.OnExit(e);
    }
}
