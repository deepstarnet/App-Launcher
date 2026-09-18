import sys
import os
import json
import re
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, Gio, GObject

USAGE_FILE = os.path.expanduser("~/.cache/usage.json")

WINDOW_WIDTH  = 850
WINDOW_HEIGHT = 800

COLORS = {
    "bg": "#0a0a0f",
    "text": "#e0e0e0",
    "muted": "#5a5a66",
    "accent_1": "#ff2d55",   # neon red
    "accent_2": "#00e5ff",   # cyan
    "panel": "#0e0e14",
    "border": "#1c1c24",
    "glow_red": "rgba(255, 45, 85, 0.15)",
    "glow_cyan": "rgba(0, 229, 255, 0.15)",
}

CALC_PATTERN = re.compile(r'^[\d\s\+\-\*\/\.\(\)%]+$')


def load_usage():
    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_usage(usage):
    os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
    with open(USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(usage, f)


def fuzzy_score(query, text):
    """
    Fuzzy matcher: возвращает score > 0 если все символы query
    встречаются в text по порядку, иначе 0. Компактнее совпадение
    и ближе к началу строки = выше score.
    """
    query = query.lower()
    text = text.lower()

    if not query:
        return 1

    if query in text:
        idx = text.index(query)
        return 1000 - idx

    t_idx = 0
    match_positions = []
    for ch in query:
        found_at = text.find(ch, t_idx)
        if found_at == -1:
            return 0
        match_positions.append(found_at)
        t_idx = found_at + 1

    if not match_positions:
        return 0

    span = match_positions[-1] - match_positions[0] + 1
    return max(1, 500 - span * 5)


def safe_eval_calc(expr):
    """Безопасное вычисление арифметики без произвольного eval."""
    if not CALC_PATTERN.match(expr):
        return None
    try:
        result = eval(expr, {"__builtins__": {}}, {})
        if isinstance(result, (int, float)):
            return result
    except Exception:
        return None
    return None


class AppItem(GObject.Object):
    __gtype_name__ = 'AppItem'

    def __init__(self, name, app_info):
        super().__init__()
        self.name = name
        self.app_info = app_info
        self.icon = app_info.get_icon()
        self.app_id = app_info.get_id() or name
        self.score = 0


def get_all_apps():
    apps = []
    for app in Gio.AppInfo.get_all():
        if app.should_show():
            apps.append(AppItem(app.get_name(), app))
    return apps


class LauncherWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.set_size_request(WINDOW_WIDTH, WINDOW_HEIGHT)

        self.add_css_class("launcher")

        self._apply_css()

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.main_box.add_css_class("main-box")
        self.set_child(self.main_box)

        # Обычный GtkEntry вместо GtkSearchEntry — меньше системных
        # Adwaita-биндингов, проще перебить кастомным CSS
        self.entry = Gtk.Entry(placeholder_text="Search or calculate...")
        self.entry.add_css_class("search-entry")
        self.entry.set_margin_start(10)
        self.entry.set_margin_end(10)
        self.entry.set_margin_top(10)
        self.entry.set_margin_bottom(6)
        self.entry.connect("changed", self._on_search_changed)
        self.entry.connect("activate", self._on_entry_activate)
        self.main_box.append(self.entry)

        self.calc_label = Gtk.Label(xalign=0)
        self.calc_label.add_css_class("calc-result")
        self.calc_label.set_margin_start(14)
        self.calc_label.set_margin_bottom(4)
        self.calc_label.set_visible(False)
        self.main_box.append(self.calc_label)

        self.usage = load_usage()
        self.store = Gio.ListStore(item_type=AppItem)
        for app_item in get_all_apps():
            self.store.append(app_item)
        self._sort_store_by_usage()

        self.filter = Gtk.CustomFilter.new(self._filter_func, None)
        self.filter_model = Gtk.FilterListModel(model=self.store, filter=self.filter)

        self.sorter = Gtk.CustomSorter.new(self._sort_func, None)
        self.sort_model = Gtk.SortListModel(model=self.filter_model, sorter=self.sorter)

        self.selection = Gtk.SingleSelection(model=self.sort_model)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_item)
        factory.connect("bind", self._bind_item)

        self.list_view = Gtk.ListView(model=self.selection, factory=factory)
        self.list_view.add_css_class("app-list")
        self.list_view.connect("activate", self._on_activate)
        self.list_view.set_single_click_activate(True)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_vexpand(True)
        self.scroller.set_child(self.list_view)
        self.main_box.append(self.scroller)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect('key-pressed', self._on_key_pressed)
        self.add_controller(key_controller)

        self.connect("close-request", self._on_close_request)

        self.entry.grab_focus()
        if self.sort_model.get_n_items() > 0:
            self.selection.set_selected(0)

    def _sort_store_by_usage(self):
        def compare(a, b, _data):
            count_a = self.usage.get(a.app_id, 0)
            count_b = self.usage.get(b.app_id, 0)
            if count_a != count_b:
                return -1 if count_a > count_b else 1
            return -1 if a.name.lower() < b.name.lower() else (1 if a.name.lower() > b.name.lower() else 0)
        self.store.sort(compare, None)

    def _bump_usage(self, app_item):
        self.usage[app_item.app_id] = self.usage.get(app_item.app_id, 0) + 1
        save_usage(self.usage)
        self._sort_store_by_usage()

    def _filter_func(self, item, user_data):
        query = self.entry.get_text().strip()
        if not query:
            item.score = 0
            return True
        score = fuzzy_score(query, item.name)
        item.score = score
        return score > 0

    def _sort_func(self, a, b, user_data):
        query = self.entry.get_text().strip()
        if not query:
            return 0
        if a.score != b.score:
            return -1 if a.score > b.score else 1
        return 0

    def _on_search_changed(self, entry):
        query = entry.get_text().strip()

        calc_result = None
        if query and any(op in query for op in "+-*/%") and CALC_PATTERN.match(query):
            calc_result = safe_eval_calc(query)

        if calc_result is not None:
            self.calc_label.set_text(f"= {calc_result}")
            self.calc_label.set_visible(True)
        else:
            self.calc_label.set_visible(False)

        self.filter.changed(Gtk.FilterChange.DIFFERENT)
        self.sorter.changed(Gtk.SorterChange.DIFFERENT)

        if self.sort_model.get_n_items() > 0:
            self.selection.set_selected(0)
        else:
            self.selection.set_selected(Gtk.INVALID_LIST_POSITION)

    def _on_close_request(self, *_args):
        self.set_visible(False)
        return True

    def _copy_calc_result(self):
        text = self.calc_label.get_text()
        if text.startswith("= "):
            value = text[2:]
            clipboard = Gdk.Display.get_default().get_clipboard()
            clipboard.set(value)
            self.set_visible(False)

    def _on_activate(self, list_view, position):
        app_item = self.sort_model.get_item(position)
        if app_item is None:
            return
        try:
            context = Gdk.Display.get_default().get_app_launch_context()
            app_item.app_info.launch(None, context)
            self._bump_usage(app_item)
        except Exception as e:
            print(f"Failed to launch {app_item.name}: {e}")
        finally:
            self.set_visible(False)

    def _on_entry_activate(self, entry):
        if self.calc_label.get_visible():
            self._copy_calc_result()
            return
        self._launch_selected()

    def _launch_selected(self):
        position = self.selection.get_selected()
        if position == Gtk.INVALID_LIST_POSITION:
            return
        self._on_activate(self.list_view, position)

    NUM_KEYS = {
        Gdk.KEY_1: 0, Gdk.KEY_2: 1, Gdk.KEY_3: 2, Gdk.KEY_4: 3, Gdk.KEY_5: 4,
        Gdk.KEY_6: 5, Gdk.KEY_7: 6, Gdk.KEY_8: 7, Gdk.KEY_9: 8,
    }

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.set_visible(False)
            return True
        if state & Gdk.ModifierType.ALT_MASK and keyval in self.NUM_KEYS:
            index = self.NUM_KEYS[keyval]
            if index < self.sort_model.get_n_items():
                self._on_activate(self.list_view, index)
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._on_entry_activate(self.entry)
            return True
        if keyval == Gdk.KEY_Down:
            pos = self.selection.get_selected()
            n = self.sort_model.get_n_items()
            if n > 0:
                self.selection.set_selected(min(pos + 1, n - 1) if pos != Gtk.INVALID_LIST_POSITION else 0)
            return True
        if keyval == Gdk.KEY_Up:
            pos = self.selection.get_selected()
            if pos != Gtk.INVALID_LIST_POSITION and pos > 0:
                self.selection.set_selected(pos - 1)
            return True
        return False

    def _setup_item(self, factory, list_item):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_start(10)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        icon = Gtk.Image()
        icon.set_pixel_size(24)
        label = Gtk.Label(xalign=0)
        box.append(icon)
        box.append(label)
        box.icon = icon
        box.label = label
        list_item.set_child(box)

    def _bind_item(self, factory, list_item):
        app_item = list_item.get_item()
        box = list_item.get_child()

        if app_item.icon:
            box.icon.set_from_gicon(app_item.icon)
        else:
            box.icon.set_from_icon_name("application-x-executable")

        box.label.set_text(app_item.name)

    def _apply_css(self):
        # Против Adwaita: бьём по внутренним нодам (.search-entry text),
        # используем обычный GtkEntry, PRIORITY_USER + !important
        css = f"""
        window.launcher {{
            background-color: {COLORS['bg']} !important;
            border: 1px solid {COLORS['accent_2']};
            border-radius: 4px;
            color: {COLORS['text']} !important;
        }}

        window.launcher .main-box {{
            background-color: transparent;
        }}

        window.launcher .search-entry,
        window.launcher .search-entry text {{
            color: {COLORS['accent_2']} !important;
            background-color: {COLORS['panel']} !important;
            border: 1px solid {COLORS['accent_1']};
            border-radius: 2px;
            font-family: monospace;
            caret-color: {COLORS['accent_1']} !important;
        }}

        window.launcher .search-entry {{
            padding: 10px;
        }}

        window.launcher .search-entry:focus-within {{
            border: 1px solid {COLORS['accent_2']};
            box-shadow: 0 0 8px {COLORS['glow_cyan']};
        }}

        window.launcher .calc-result {{
            color: {COLORS['accent_1']} !important;
            font-family: monospace;
            font-weight: bold;
            font-size: 14px;
        }}

        window.launcher listview,
        window.launcher scrolledwindow {{
            background-color: transparent !important;
            padding: 5px;
        }}

        window.launcher listview row {{
            padding: 10px;
            color: {COLORS['text']} !important;
            border-left: 2px solid transparent;
            border-radius: 2px;
            background-color: transparent !important;
        }}

        window.launcher listview row label {{
            color: {COLORS['text']} !important;
        }}

        window.launcher listview row:selected {{
            background-color: {COLORS['glow_red']} !important;
            border-left: 2px solid {COLORS['accent_1']};
        }}

        window.launcher listview row:selected label {{
            color: #ffffff !important;
        }}

        window.launcher listview row:hover {{
            background-color: {COLORS['glow_cyan']} !important;
            border-left: 2px solid {COLORS['accent_2']};
        }}
        """
        provider = Gtk.CssProvider()
        try:
            provider.load_from_string(css)
        except Exception as e:
            print(f"[CSS ERROR] Failed to parse stylesheet: {e}")
            return

        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER,
        )


class LauncherApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='dev.deepstar.launcher')
        self.win = None

    def do_activate(self):
        if self.win is None:
            self.win = LauncherWindow(self)
        else:
            self.win.entry.set_text("")
            self.win.calc_label.set_visible(False)
            if self.win.sort_model.get_n_items() > 0:
                self.win.selection.set_selected(0)
            self.win.set_visible(True)

        self.win.entry.grab_focus()
        self.win.present()


if __name__ == '__main__':
    os.environ.setdefault("GTK_THEME", "Adwaita:dark")

    app = LauncherApp()
    app.run(sys.argv)