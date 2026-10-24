# -*- coding: utf-8 -*-
"""PyCode Studio - a VS Code-inspired code editor for Android, pure Python (Kivy)."""
import builtins
import contextlib
import ctypes
import importlib
import importlib.metadata as md
import io
import json
import keyword
import os
import queue
import re
import shlex
import shutil
import sys
import threading
import traceback
from functools import partial

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.codeinput import CodeInput
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.recycleview import RecycleView
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.spinner import Spinner
from kivy.uix.switch import Switch
from kivy.uix.textinput import TextInput
from kivy.utils import get_color_from_hex as hexc
from pygments.lexers import (CssLexer, HtmlLexer, JavaLexer, JavascriptLexer,
                             PythonLexer, XmlLexer)
from pygments.lexers.special import TextLexer

from catalog import load_catalog, norm

try:
    import jedi  # optional: smart Python completion
except Exception:
    jedi = None

THEMES = {
    "dark": dict(bg="#111827", editor="#0B1220", bar="#1F2937", accent="#2563EB",
                 text="#E5E7EB", style="monokai"),
    "light": dict(bg="#F3F4F6", editor="#FFFFFF", bar="#E5E7EB", accent="#2563EB",
                  text="#111827", style="default"),
}
DEFAULTS = dict(theme="dark", font_size=15, tab_size=4, autocomplete=True, confirm_run=True)

LANGS = {
    ".py": ("Python", PythonLexer), ".java": ("Java", JavaLexer),
    ".html": ("HTML", HtmlLexer), ".htm": ("HTML", HtmlLexer),
    ".css": ("CSS", CssLexer), ".js": ("JavaScript", JavascriptLexer),
    ".xml": ("XML", XmlLexer),
}

WORDS = {
    "Python": list(keyword.kwlist) + [b for b in dir(builtins) if not b.startswith("_")],
    "Java": ("abstract assert boolean break byte case catch char class const continue default do "
             "double else enum extends final finally float for if implements import instanceof int "
             "interface long native new package private protected public return short static super "
             "switch synchronized this throw throws try void volatile while String System.out.println "
             "ArrayList HashMap List Map Set Integer Object Override main args").split(),
    "JavaScript": ("async await break case catch class const continue console.log debugger default "
                   "delete do else export extends finally for function if import in instanceof let new "
                   "of return super switch this throw try typeof var void while yield document window "
                   "addEventListener querySelector getElementById fetch JSON.stringify JSON.parse "
                   "Promise setTimeout setInterval Array Object Math null undefined true false").split(),
    "HTML": ("html head body title meta link script style div span p a img ul ol li table tr td th "
             "form input button label select option textarea h1 h2 h3 h4 h5 h6 header footer nav "
             "section article aside main br hr class id href src alt type value placeholder").split(),
    "CSS": ("color background background-color border border-radius margin padding width height "
            "display flex grid position absolute relative fixed top left right bottom font-size "
            "font-family font-weight text-align justify-content align-items overflow opacity "
            "transition transform z-index box-shadow cursor content gap").split(),
    "XML": "xml version encoding xmlns xsi schemaLocation".split(),
}

# (label, text to insert, move cursor left by N)
SHORTCUTS = [("TAB", "\t", 0), ("( )", "()", 1), ("[ ]", "[]", 1), ("{ }", "{}", 1),
             ('" "', '""', 1), ("' '", "''", 1), (":", ":", 0), ("=", "=", 0), ("#", "#", 0),
             ("<", "<", 0), (">", ">", 0), ("/", "/", 0), ("\\", "\\", 0), (";", ";", 0),
             ("_", "_", 0), (".", ".", 0), (",", ",", 0)]


def quick_suggestions(lang, text, index, module_names):
    """Keyword + document-word completion. Returns [(label, text_to_insert)]."""
    before = text[:index]
    pat = r"[\w\-]+$" if lang in ("HTML", "CSS", "XML") else r"[\w\.]+$"
    m = re.search(pat, before)
    if not m:
        return []
    prefix = m.group(0)
    tail = prefix.rsplit(".", 1)[-1]
    line = before.rsplit("\n", 1)[-1].lstrip()
    if lang == "Python" and re.match(r"(import|from)\s", line):
        pool = list(module_names)
    else:
        pool = list(WORDS.get(lang, ()))
    doc_pat = r"[A-Za-z_][\w\-]*" if lang in ("HTML", "CSS", "XML") else r"[A-Za-z_]\w*"
    doc_words = set(re.findall(doc_pat, text))
    out, seen = [], set()
    for w in pool:
        if w.startswith(prefix) and w != prefix and w not in seen:
            seen.add(w)
            out.append((w, w[len(prefix):]))
    for w in doc_words:
        if tail and w.startswith(tail) and w != tail and w not in seen:
            seen.add(w)
            out.append((w, w[len(tail):]))
    out.sort(key=lambda p: (len(p[0]), p[0]))
    return out[:30]


class TermWriter(io.TextIOBase):
    encoding = "utf-8"

    def __init__(self, app):
        self.app = app

    def write(self, s):
        self.app.term_write(s)
        return len(s)

    def flush(self):
        pass


class Editor(CodeInput):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self.lang = "Python"

    def insert_text(self, substring, from_undo=False):
        if substring == "\n" and not from_undo:
            line = self.text[:self.cursor_index()].rsplit("\n", 1)[-1]
            indent = re.match(r"[ \t]*", line).group(0)
            opens = (self.lang == "Python" and line.rstrip().endswith(":")) or \
                    (self.lang in ("Java", "JavaScript", "CSS") and line.rstrip().endswith("{"))
            if opens:
                indent += " " * self.app.cfg["tab_size"]
            substring = "\n" + indent
        return super().insert_text(substring, from_undo=from_undo)


class LibRow(Button):
    lib = StringProperty("")

    def __init__(self, **kw):
        super().__init__(**kw)
        t = App.get_running_app().theme
        self.background_normal = ""
        self.background_color = hexc(t["bar"])
        self.color = hexc(t["text"])
        self.halign = "left"
        self.bind(size=lambda *_: setattr(self, "text_size", (self.width - dp(16), None)))

    def on_release(self):
        App.get_running_app().install_lib(self.lib)


class PyCodeApp(App):
    title = "PyCode Studio"

    # ------------------------------------------------------------ setup
    def build(self):
        Window.softinput_mode = "resize"
        Window.bind(on_keyboard=self.on_key)
        u = self.user_data_dir
        self.projects = os.path.join(u, "projects")
        self.libs_dir = os.path.join(u, "site-packages")
        self.plugins = os.path.join(u, "catalog")
        for d in (self.projects, self.libs_dir, self.plugins):
            os.makedirs(d, exist_ok=True)
        if self.libs_dir not in sys.path:
            sys.path.insert(0, self.libs_dir)
        os.chdir(self.projects)
        self.cfg_path = os.path.join(u, "settings.json")
        self.cfg = dict(DEFAULTS)
        try:
            with open(self.cfg_path, encoding="utf-8") as f:
                self.cfg.update(json.load(f))
        except Exception:
            pass
        self.theme = THEMES[self.cfg["theme"]]
        self.catalog = load_catalog(self.plugins)
        self.modules = sorted({e["import"].split(".")[0] for e in self.catalog} |
                              set(getattr(sys, "stdlib_module_names", ())))
        self.installed = set()
        self.docs, self.cur, self.loading, self.ver = [], -1, False, 0
        self.term_buf = ["PyCode Studio terminal - type 'help'\n"]
        self.stdin_q, self.runner, self.waiting_input = queue.Queue(), None, False
        self.repl_ns = {"__name__": "__main__"}
        self.root_box = BoxLayout()
        self.render("editor")
        first = os.path.join(self.projects, "hello.py")
        if not os.path.exists(first):
            with open(first, "w", encoding="utf-8") as f:
                f.write('name = input("Your name: ")\nprint("Hello,", name)\n')
        self.open_file(first)
        self.refresh_installed()
        return self.root_box

    def save_cfg(self):
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f)

    def set_cfg(self, key, value):
        self.cfg[key] = value
        self.save_cfg()

    def on_key(self, window, key, *a):
        if key == 27 and self.sm.current != "editor":
            self.goto("editor")
            return True
        return False

    def on_pause(self):
        self.save_all()
        return True

    def on_stop(self):
        self.save_all()

    # ------------------------------------------------------------ UI helpers
    def btn(self, text, cb=None, accent=False, **kw):
        t = self.theme
        b = Button(text=text, background_normal="", color=hexc("#FFFFFF" if accent else t["text"]),
                   background_color=hexc(t["accent"] if accent else t["bar"]), **kw)
        if cb:
            b.bind(on_release=lambda *_: cb())
        return b

    def label(self, text, **kw):
        lb = Label(text=text, color=hexc(self.theme["text"]), **kw)
        lb.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
        return lb

    def confirm(self, message, on_yes, yes="OK"):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        box.add_widget(self.label(message, halign="left"))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        pop = Popup(title="Confirm", content=box, size_hint=(.9, .45))

        def yes_cb():
            pop.dismiss()
            on_yes()
        row.add_widget(self.btn("Cancel", pop.dismiss))
        row.add_widget(self.btn(yes, yes_cb, accent=True))
        box.add_widget(row)
        pop.open()

    def render(self, screen="editor"):
        t = self.theme = THEMES[self.cfg["theme"]]
        Window.clearcolor = hexc(t["bg"])
        root = BoxLayout(orientation="vertical")
        nav = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(2))
        for name, label in (("editor", "Editor"), ("terminal", "Terminal"),
                            ("libs", "Libraries"), ("settings", "Settings")):
            nav.add_widget(self.btn(label, partial(self.goto, name)))
        self.sm = ScreenManager(transition=NoTransition())
        for scr in (self.editor_screen(), self.terminal_screen(),
                    self.libs_screen(), self.settings_screen()):
            self.sm.add_widget(scr)
        root.add_widget(nav)
        root.add_widget(self.sm)
        self.root_box.clear_widgets()
        self.root_box.add_widget(root)
        self.sm.current = screen
        if self.docs and 0 <= self.cur < len(self.docs):
            self.load_current()

    def goto(self, name):
        if name != "editor":
            self.editor.focus = False
        self.sm.current = name
        if name == "libs":
            self.filter_libs()

    # ------------------------------------------------------------ editor screen
    def editor_screen(self):
        t = self.theme
        s = Screen(name="editor")
        box = BoxLayout(orientation="vertical")
        bar = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(2))
        for label, cb in (("Files", self.show_files), ("New", self.new_file_popup),
                          ("Save", self.save_current), ("Run", self.run_current),
                          ("Stop", self.stop_run)):
            bar.add_widget(self.btn(label, cb, accent=(label == "Run")))
        self.tabs = BoxLayout(size_hint_x=None, spacing=dp(2))
        self.tabs.bind(minimum_width=self.tabs.setter("width"))
        tabs_sv = ScrollView(size_hint_y=None, height=dp(38), do_scroll_y=False)
        tabs_sv.add_widget(self.tabs)
        self.editor = Editor(self, style_name=t["style"], font_size=sp(self.cfg["font_size"]),
                             background_color=hexc(t["editor"]), cursor_color=hexc(t["accent"]),
                             unfocus_on_touch=False)
        self.editor.bind(text=self.on_editor_text, cursor=self.update_status)
        self.status = self.label("", size_hint_y=None, height=dp(22), halign="left")
        self.sugg = BoxLayout(size_hint_x=None, spacing=dp(3))
        self.sugg.bind(minimum_width=self.sugg.setter("width"))
        sugg_sv = ScrollView(size_hint_y=None, height=dp(40), do_scroll_y=False)
        sugg_sv.add_widget(self.sugg)
        keys = BoxLayout(size_hint_x=None, spacing=dp(3))
        keys.bind(minimum_width=keys.setter("width"))
        for label, text, back in SHORTCUTS:
            keys.add_widget(self.btn(label, partial(self.press_key, text, back),
                                     size_hint_x=None, width=dp(48)))
        keys.add_widget(self.btn("Undo", self.editor.do_undo, size_hint_x=None, width=dp(60)))
        keys.add_widget(self.btn("Redo", self.editor.do_redo, size_hint_x=None, width=dp(60)))
        keys_sv = ScrollView(size_hint_y=None, height=dp(40), do_scroll_y=False)
        keys_sv.add_widget(keys)
        for w in (bar, tabs_sv, self.editor, self.status, sugg_sv, keys_sv):
            box.add_widget(w)
        s.add_widget(box)
        return s

    def press_key(self, text, back):
        ed = self.editor
        if text == "\t":
            text = " " * self.cfg["tab_size"]
        ed.focus = True
        ed.insert_text(text)
        for _ in range(back):
            ed.do_cursor_movement("cursor_left")

    def update_status(self, *_):
        col, row = self.editor.cursor
        self.status.text = f"{self.editor.lang}   Ln {row + 1}, Col {col + 1}"

    # ------------------------------------------------------------ documents
    def write_doc(self, d):
        with open(d["path"], "w", encoding="utf-8") as f:
            f.write(d["text"])
        d["dirty"] = False

    def store_current(self):
        if 0 <= self.cur < len(self.docs):
            self.docs[self.cur]["text"] = self.editor.text

    def save_current(self):
        self.store_current()
        if 0 <= self.cur < len(self.docs):
            self.write_doc(self.docs[self.cur])
            self.refresh_tabs()

    def save_all(self):
        self.store_current()
        for d in self.docs:
            if d["dirty"]:
                self.write_doc(d)

    def open_file(self, path):
        for i, d in enumerate(self.docs):
            if d["path"] == path:
                return self.switch_doc(i)
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        self.docs.append({"path": path, "text": text, "dirty": False})
        self.switch_doc(len(self.docs) - 1)

    def switch_doc(self, i):
        self.store_current()
        self.cur = i
        self.load_current()

    def load_current(self):
        d = self.docs[self.cur]
        lang, lexer = LANGS.get(os.path.splitext(d["path"])[1].lower(), ("Text", TextLexer))
        self.loading = True
        self.editor.lang = lang
        self.editor.lexer = lexer()
        self.editor.text = d["text"]
        self.loading = False
        self.clear_suggestions()
        self.refresh_tabs()
        self.update_status()

    def close_doc(self, i):
        self.store_current()
        d = self.docs[i]
        if d["dirty"]:
            self.write_doc(d)
        self.docs.pop(i)
        if not self.docs:
            self.create_file("untitled.py")
            return
        self.cur = min(max(i - 1, 0), len(self.docs) - 1)
        self.load_current()

    def refresh_tabs(self):
        self.tabs.clear_widgets()
        for i, d in enumerate(self.docs):
            name = os.path.basename(d["path"]) + (" *" if d["dirty"] else "")
            self.tabs.add_widget(self.btn(name, partial(self.switch_doc, i), accent=(i == self.cur),
                                          size_hint_x=None, width=dp(120)))
            self.tabs.add_widget(self.btn("x", partial(self.close_doc, i),
                                          size_hint_x=None, width=dp(32)))

    def create_file(self, name):
        name = os.path.basename(name.strip()) or "untitled.py"
        if not os.path.splitext(name)[1]:
            name += ".py"
        path = os.path.join(self.projects, name)
        if not os.path.exists(path):
            open(path, "w", encoding="utf-8").close()
        self.open_file(path)

    def new_file_popup(self):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        inp = TextInput(text="untitled.py", multiline=False, size_hint_y=None, height=dp(44))
        pop = Popup(title="New file (.py .java .html .css .js .xml)", content=box, size_hint=(.9, .35))

        def ok():
            pop.dismiss()
            self.create_file(inp.text)
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        row.add_widget(self.btn("Cancel", pop.dismiss))
        row.add_widget(self.btn("Create", ok, accent=True))
        for w in (inp, row):
            box.add_widget(w)
        pop.open()

    def show_files(self):
        box = BoxLayout(orientation="vertical", spacing=dp(4))
        grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(4))
        grid.bind(minimum_height=grid.setter("height"))
        pop = Popup(title="Files", content=box, size_hint=(.92, .8))

        def open_it(p):
            pop.dismiss()
            self.open_file(p)

        def del_it(p):
            def yes():
                pop.dismiss()
                for i, d in enumerate(self.docs):
                    if d["path"] == p:
                        self.docs.pop(i)
                        break
                os.remove(p)
                if not self.docs:
                    self.create_file("untitled.py")
                else:
                    self.cur = 0
                    self.load_current()
            self.confirm(f"Delete {os.path.basename(p)}?", yes, "Delete")

        for name in sorted(os.listdir(self.projects)):
            p = os.path.join(self.projects, name)
            if not os.path.isfile(p):
                continue
            row = BoxLayout(size_hint_y=None, height=dp(44))
            row.add_widget(self.btn(name, partial(open_it, p)))
            row.add_widget(self.btn("Del", partial(del_it, p), size_hint_x=.2))
            grid.add_widget(row)
        sv = ScrollView()
        sv.add_widget(grid)
        box.add_widget(sv)
        box.add_widget(self.btn("Close", pop.dismiss, size_hint_y=None, height=dp(44)))
        pop.open()

    # ------------------------------------------------------------ autocomplete
    def on_editor_text(self, *_):
        if self.loading:
            return
        if 0 <= self.cur < len(self.docs):
            d = self.docs[self.cur]
            if not d["dirty"]:
                d["dirty"] = True
                self.refresh_tabs()
        self.ver += 1
        Clock.unschedule(self._suggest)
        if self.cfg["autocomplete"]:
            Clock.schedule_once(self._suggest, .25)
        else:
            self.clear_suggestions()

    def _suggest(self, dt):
        ed, ver = self.editor, self.ver
        text, idx, lang = ed.text, ed.cursor_index(), ed.lang
        items = quick_suggestions(lang, text, idx, self.modules)
        self.show_suggestions(items)
        if lang == "Python" and jedi is not None:
            path = self.docs[self.cur]["path"] if 0 <= self.cur < len(self.docs) else None
            threading.Thread(target=self._jedi_job, args=(text, idx, ver, items, path),
                             daemon=True).start()

    def _jedi_job(self, text, idx, ver, items, path):
        try:
            line = text.count("\n", 0, idx) + 1
            col = idx - (text.rfind("\n", 0, idx) + 1)
            res = [(c.name, c.complete) for c in jedi.Script(text, path=path).complete(line, col)[:40]
                   if c.complete is not None]
        except Exception:
            return
        Clock.schedule_once(lambda dt: self._merge(ver, res, items))

    def _merge(self, ver, res, items):
        if ver != self.ver:
            return
        seen, out = set(), []
        for label, ins in res + items:
            if label not in seen:
                seen.add(label)
                out.append((label, ins))
        self.show_suggestions(out)

    def show_suggestions(self, items):
        self.clear_suggestions()
        for label, ins in items[:25]:
            self.sugg.add_widget(self.btn(label, partial(self.apply_suggestion, ins),
                                          accent=True, size_hint_x=None,
                                          width=max(dp(60), dp(11) * len(label) + dp(16))))

    def clear_suggestions(self):
        self.sugg.clear_widgets()

    def apply_suggestion(self, ins):
        self.editor.focus = True
        self.editor.insert_text(ins)

    # ------------------------------------------------------------ running code
    def run_current(self):
        self.save_current()
        if not (0 <= self.cur < len(self.docs)):
            return
        path = self.docs[self.cur]["path"]
        if not path.endswith(".py"):
            self.confirm("Only .py files can be run. Java, HTML, CSS, JavaScript and XML "
                         "files are edit-only in this version.", lambda: None)
            return

        def go():
            self.goto("terminal")
            self.start_program(path)
        if self.cfg["confirm_run"]:
            self.confirm("Run this file?\nIt runs inside the app with the app's own permissions "
                         "(no sandbox).", go, "Run")
        else:
            go()

    def term_input(self, prompt=""):
        self.term_write(str(prompt))
        self.waiting_input = True
        line = self.stdin_q.get()
        self.waiting_input = False
        return line

    def start_program(self, path):
        if self.runner and self.runner.is_alive():
            self.term_write("A program is already running (use Stop).\n")
            return
        self.term_write(f"\n$ python {os.path.basename(path)}\n")

        def work():
            ns = {"__name__": "__main__", "__file__": path, "input": self.term_input}
            old = (sys.stdout, sys.stderr, sys.argv)
            sys.stdout = sys.stderr = TermWriter(self)
            sys.argv = [path]
            cwd = os.getcwd()
            folder = os.path.dirname(path)
            os.chdir(folder)
            if folder not in sys.path:
                sys.path.insert(0, folder)
            try:
                with open(path, encoding="utf-8") as f:
                    src = f.read()
                exec(compile(src, path, "exec"), ns)
            except SystemExit:
                pass
            except BaseException:
                traceback.print_exc()
            finally:
                sys.stdout, sys.stderr, sys.argv = old
                os.chdir(cwd)
                self.term_write("[finished]\n")
        self.runner = threading.Thread(target=work, daemon=True)
        self.runner.start()

    def stop_run(self):
        t = self.runner
        if t and t.is_alive():
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(t.ident),
                                                       ctypes.py_object(SystemExit))
            self.stdin_q.put("")
            self.term_write("[stop requested]\n")

    # ------------------------------------------------------------ terminal
    def terminal_screen(self):
        t = self.theme
        s = Screen(name="terminal")
        box = BoxLayout(orientation="vertical")
        self.term_out = TextInput(readonly=True, font_name="data/fonts/RobotoMono-Regular.ttf",
                                  font_size=sp(13), background_color=hexc(t["editor"]),
                                  foreground_color=hexc(t["text"]), text="".join(self.term_buf))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(2))
        self.term_in = TextInput(multiline=False, hint_text="pip install requests | help",
                                 font_size=sp(14))
        self.term_in.bind(on_text_validate=self.term_submit)
        row.add_widget(self.term_in)
        row.add_widget(self.btn("Enter", lambda: self.term_submit(self.term_in), accent=True,
                                size_hint_x=.25))
        box.add_widget(self.term_out)
        box.add_widget(row)
        s.add_widget(box)
        return s

    @mainthread
    def term_write(self, s):
        self.term_buf.append(s)
        text = "".join(self.term_buf)
        if len(text) > 60000:
            text = text[-40000:]
            self.term_buf = [text]
        self.term_out.text = text
        Clock.schedule_once(lambda dt: setattr(self.term_out, "cursor",
                                               self.term_out.get_cursor_from_index(len(text))))

    def term_submit(self, inp):
        line = inp.text
        inp.text = ""
        Clock.schedule_once(lambda dt: setattr(inp, "focus", True), .1)
        if self.waiting_input:
            self.term_write(line + "\n")
            self.stdin_q.put(line)
            return
        if not line.strip():
            return
        self.term_write(f"$ {line}\n")
        self.shell(line)

    def shell(self, line):
        try:
            parts = shlex.split(line)
        except ValueError as e:
            self.term_write(f"parse error: {e}\n")
            return
        cmd, args = parts[0], parts[1:]
        w = self.term_write
        if cmd == "help":
            w("help | clear | pwd | ls | cd DIR | cat FILE | python FILE.py\n"
              "pip install NAME... | pip uninstall NAME... | pip list\n"
              "libs [WORD]  - search the library catalog\n"
              "anything else runs as a Python expression/statement\n")
        elif cmd == "clear":
            self.term_buf = []
            self.term_out.text = ""
        elif cmd == "pwd":
            w(os.getcwd() + "\n")
        elif cmd == "ls":
            w("  ".join(sorted(os.listdir(args[0] if args else "."))) + "\n")
        elif cmd == "cd":
            try:
                os.chdir(args[0] if args else self.projects)
            except Exception as e:
                w(f"cd: {e}\n")
        elif cmd == "cat" and args:
            try:
                with open(args[0], encoding="utf-8", errors="replace") as f:
                    w(f.read() + "\n")
            except Exception as e:
                w(f"cat: {e}\n")
        elif cmd in ("python", "run") and args:
            p = os.path.abspath(args[0])
            if os.path.isfile(p):
                self.start_program(p)
            else:
                w(f"no such file: {args[0]}\n")
        elif cmd == "pip":
            self.pip(args)
        elif cmd == "libs":
            q = args[0].lower() if args else ""
            hits = [e["name"] for e in self.catalog if q in e["name"].lower()]
            w(f"{len(hits)} match(es)\n" + ", ".join(hits[:80]) + "\n")
        else:
            self.repl(line)

    def repl(self, line):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                try:
                    r = eval(compile(line, "<repl>", "eval"), self.repl_ns)
                    if r is not None:
                        print(repr(r))
                except SyntaxError:
                    exec(compile(line, "<repl>", "exec"), self.repl_ns)
            except Exception:
                traceback.print_exc(limit=1)
        self.term_write(buf.getvalue())

    # ------------------------------------------------------------ pip
    def pip(self, args):
        if not args:
            self.term_write("usage: pip install|uninstall|list ...\n")
        elif args[0] == "install" and len(args) > 1:
            self.pip_install(args[1:])
        elif args[0] == "uninstall" and len(args) > 1:
            for n in [a for a in args[1:] if not a.startswith("-")]:
                self.pip_uninstall(n)
            self.refresh_installed()
        elif args[0] == "list":
            names = sorted(d for d in os.listdir(self.libs_dir) if d.endswith(".dist-info"))
            self.term_write("\n".join(n[:-10] for n in names) + ("\n" if names else "(nothing installed)\n"))
        else:
            self.term_write("supported: pip install | pip uninstall | pip list\n")

    def pip_install(self, names):
        def work():
            try:
                from pip._internal.cli.main import main as pip_main
            except Exception:
                self.term_write("pip is not bundled in this build "
                                "(add 'pip' to requirements in buildozer.spec).\n")
                return
            old = (sys.stdout, sys.stderr)
            sys.stdout = sys.stderr = TermWriter(self)
            rc = 1
            try:
                rc = pip_main(["install", "--target", self.libs_dir, "--upgrade",
                               "--only-binary=:all:", "--no-warn-script-location",
                               "--disable-pip-version-check", "--progress-bar", "off"] + names)
            except SystemExit as e:
                rc = e.code or 0
            except BaseException:
                traceback.print_exc()
            finally:
                sys.stdout, sys.stderr = old
            importlib.invalidate_caches()
            if rc == 0:
                self.term_write("[done]\n")
            else:
                self.term_write(f"[pip failed ({rc}). Packages with native code usually have no "
                                "Android wheel; bundle them at build time instead.]\n")
            Clock.schedule_once(lambda dt: self.refresh_installed())
        self.term_write("Installing (pure-Python wheels only)...\n")
        threading.Thread(target=work, daemon=True).start()

    def pip_uninstall(self, name):
        target = norm(name)
        found = False
        for d in os.listdir(self.libs_dir):
            if not d.endswith(".dist-info"):
                continue
            if norm(d[:-10].rsplit("-", 1)[0]) != target:
                continue
            found = True
            info = os.path.join(self.libs_dir, d)
            tops = set()
            try:
                with open(os.path.join(info, "RECORD"), encoding="utf-8") as f:
                    for ln in f:
                        p = ln.split(",")[0].strip()
                        if p and not p.startswith(".."):
                            tops.add(p.split("/")[0])
            except OSError:
                pass
            # note: packages sharing a namespace folder (e.g. google/) may lose siblings
            for top in tops:
                p = os.path.join(self.libs_dir, top)
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                elif os.path.isfile(p):
                    os.remove(p)
            shutil.rmtree(info, ignore_errors=True)
        self.term_write(f"{'removed' if found else 'not installed'}: {name}\n")

    def refresh_installed(self):
        names = set()
        try:
            for d in md.distributions():
                n = d.metadata["Name"]
                if n:
                    names.add(norm(n))
        except Exception:
            pass
        self.installed = names
        if hasattr(self, "rv"):
            self.filter_libs()

    # ------------------------------------------------------------ libraries screen
    def libs_screen(self):
        s = Screen(name="libs")
        box = BoxLayout(orientation="vertical")
        top = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(2))
        self.lib_search = TextInput(hint_text=f"Search {len(self.catalog)} libraries", multiline=False)
        cats = ["All"] + sorted({e["category"] for e in self.catalog})
        self.lib_cat = Spinner(text="All", values=cats, size_hint_x=.4)
        self.lib_search.bind(text=lambda *_: self.filter_libs())
        self.lib_cat.bind(text=lambda *_: self.filter_libs())
        top.add_widget(self.lib_search)
        top.add_widget(self.lib_cat)
        top.add_widget(self.btn("+", self.add_lib_popup, size_hint_x=None, width=dp(44)))
        self.lib_count = self.label("", size_hint_y=None, height=dp(24), halign="left")
        self.rv = RecycleView()
        self.rv.viewclass = LibRow
        lay = RecycleBoxLayout(default_size=(None, dp(56)), default_size_hint=(1, None),
                               size_hint_y=None, orientation="vertical", spacing=dp(2))
        lay.bind(minimum_height=lay.setter("height"))
        self.rv.add_widget(lay)
        for w in (top, self.lib_count, self.rv):
            box.add_widget(w)
        s.add_widget(box)
        return s

    def filter_libs(self):
        q = self.lib_search.text.strip().lower()
        cat = self.lib_cat.text
        rows = []
        for e in self.catalog:
            if cat != "All" and e["category"] != cat:
                continue
            if q and q not in e["name"].lower():
                continue
            if norm(e["name"]) in self.installed:
                tag = "installed"
            else:
                tag = "native code - may not install" if e["native"] else "pure Python - installable"
            rows.append({"text": f"{e['name']}\n[{e['category']}] {tag}", "lib": e["name"]})
        self.rv.data = rows
        self.lib_count.text = f"  {len(rows)} / {len(self.catalog)}"

    def install_lib(self, name):
        entry = next((e for e in self.catalog if e["name"] == name), None)
        warn = ""
        if entry and entry["native"]:
            warn = "\n\nThis package contains native code. It will probably fail to install " \
                   "with pip on Android."

        def go():
            self.goto("terminal")
            self.pip_install([name])
        self.confirm(f"pip install {name}?{warn}", go, "Install")

    def add_lib_popup(self):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        name = TextInput(hint_text="PyPI package name", multiline=False, size_hint_y=None, height=dp(44))
        cat = TextInput(text="Custom", multiline=False, size_hint_y=None, height=dp(44))
        pop = Popup(title="Add library to catalog", content=box, size_hint=(.9, .5))

        def ok():
            n = name.text.strip()
            if n:
                path = os.path.join(self.plugins, "custom.json")
                try:
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = []
                data.append({"name": n, "category": cat.text.strip() or "Custom", "native": False})
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=1)
                self.catalog = load_catalog(self.plugins)
                self.filter_libs()
            pop.dismiss()
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        row.add_widget(self.btn("Cancel", pop.dismiss))
        row.add_widget(self.btn("Add", ok, accent=True))
        for w in (name, cat, row):
            box.add_widget(w)
        pop.open()

    # ------------------------------------------------------------ settings screen
    def settings_screen(self):
        s = Screen(name="settings")
        grid = GridLayout(cols=1, size_hint_y=None, spacing=dp(10), padding=dp(10))
        grid.bind(minimum_height=grid.setter("height"))

        def row(title, widget):
            r = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
            r.add_widget(self.label(title, halign="left"))
            r.add_widget(widget)
            grid.add_widget(r)

        theme = Spinner(text=self.cfg["theme"], values=("dark", "light"), size_hint_x=.5)
        theme.bind(text=lambda i, v: self.change_theme(v))
        row("Theme", theme)

        size = Slider(min=10, max=30, step=1, value=self.cfg["font_size"], size_hint_x=.6)
        size.bind(value=self.change_font)
        row("Font size", size)

        tab = Spinner(text=str(self.cfg["tab_size"]), values=("2", "4", "8"), size_hint_x=.5)
        tab.bind(text=lambda i, v: self.set_cfg("tab_size", int(v)))
        row("Tab size (spaces)", tab)

        ac = Switch(active=self.cfg["autocomplete"], size_hint_x=.5)
        ac.bind(active=lambda i, v: self.set_cfg("autocomplete", v))
        row("Auto-complete", ac)

        cr = Switch(active=self.cfg["confirm_run"], size_hint_x=.5)
        cr.bind(active=lambda i, v: self.set_cfg("confirm_run", v))
        row("Ask before running code", cr)

        info = (f"Jedi (smart Python completion): {'on' if jedi else 'not installed'}\n"
                f"Catalog: {len(self.catalog)} libraries\n"
                f"Add libraries: drop *.json files into\n{self.plugins}\n"
                f"Installed packages folder:\n{self.libs_dir}\nProjects folder:\n{self.projects}")
        lb = self.label(info, halign="left", size_hint_y=None, height=dp(190))
        grid.add_widget(lb)
        sv = ScrollView()
        sv.add_widget(grid)
        s.add_widget(sv)
        return s

    def change_theme(self, value):
        if value == self.cfg["theme"]:
            return
        self.set_cfg("theme", value)
        self.store_current()
        Clock.schedule_once(lambda dt: self.render("settings"))

    def change_font(self, inst, value):
        self.set_cfg("font_size", int(value))
        self.editor.font_size = sp(int(value))


if __name__ == "__main__":
    PyCodeApp().run()
