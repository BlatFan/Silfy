using System.Windows;
using Silfy.Desktop.ViewModels;

namespace Silfy.Desktop;

public partial class MainWindow : Window
{
    private readonly MainViewModel _viewModel;

    public MainWindow(MainViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        DataContext = viewModel;
    }

    protected override void OnClosing(System.ComponentModel.CancelEventArgs e)
    {
        if (global::System.Windows.Application.Current is App app && !app.AllowExit)
        {
            e.Cancel = true;
            Hide();
            return;
        }
        base.OnClosing(e);
    }

    public Task StartListeningFromTrayAsync() => _viewModel.StartListeningAsync();
    public Task StopListeningFromTrayAsync() => _viewModel.StopListeningAsync();
}
