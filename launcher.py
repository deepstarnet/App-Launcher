import os
import sys
import pickle
import time

try:
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Gio', '2.0')
    from gi.repository import Gtk, Gdk, Gio, GLib
except Exception as e:
    print(f"Missing dependencies: {e}")
    sys.exit(1)

WINDOW_WIDTH  = 850
WINDOW_HEIGHT = 400
TOP_OFFSET    = 120
CACHE_FILE    = os.path.expanduser("~/.cache/launcher-apps.pkl")
CACHE_TTL     = 300  # секунд (5 минут)


def get_applications(use_cache=True):
    # Проверяем кэш
    if use_cache and os.path.exists(CACHE_FILE):
        age = time.time() - os.path.getmtime(CACHE_FILE)
        if age < CACHE_TTL:
            with open(CACHE_FILE, 'rb') as f:
                return pickle.load(f)

    apps = []
    seen = set()
    for app in Gio.AppInfo.get_all():
        if not app.should_show():
            continue
        name = app.get_name()
        if name in seen:
            continue
        seen.add(name)
        apps.append((name, app.get_id()))

    apps = sorted(apps, key=lambda x: x[0].lower())

    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(apps, f)

    return apps


def launch_app(app_id):
    app_info = Gio.DesktopAppInfo.new(app_id)
    if app_info:
        app_info.launch([], None)


class LauncherWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)

        self.all_apps = get_applications()
        self.filtered = self.all_apps[:]

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)

        self._build_ui()
        self._apply_css()

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect('key-pressed', self._on_key)
        self.add_controller(key_ctrl)

    def _build_ui(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(outer)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Search applications...")
        self.entry.add_css_class('search-entry')
        self.entry.set_margin_top(12)
        self.entry.set_margin_bottom(8)
        self.entry.set_margin_start(12)
        self.entry.set_margin_end(12)
        self.entry.connect('changed', self._on_search)
        self.entry.connect('activate', self._on_enter)
        outer.append(self.entry)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.add_css_class('sep')
        outer.append(sep)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_margin_top(4)
        scroll.set_margin_bottom(8)

        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class('app-list')
        self.listbox.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self.listbox.connect('row-activated', self._on_activate)
        scroll.set_child(self.listbox)
        outer.append(scroll)

        self._populate_list(self.all_apps)
        GLib.idle_add(self._select_first)

    def _populate_list(self, apps):
        while True:
            row = self.listbox.get_row_at_index(0)
            if row is None:
                break
            self.listbox.remove(row)

        for name, app_id in apps:
            row = Gtk.ListBoxRow()
            row.app_id = app_id
            row.add_css_class('app-row')
            label = Gtk.Label(label=name)
            label.set_halign(Gtk.Align.START)
            label.set_margin_start(16)
            label.set_margin_top(8)
            label.set_margin_bottom(8)
            label.add_css_class('app-label')
            row.set_child(label)
            self.listbox.append(row)

    def _select_first(self):
        row = self.listbox.get_row_at_index(0)
        if row:
            self.listbox.select_row(row)
        return False

    def _on_search(self, entry):
        query = entry.get_text().lower().strip()
        if not query:
            self.filtered = self.all_apps[:]
        else:
            self.filtered = [
                (name, app_id) for name, app_id in self.all_apps
                if query in name.lower()
            ]
        self._populate_list(self.filtered)
        GLib.idle_add(self._select_first)

    def _on_enter(self, entry):
        row = self.listbox.get_selected_row()
        if row:
            launch_app(row.app_id)
            self.close()

    def _on_activate(self, listbox, row):
        launch_app(row.app_id)
        self.close()

    def _on_key(self, ctrl, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
        elif keyval == Gdk.KEY_Down:
            self._move_selection(1)
        elif keyval == Gdk.KEY_Up:
            self._move_selection(-1)
        elif keyval == Gdk.KEY_Return:
            row = self.listbox.get_selected_row()
            if row:
                launch_app(row.app_id)
                self.close()
        return False

    def _move_selection(self, direction):
        current = self.listbox.get_selected_row()
        if current is None:
            self._select_first()
            return
        idx      = current.get_index()
        next_row = self.listbox.get_row_at_index(idx + direction)
        if next_row:
            self.listbox.select_row(next_row)
            next_row.grab_focus()

    def _apply_css(self):
        css = b"""
        window {
            background-color: rgba(10, 10, 15, 0.97);
            border: 1px solid rgba(0, 229, 255, 0.3);
            border-radius: 10px;
        }
        .search-entry {
            font-family: JetBrains Mono, monospace;
            font-size: 14px;
            background-color: transparent;
            border: none;
            border-bottom: 1px solid rgba(0, 229, 255, 0.15);
            border-radius: 0;
            color: #e8e8ec;
            caret-color: #00e5ff;
            padding: 6px 4px;
            box-shadow: none;
        }
        .search-entry:focus {
            outline: none;
            box-shadow: none;
            border-bottom-color: rgba(0, 229, 255, 0.6);
        }
        .sep {
            background-color: rgba(0, 229, 255, 0.1);
            min-height: 1px;
        }
        .app-list {
            background: transparent;
        }
        .app-row {
            background: transparent;
            border-radius: 4px;
            margin: 1px 8px;
        }
        .app-row:selected {
            background-color: rgba(0, 229, 255, 0.1);
        }
        .app-row:selected .app-label {
            color: #00e5ff;
        }
        .app-label {
            font-family: JetBrains Mono, monospace;
            font-size: 13px;
            color: #9a9aaa;
        }
        scrollbar {
            background: transparent;
            min-width: 4px;
        }
        scrollbar slider {
            background-color: rgba(0, 229, 255, 0.2);
            border-radius: 4px;
            min-height: 30px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


class LauncherApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='dev.deepstar.launcher')

    def do_activate(self):
        win = LauncherWindow(self)
        win.present()
        win.entry.grab_focus()


if __name__ == '__main__':
    app = LauncherApp()
    app.run(sys.argv)