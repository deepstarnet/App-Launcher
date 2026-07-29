import sys
import os
import json
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, Gio, GObject

USAGE_FILE = os.path.expanduser("~/.cache/usage.json")

WINDOW_WIDTH  = 850
WINDOW_HEIGHT = 400

# will be separate file
COLORS = {
    "bg": "#0a0a0f",
    "text": "#e0e0e0",
    "muted": "#5a5a66",
    "accent_1": "#00ff9f",
    "accent_2": "#00e5ff",
    "panel": "#0e0e14",
    "border": "#1c1c24",
}


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


class AppItem(GObject.Object):
    __gtype_name__ = 'AppItem'

    def __init__(self, name, app_info):
        super().__init__()
        self.name = name
        self.app_info = app_info
        self.icon = app_info.get_icon()
        self.app_id = app_info.get_id() or name


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

        self._apply_css()

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main_box.add_css_class("main-box")
        self.set_child(main_box)

        # search 
        self.entry = Gtk.SearchEntry(placeholder_text="Search...")
        self.entry.add_css_class("search-entry")
        self.entry.set_margin_start(10)
        self.entry.set_margin_end(10)
        self.entry.set_margin_top(10)
        self.entry.set_margin_bottom(6)
        self.entry.connect("search-changed", self._on_search_changed)
        self.entry.connect("activate", self._on_entry_activate)
        main_box.append(self.entry)

        #  data: base store -> filter -> sorter (optional) -> selection
        self.usage = load_usage()
        self.store = Gio.ListStore(item_type=AppItem)
        for app_item in get_all_apps():
            self.store.append(app_item)
        self._sort_store_by_usage()

        self.filter = Gtk.CustomFilter.new(self._filter_func, None)
        self.filter_model = Gtk.FilterListModel(model=self.store, filter=self.filter)

        self.selection = Gtk.SingleSelection(model=self.filter_model)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_item)
        factory.connect("bind", self._bind_item)

        self.list_view = Gtk.ListView(model=self.selection, factory=factory)
        self.list_view.add_css_class("app-list")
        self.list_view.connect("activate", self._on_activate)
        self.list_view.set_single_click_activate(True)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.list_view)
        main_box.append(scroller)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect('key-pressed', self._on_key_pressed)
        self.add_controller(key_controller)

        self.connect("close-request", self._on_close_request)

        # focus search on open, select first row by default
        self.entry.grab_focus()
        if self.filter_model.get_n_items() > 0:
            self.selection.set_selected(0)

    # usage / sorting
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

    # filing
    def _filter_func(self, item, user_data):
        query = self.entry.get_text().strip().lower()
        if not query:
            return True
        return query in item.name.lower()

    def _on_search_changed(self, entry):
        self.filter.changed(Gtk.FilterChange.DIFFERENT)
        if self.filter_model.get_n_items() > 0:
            self.selection.set_selected(0)
        else:
            self.selection.set_selected(Gtk.INVALID_LIST_POSITION)

    # ---------- launching ----------
    def _on_close_request(self, *_args):
        self.set_visible(False)
        return True  # отменяем стандартный destroy

    def _on_activate(self, list_view, position):
        app_item = self.filter_model.get_item(position)
        if app_item is None:
            return
        try:
            context = Gdk.Display.get_default().get_app_launch_context()
            app_item.app_info.launcher([], context)
            self._bump_usage(app_item)
        except Exeption as e:
            print(f"Failed to launch {app_item.name}: {e}")
        finally:
            self.set_visible(False)
    def _on_entry_activate(self, entry):
        
        self._launch_selected()

    def _launch_selected(self):
        position = self.selection.get_selected()
        if position == Gtk.INVALID_LIST_POSITION:
            return
        self._on_activate(self.list_view, position)

    # keyboard
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
            if index < self.filter_model.get_n_items():
                self._on_activate(self.list_view, index)
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._launch_selected()
            return True
        if keyval == Gdk.KEY_Down:
            pos = self.selection.get_selected()
            n = self.filter_model.get_n_items()
            if n > 0:
                self.selection.set_selected(min(pos + 1, n - 1) if pos != Gtk.INVALID_LIST_POSITION else 0)
            return True
        if keyval == Gdk.KEY_Up:
            pos = self.selection.get_selected()
            if pos != Gtk.INVALID_LIST_POSITION and pos > 0:
                self.selection.set_selected(pos - 1)
            return True
        return False

    # -list item
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
        # keep direct references instead of relying on observe_children() order
        box.icon = icon
        box.label = label
        list_item.set_child(box)

    def _bind_item(self, factory, list_item):
        app_item = list_item.get_item()
        box = list_item.get_child()
        box.icon.set_from_gicon(app_item.icon)
        box.label.set_text(app_item.name)

    # styling (in the future will be a separate file)
    def _apply_css(self):
        css = f"""
        window {{
            background-color: {COLORS['bg']};
            border: 1px solid {COLORS['border']};
            border-radius: 20px;
            color: {COLORS['text']};
        }}
        .main-box {{
            border-radius: 20px;
        }}
        .search-entry {{
            color: {COLORS['text']};
            background-color: {COLORS['panel']};
            border: 1px solid {COLORS['border']};
            padding: 8px;
            border-radius: 16px;
        }}
        listview {{
            background-color: transparent;
            padding: 5px;
        }}
        listview row {{
            padding: 10px;
            color: {COLORS['text']};
            border-radius: 10px;
        }}
        listview row:selected {{
            background-color: rgba(0, 255, 159, 0.1);
            border-left: 2px solid {COLORS['accent_1']};
            color: #ffffff;
        }}
        listview row:hover {{
            background-color: rgba(0, 229, 255, 0.06);
        }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
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
            self.win.selection.set_selected(0)
        self.win.entry.grab_focus()
        self.win.present()


if __name__ == '__main__':
    app = LauncherApp()
    app.run(sys.argv)