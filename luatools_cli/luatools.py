import os
import sys
import time

try:
    import prompt_toolkit
    from rich.console import Console
    from rich.panel import Panel
    from PyQt6.QtCore import QUrl, QTimer, QEventLoop, pyqtSignal
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineUrlRequestInterceptor, QWebEnginePage
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except ImportError as e:
    print(f"[!] Dependency Error: {e}")
    print("Missing dependencies. Please run start.bat to install requirements automatically.")
    sys.exit(1)

# Suppress harmless Chromium engine logs (like Bluetooth adapter failures)
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-logging --log-level=3"

console = Console()
AUTH_DIR = os.path.join(os.getcwd(), ".luatools_auth_qt")

# --- Live Steam Search Completer ---
from prompt_toolkit.completion import Completer, Completion, ThreadedCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import CompleteStyle
import urllib.request
import urllib.parse
import json

# Fix urllib slowness on Windows (Disable Proxy Auto-Discovery)
proxy_handler = urllib.request.ProxyHandler({})
opener = urllib.request.build_opener(proxy_handler)
urllib.request.install_opener(opener)

_STEAM_SEARCH_CACHE = {}

class SteamCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text.strip()
        if len(text) < 3:
            return
            
        if text in _STEAM_SEARCH_CACHE:
            data = _STEAM_SEARCH_CACHE[text]
        else:
            try:
                url = f"https://store.steampowered.com/api/storesearch/?term={urllib.parse.quote(text)}&l=english&cc=US"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                resp = urllib.request.urlopen(req, timeout=1.5).read().decode()
                data = json.loads(resp)
                _STEAM_SEARCH_CACHE[text] = data
            except Exception:
                return
            
        for item in data.get('items', []):
                name = item['name']
                appid = str(item['id'])
                
                # Highlight the matching part in cyan (SteamDB style)
                lower_name = name.lower()
                lower_text = text.lower()
                
                if lower_text in lower_name:
                    idx = lower_name.find(lower_text)
                    matched_part = name[idx:idx+len(text)]
                    before = name[:idx]
                    after = name[idx+len(text):]
                    display_html = HTML(f'{before}<style fg="#3b82f6"><b>{matched_part}</b></style>{after}')
                else:
                    display_html = HTML(name)

                yield Completion(
                    text=f"{name} (App ID: {appid})",
                    start_position=-len(document.text),
                    display=display_html,
                    display_meta=HTML(f'<style fg="#555555">App ID: {appid}</style>')
                )

class QuietWebEnginePage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        # Suppress all JS console messages to keep the terminal clean
        pass

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
        new_page = QuietWebEnginePage(self.profile, self)
        self.setPage(new_page)
        
        # We start the automation state machine once the initial load finishes
        self.page().loadFinished.connect(self.start_automation)
        self.urlChanged.connect(self.handle_url_changed)
        
        self.load(QUrl("https://lua.tools/"))
        
        # Track how many times we saw "LOGIN" to debounce React state delays
        self.login_seen_count = 0
        
        self.automation_started = False
        
        # Setup animated status
        from rich.status import Status
        self.cli_status = Status("[#3b82f6]Initializing engine...[/]", spinner="dots", spinner_style="#3b82f6")
        self.cli_status.start()
        
        # By default, we hide the window (Phantom mode)
        self.hide()
        
    def createWindow(self, windowType):
        # Force all new tabs/windows (like Discord login) to open in this same window
        return self
        
    def handle_url_changed(self, url):
        # Instantly hide the popup once Discord redirects back to lua.tools
        url_str = url.toString()
        if "discord.com" not in url_str and self.isVisible():
            self.hide()
            
    def cleanup_and_finish(self):
        self.cli_status.stop()
        # Clean up Qt objects to prevent 'Expect troubles!' warning
        if self.page():
            self.page().deleteLater()
        self.deleteLater()
        self.finished.emit()
        
    def update_status(self, text):
        self.cli_status.update(f"[dim]{text}[/dim]")
        
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
            console.print("[bold red]▌ Failed to load lua.tools[/bold red]")
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
                
                # Auto-click Login so the user doesn't have to search for the button
                js_click_login = """
                (function() {
                    let btns = Array.from(document.querySelectorAll("button"));
                    let loginBtn = btns.find(b => b.textContent.includes("Login"));
                    if (loginBtn) loginBtn.click();
                })();
                """
                self.execute_js_sync(js_click_login)
                
                # Format window as a neat OAuth popup rather than a raw browser
                self.setWindowTitle("Discord Secure Authentication")
                self.resize(450, 750)
                
                console.print(Panel.fit("[bold white]Showing browser. Please log in via Discord.\nThe popup is automatically accepted![/bold white]", title="[bold #3b82f6]Authentication Required[/]", border_style="#3b82f6"))
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
        (function() {
            let btns = Array.from(document.querySelectorAll("button"));
            let loginBtn = btns.find(b => b.textContent.includes("Login"));
            let fetchBtn = btns.find(b => b.textContent.includes("Fetch Manifest") || b.textContent.includes("Fetch DLC"));
            return !!fetchBtn && !loginBtn;
        })()
        """
        success = self.execute_js_sync(js_check)
        if success:
            self.cli_status.stop()
            console.print("[bold #3b82f6]>[/bold #3b82f6] [bold white]Authenticated successfully![/bold white]")
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
        (function() {
            let btns = Array.from(document.querySelectorAll("button"));
            let loginBtn = btns.find(b => b.textContent.includes("Login"));
            let fetchBtn = btns.find(b => b.textContent.includes("Fetch Manifest") || b.textContent.includes("Fetch DLC"));
            if (fetchBtn && !loginBtn) {
                fetchBtn.click();
                return true;
            }
            return false;
        })()
        """
        clicked = self.execute_js_sync(js_click_fetch)
        if clicked:
            self.update_status("Waiting for mirrors to resolve...")
            QTimer.singleShot(1000, self.step_wait_for_mirrors)
        else:
            QTimer.singleShot(1000, self.step_click_fetch)
            
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
        target_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lua")
        os.makedirs(target_dir, exist_ok=True)
        
        download_path = os.path.join(target_dir, file_name)
        download.setDownloadDirectory(target_dir)
        download.setDownloadFileName(file_name)
        
        def state_changed(state):
            if getattr(state, "name", "") == "DownloadCompleted" or state == 2:
                self.cli_status.stop()
                console.print()
                console.print(Panel.fit(
                    f"[bold white]Payload Downloaded Successfully![/bold white]\n[dim]Saved to: {download_path}[/dim]",
                    title="[bold #3b82f6]Bypass Success[/]",
                    border_style="#3b82f6"
                ))
                self.cleanup_and_finish()
                
        download.stateChanged.connect(state_changed)
        download.accept()


def main():
    # Initialize QApplication once
    app = QApplication.instance() or QApplication(sys.argv)
    
    while True:
        ascii_art = """[bold white]
██╗     ██╗   ██╗ █████╗     ████████╗ ██████╗  ██████╗ ██╗     ███████╗
██║     ██║   ██║██╔══██╗    ╚══██╔══╝██╔═══██╗██╔═══██╗██║     ██╔════╝
██║     ██║   ██║███████║       ██║   ██║   ██║██║   ██║██║     ███████╗
██║     ██║   ██║██╔══██║       ██║   ██║   ██║██║   ██║██║     ╚════██║
███████╗╚██████╔╝██║  ██║       ██║   ╚██████╔╝╚██████╔╝███████╗███████║
╚══════╝ ╚═════╝ ╚═╝  ╚═╝       ╚═╝    ╚═════╝  ╚═════╝ ╚══════╝╚══════╝
[/bold white]"""
        from rich.align import Align
        from rich.panel import Panel
        import random
        import threading
        import io
        import shutil
        from rich.console import Console
        from prompt_toolkit.formatted_text import ANSI, HTML, to_formatted_text
        from prompt_toolkit.application.current import get_app
        
        menu_text = """
 [bold white]1.[/bold white] Direct Download  (Fetch via exact Steam App ID)
 [bold white]2.[/bold white] Smart Search     (Live API search & resolution)
 
 [bold white]3.[/bold white] Clear Auth Cache (Force new Discord Login)
 [bold white]4.[/bold white] Exit System      (Terminate Session)
"""

        dummy_console = Console(file=io.StringIO(), force_terminal=True, color_system="truecolor")
        
        def run_glitched_prompt(prompt_html, include_menu=False, **prompt_kwargs):
            app_ref = [None]
            glitch_active = [True]
            
            def glitch_worker():
                while glitch_active[0]:
                    time.sleep(0.08)
                    if app_ref[0] and app_ref[0].is_running:
                        try:
                            app_ref[0].invalidate()
                        except Exception:
                            pass
                            
            def render_screen():
                app_ref[0] = get_app()
                
                dummy_console.width = shutil.get_terminal_size().columns
                dummy_console.file.seek(0)
                dummy_console.file.truncate(0)
                
                glitch_ascii = ""
                in_tag = False
                for char in ascii_art:
                    if char == '[': in_tag = True
                    if in_tag:
                        glitch_ascii += char
                        if char == ']': in_tag = False
                        continue
                    if char not in ["\n", " "] and random.random() < 0.02:
                        glitch_ascii += " "
                    else:
                        glitch_ascii += char
                        
                dummy_console.print("\n" * 2)
                dummy_console.print(Align.center(glitch_ascii))
                dummy_console.print("\n" * 2)
                
                if include_menu:
                    dummy_console.print(Align.center(Panel.fit(
                        menu_text,
                        title="[bold #3b82f6]Operation Node[/]",
                        border_style="#3b82f6",
                        padding=(0, 4)
                    )))
                    dummy_console.print()
                
                ansi_str = dummy_console.file.getvalue()
                return to_formatted_text(ANSI(ansi_str)) + to_formatted_text(HTML(prompt_html))

            t = threading.Thread(target=glitch_worker, daemon=True)
            t.start()
            
            os.system('cls' if os.name == 'nt' else 'clear')
            
            try:
                result = prompt(render_screen, **prompt_kwargs)
            finally:
                glitch_active[0] = False
                
            return result

        # Shared prompt_toolkit style
        opencode_style = Style.from_dict({
            '': 'fg:#ffffff',
            'completion-menu': 'bg:#1e1e1e fg:#cccccc',
            'completion-menu.completion': 'bg:#1e1e1e fg:#cccccc',
            'completion-menu.completion.current': 'bg:#2d2d2d fg:#ffffff',
            'scrollbar.background': 'bg:#1e1e1e',
            'scrollbar.button': 'bg:#555555',
        })
        action = run_glitched_prompt(
            '<style fg="#3b82f6">▌ </style><style fg="#8f98a0">Select Option [1-4]: </style>',
            include_menu=True,
            style=opencode_style
        ).strip()
        
        if not action or action == "4":
            from prompt_toolkit.shortcuts import yes_no_dialog
            from prompt_toolkit.styles import Style as PtStyle
            
            dialog_style = PtStyle.from_dict({
                'dialog':             'bg:#1e1e1e fg:#ffffff',
                'dialog frame.label': 'bg:#1e1e1e fg:#3b82f6 bold',
                'dialog.body':        'bg:#1e1e1e fg:#cccccc',
                'dialog shadow':      'bg:default', # Removed black shadow properly
                'button':             'bg:#2d2d2d fg:#ffffff',
                'button.focused':     'bg:#3b82f6 fg:#ffffff bold',
            })
            
            result = yes_no_dialog(
                title="System Exit",
                text="\n       Are you sure you want to go offline?       \n",
                style=dialog_style
            ).run()
            
            if result:
                break
            else:
                continue
            
        target = None
        
        console.print()
        
        if action == "3":
            if os.path.exists(AUTH_DIR):
                console.print(f"[bold #3b82f6]>[/bold #3b82f6] [bold white]Initiating secure wipe of auth profile...[/bold white]\n")
                files_to_delete = []
                for root, dirs, files in os.walk(AUTH_DIR):
                    for file in files:
                        files_to_delete.append(os.path.join(root, file))
                
                for file_path in files_to_delete:
                    try:
                        os.remove(file_path)
                        console.print(f"  [#3b82f6]WIPE[/] [white]{file_path}[/white]")
                        time.sleep(0.02)
                    except Exception:
                        pass
                        
                import shutil
                shutil.rmtree(AUTH_DIR, ignore_errors=True)
                console.print("\n[bold #3b82f6]>[/bold #3b82f6] [bold white]Auth cache cleared successfully. You will need to log in again.[/bold white]")
            else:
                console.print("[white]No auth cache found. System is clean.[/white]")
            time.sleep(2.5)
            continue
            
        if action == "1":
            selection = run_glitched_prompt(
                '<style fg="#3b82f6">▌ </style><style fg="#8f98a0">Target Steam App ID: </style>',
                style=opencode_style
            )
            if not selection:
                continue
            selection = selection.strip()
            if not selection.isdigit():
                console.print("\n[bold red][!] Invalid App ID. Must be numeric.[/bold red]")
                time.sleep(1.5)
                continue
            target = selection
            
        elif action == "2":
            prompt_html = '<style fg="#ffffff">Type a game name to see live suggestions (requires 3 chars). Use Up/Down, then Enter.</style>\n\n<style fg="#3b82f6">▌ </style><style fg="#8f98a0">Game Search: </style>'
            selection = run_glitched_prompt(
                prompt_html,
                completer=ThreadedCompleter(SteamCompleter()), 
                complete_while_typing=True,
                complete_style=CompleteStyle.COLUMN,
                style=opencode_style
            )
            if not selection or "App ID: " not in selection:
                console.print("\n[bold red][!] Invalid selection. Please select a valid game.[/bold red]")
                time.sleep(1.5)
                continue
            try:
                target = selection.split("App ID: ")[1].replace(")", "")
            except Exception:
                continue
                
        if target:
            console.print(f"\n[#3b82f6]▌[/] [white]Launching QtWebEngine for App ID {target} (Phantom Mode)...[/white]")
            fetcher = AutoFetcher(target)
            
            # Block and run Qt event loop just for this fetcher
            loop = QEventLoop()
            fetcher.finished.connect(loop.quit)
            loop.exec()
            
            console.print("\n[white]Ready for next target.[/white]")
            input("Press Enter to return to the main menu...")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[dim]Aborted by operator.[/dim]")
        sys.exit(0)
