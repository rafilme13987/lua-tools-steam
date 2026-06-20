import os
import sys
import time

try:
    import questionary
    from rich.console import Console
    from rich.panel import Panel
    from PyQt6.QtCore import QUrl, QTimer, QEventLoop, pyqtSignal
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineUrlRequestInterceptor, QWebEnginePage
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    print("Missing dependencies. Run: pip install rich questionary PyQt6 PyQt6-WebEngine")
    sys.exit(1)

# Suppress harmless Chromium engine logs (like Bluetooth adapter failures)
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-logging --log-level=3"

console = Console()
AUTH_DIR = os.path.join(os.getcwd(), ".luatools_auth_qt")

class DiscordInterceptor(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        url = info.requestUrl().toString()
        if url.startswith("discord://"):
            # Block the browser from navigating or showing a security prompt
            info.block(True)
            # Launch natively via OS
            try:
                os.startfile(url)
            except Exception:
                pass

class AutoFetcher(QWebEngineView):
    finished = pyqtSignal()
    
    def __init__(self, app_id, parent=None):
        super().__init__(parent)
        self.app_id = app_id
        
        # Setup Persistent Profile
        self.profile = QWebEngineProfile("LuaToolsProfile", self)
        self.profile.setPersistentStoragePath(AUTH_DIR)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        
        # Setup Interceptor
        self.interceptor = DiscordInterceptor(self)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        
        # Setup Downloader
        self.profile.downloadRequested.connect(self.on_download_requested)
        
        # Apply Profile to Page
        new_page = QWebEnginePage(self.profile, self)
        self.setPage(new_page)
        
        # We start the automation state machine once the initial load finishes
        self.page().loadFinished.connect(self.start_automation)
        
        self.load(QUrl("https://lua.tools/"))
        
        # Track how many times we saw "LOGIN" to debounce React state delays
        self.login_seen_count = 0
        
        self.automation_started = False
        
        # Setup animated status
        from rich.status import Status
        self.cli_status = Status("[magenta]Initializing engine...", spinner="dots")
        self.cli_status.start()
        
        # By default, we hide the window (Phantom mode)
        self.hide()
        
    def cleanup_and_finish(self):
        self.cli_status.stop()
        # Clean up Qt objects to prevent 'Expect troubles!' warning
        if self.page():
            self.page().deleteLater()
        self.deleteLater()
        self.finished.emit()
        
    def update_status(self, text):
        self.cli_status.update(f"[cyan]{text}[/cyan]")
        
    def execute_js_sync(self, script):
        """Execute JS synchronously using a local event loop."""
        loop = QEventLoop()
        result_holder = []
        
        def callback(res):
            result_holder.append(res)
            loop.quit()
            
        self.page().runJavaScript(script, callback)
        loop.exec()
        return result_holder[0] if result_holder else None

    def start_automation(self, ok):
        if not ok:
            self.cli_status.stop()
            console.print("[bold red][-] Failed to load lua.tools[/bold red]")
            self.cleanup_and_finish()
            return
            
        if self.automation_started:
            return
            
        self.automation_started = True
        self.update_status(f"Verifying search for App ID: {self.app_id}...")
        
        # Start state machine
        QTimer.singleShot(2000, self.step_check_login)

    def step_check_login(self):
        # Fill search input
        js_fill = f"""
        (function() {{
            let input = document.querySelector("input[placeholder*='search']");
            if (input) {{
                let lastValue = input.value;
                input.value = '{self.app_id}';
                let event = new Event('input', {{ bubbles: true }});
                event.simulated = true;
                let tracker = input._valueTracker;
                if (tracker) {{ tracker.setValue(lastValue); }}
                input.dispatchEvent(event);
                return true;
            }}
            return false;
        }})()
        """
        self.execute_js_sync(js_fill)
        
        QTimer.singleShot(2000, self.step_wait_for_card)
        
    def step_wait_for_card(self):
        js_check_buttons = """
        (function() {{
            let btns = Array.from(document.querySelectorAll("button"));
            let loginBtn = btns.find(b => b.textContent.includes("Login to Fetch Manifest"));
            let fetchBtn = btns.find(b => b.textContent.includes("Fetch Manifest") || b.textContent.includes("Fetch DLC"));
            if (loginBtn) return "LOGIN";
            if (fetchBtn) return "FETCH";
            return "WAIT";
        }})()
        """
        
        status = self.execute_js_sync(js_check_buttons)
        
        if status == "LOGIN":
            self.login_seen_count += 1
            if self.login_seen_count >= 3:
                self.cli_status.stop()
                console.print(Panel.fit("[bold yellow]Authentication Required[/bold yellow]\n[white]Showing browser. Please log in via Discord.\nThe popup is automatically accepted![/white]"))
                self.show()
                self.cli_status.start()
                self.update_status("Waiting for Discord authentication...")
                QTimer.singleShot(2000, self.step_wait_for_login_success)
            else:
                QTimer.singleShot(1000, self.step_wait_for_card)
        elif status == "FETCH":
            self.step_click_fetch()
        else:
            QTimer.singleShot(1000, self.step_wait_for_card)

    def step_wait_for_login_success(self):
        js_check = """
        (function() {{
            let btns = Array.from(document.querySelectorAll("button"));
            let fetchBtn = btns.find(b => b.textContent.includes("Fetch Manifest") || b.textContent.includes("Fetch DLC"));
            return !!fetchBtn;
        }})()
        """
        success = self.execute_js_sync(js_check)
        if success:
            self.cli_status.stop()
            console.print("[bold green][+] Authenticated successfully![/bold green]")
            self.cli_status.start()
            self.hide() # Go back to phantom mode
            
            # Re-fill just in case navigation cleared it
            js_fill = f"""
            (function() {{
                let input = document.querySelector("input[placeholder*='search']");
                if (input) {{
                    let lastValue = input.value;
                    input.value = '{self.app_id}';
                    let event = new Event('input', {{ bubbles: true }});
                    let tracker = input._valueTracker;
                    if (tracker) {{ tracker.setValue(lastValue); }}
                    input.dispatchEvent(event);
                }}
            }})()
            """
            self.execute_js_sync(js_fill)
            self.update_status("Reloading game card...")
            QTimer.singleShot(1000, self.step_click_fetch)
        else:
            QTimer.singleShot(1000, self.step_wait_for_login_success)

    def step_click_fetch(self):
        self.update_status(f"Fetching manifest for {self.app_id}...")
        js_click_fetch = """
        (function() {{
            let btns = Array.from(document.querySelectorAll("button"));
            let fetchBtn = btns.find(b => b.textContent.includes("Fetch Manifest") || b.textContent.includes("Fetch DLC"));
            if (fetchBtn) {
                fetchBtn.click();
                return true;
            }
            return false;
        }})()
        """
        self.execute_js_sync(js_click_fetch)
        self.update_status("Waiting for mirrors to resolve...")
        QTimer.singleShot(1000, self.step_wait_for_mirrors)
        
    def step_wait_for_mirrors(self):
        js_click_dl = """
        (function() {{
            let btns = Array.from(document.querySelectorAll("button"));
            let dlBtn = btns.find(b => b.textContent === 'Download');
            if (dlBtn) {
                dlBtn.click();
                return true;
            }
            return false;
        }})()
        """
        clicked = self.execute_js_sync(js_click_dl)
        if clicked:
            self.update_status("Downloading payload...")
            # The downloadRequested signal will catch it
        else:
            QTimer.singleShot(1000, self.step_wait_for_mirrors)
            
    def on_download_requested(self, download):
        file_name = download.suggestedFileName()
        download_path = os.path.join(os.getcwd(), file_name)
        download.setDownloadDirectory(os.getcwd())
        download.setDownloadFileName(file_name)
        
        def state_changed(state):
            if getattr(state, "name", "") == "DownloadCompleted" or state == 2:
                self.cli_status.stop()
                console.print(Panel.fit(
                    f"[bold green]Payload Downloaded Successfully![/bold green]\n\n[bold white]Saved to: {download_path}[/bold white]",
                    title="Bypass Success",
                    border_style="green"
                ))
                self.cleanup_and_finish()
                
        download.stateChanged.connect(state_changed)
        download.accept()


def main():
    console.print(Panel.fit(
        "[bold cyan]Lua.tools Auto-Fetcher (PyQt6 Engine)[/bold cyan]\n"
        "[dim]Cracked-2m96 Operator Mode[/dim]",
        border_style="cyan"
    ))
    
    # Initialize QApplication once
    app = QApplication.instance() or QApplication(sys.argv)
    
    while True:
        target = questionary.text("Target Steam App ID (or 'exit' to quit):").ask()
        if not target or target.strip().lower() == 'exit':
            break

        target = target.strip()
        if not target.isdigit():
            console.print("[bold red][!] Invalid App ID. Must be numeric.[/bold red]")
            continue
        
        console.print("[dim][*] Launching QtWebEngine (Phantom Mode)...[/dim]")
        fetcher = AutoFetcher(target)
        
        # Block and run Qt event loop just for this fetcher
        loop = QEventLoop()
        fetcher.finished.connect(loop.quit)
        loop.exec()
        
        console.print("\n[dim]Ready for next target.[/dim]")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[dim]Aborted by operator.[/dim]")
        sys.exit(0)
