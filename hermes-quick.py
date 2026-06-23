#!/usr/bin/env python
"""
Hermes Quick Ask — 纯蓝无边框快捷输入小窗
==============================================
功能: Ctrl+H 呼出/隐藏，模型切换，Hermes CLI 调用
配色: 官网纯蓝 #0000f2 · 文字 #f5f5f5 · 完全无边框（overrideredirect）
语言: Python 3 + tkinter + keyboard + ctypes
==============================================
"""

import os
import sys
import subprocess
import tempfile
import threading
import queue
import ctypes
from ctypes import c_int, c_void_p, byref, c_uint, POINTER

try:
    import keyboard
except ImportError:
    print("缺少 keyboard 库，运行: uv pip install keyboard")
    sys.exit(1)
try:
    import tkinter as tk
    import tkinter.font as tkfont
except ImportError:
    print("缺少 tkinter，请安装 Python 时勾选 tcl/tk")
    sys.exit(1)

# ── 单实例锁 ─────────────────────────────────────────────
_LOCK_FILE = os.path.join(tempfile.gettempdir(), ".hermes_quick_ask.lock")


def _acquire_lock() -> bool:
    try:
        fd = os.open(_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            with open(_LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            handle = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, old_pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                print("⚠  已有实例在运行 | 按 Ctrl+H 弹出")
                return False
        except (ValueError, OSError, Exception):
            pass
        try:
            os.unlink(_LOCK_FILE)
        except OSError:
            pass
        return _acquire_lock()
    except OSError:
        return False


def _release_lock():
    try:
        os.unlink(_LOCK_FILE)
    except OSError:
        pass


# ── 配色 ─────────────────────────────────────────────────
BLUE = "#0000f2"
TEXT = "#f5f5f5"
TEXT_DIM = "#b0b0ff"
TEXT_MUTED = "#7070cc"
INPUT_BG = "#0a0ad0"
OUTPUT_BG = "#0808a0"
HOVER = "#1818e0"
SELECT = "#3030c0"
MODEL_BG = "#0a0ad0"
MENU_BG = "#0000d0"
MENU_HOVER = "#1a1ac0"

HOTKEY = "ctrl+h"

# 可用模型列表
MODELS = [
    "deepseek-v4-flash-free", "gpt-4o", "gpt-4o-mini",
    "claude-sonnet-4", "claude-haiku-3-5",
    "gemini-2-5-pro", "gemini-2-0-flash", "o3-mini",
]


# ── Hermes CLI ───────────────────────────────────────────
def _get_default_model() -> str:
    try:
        r = subprocess.run(
            ["hermes.exe", "config", "show"],
            capture_output=True, text=True, timeout=10,
        )
        for line in r.stdout.splitlines():
            if "model.default" in line or "default_model" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    return parts[1].strip().strip('"').strip("'")
        return MODELS[0]
    except Exception:
        return MODELS[0]


def _ask_hermes(query: str, model: str = "") -> str:
    try:
        cmd = ["hermes.exe", "chat", "-q", query, "-Q"]
        if model:
            cmd += ["-m", model]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        out = r.stdout.strip()

        # 提取 session_id 并删除该会话，不留聊天记录
        answer = out
        for line in out.split("\n"):
            if line.startswith("session_id:"):
                sid = line.split("session_id:")[-1].strip()
                answer = out.replace(line, "", 1).strip()
                try:
                    subprocess.run(
                        ["hermes.exe", "sessions", "delete", sid, "--yes"],
                        capture_output=True, timeout=10,
                    )
                except Exception:
                    pass
                break

        if answer:
            return answer

        # fallback: stderr
        if not out and r.stderr.strip():
            lines = [l for l in r.stderr.split("\n")
                     if "WARNING" not in l.upper() and "session_id" not in l.lower()]
            return "\n".join(lines).strip() or r.stderr.strip()[:200]

        return out or "(无输出)"
    except subprocess.TimeoutExpired:
        return "[超时] 请求超过 120 秒"
    except FileNotFoundError:
        return "[错误] 找不到 hermes.exe"
    except Exception as e:
        return f"[错误] {e}"


# ── Windows API 绑定 ─────────────────────────────────────
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = c_void_p
user32.GetWindowThreadProcessId.argtypes = [c_void_p, POINTER(c_uint)]
user32.GetWindowThreadProcessId.restype = c_uint
user32.AttachThreadInput.argtypes = [c_uint, c_uint, c_int]
user32.AttachThreadInput.restype = c_int
user32.SetForegroundWindow.argtypes = [c_void_p]
user32.SetForegroundWindow.restype = c_int
user32.SetActiveWindow.argtypes = [c_void_p]
user32.SetActiveWindow.restype = c_void_p
user32.SetFocus.argtypes = [c_void_p]
user32.SetFocus.restype = c_void_p
user32.GetWindowLongW.argtypes = [c_void_p, c_int]
user32.GetWindowLongW.restype = c_uint
user32.SetWindowLongW.argtypes = [c_void_p, c_int, c_uint]
user32.SetWindowLongW.restype = c_uint
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = c_uint

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000


# ── 窗口 ─────────────────────────────────────────────────
class HermesQuickWindow:

    def __init__(self):
        self.queue = queue.Queue()
        self._visible = False
        self._running = False
        self._current_model = _get_default_model()

        self.window = tk.Tk()
        self.window.title("Hermes Quick Ask")
        self.window.geometry("500x400+200+200")
        self.window.minsize(400, 320)
        self.window.configure(bg=BLUE)

        # 完全无边框（无 DWM 圆角）+ 置顶
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)

        # 工具窗口（不在任务栏显示）
        hwnd = self._get_hwnd()
        if hwnd:
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ex |= WS_EX_TOOLWINDOW
            ex &= ~WS_EX_APPWINDOW
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)

        self._drag_data = {"x": 0, "y": 0, "dragging": False}
        self._need_focus = False

        self._build_ui()

        # 全局热键
        keyboard.add_hotkey(HOTKEY, self.toggle)

        # 窗口事件
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self.window.bind("<Escape>", lambda e: self.hide())
        self.window.bind("<Control-h>", lambda e: self.toggle())
        self.window.bind("<Button-2>", lambda e: self.toggle())

        self._poll_queue()
        self.window.withdraw()

    def _get_hwnd(self):
        try:
            return user32.GetParent(self.window.winfo_id())
        except Exception:
            return None

    def _bind_drag(self, widget):
        """让一个 widget 支持窗口拖拽"""
        widget.bind("<Button-1>", self._drag_start)
        widget.bind("<B1-Motion>", self._drag_move)
        widget.bind("<ButtonRelease-1>", self._drag_stop)

    # ── UI 构建 ──

    def _build_ui(self):
        outer = tk.Frame(self.window, bg=BLUE)
        outer.pack(fill="both", expand=True)

        # ══ 标题栏（可拖拽） ══
        tb = tk.Frame(outer, bg=BLUE, height=32)
        tb.pack(fill="x")
        tb.pack_propagate(False)
        self._bind_drag(tb)

        logo = tk.Label(tb, text="⚡", font=("Segoe UI", 14, "bold"),
                        bg=BLUE, fg=TEXT)
        logo.pack(side="left", padx=(12, 4))
        self._bind_drag(logo)

        title = tk.Label(tb, text="Hermes  Quick  Ask",
                         font=("Segoe UI", 11, "bold"), bg=BLUE, fg=TEXT)
        title.pack(side="left")
        self._bind_drag(title)

        self._close_btn = tk.Label(tb, text="✕", font=("Segoe UI", 11, "bold"),
                                   bg=BLUE, fg=TEXT_DIM, padx=10, pady=2)
        self._close_btn.pack(side="right", padx=(0, 8))
        self._close_btn.bind("<Button-1>", lambda e: self._on_close())
        self._close_btn.bind("<Enter>",
                             lambda e: self._close_btn.configure(bg=HOVER))
        self._close_btn.bind("<Leave>",
                             lambda e: self._close_btn.configure(bg=BLUE))

        # ══ 提示 + 模型切换 ══
        info = tk.Frame(outer, bg=BLUE)
        info.pack(fill="x", padx=14, pady=(0, 6))

        tk.Label(info, text="Ctrl+H · Enter 发送 · Esc 隐藏",
                 font=("Segoe UI", 9), bg=BLUE, fg=TEXT_MUTED).pack(side="left")

        mf = tk.Frame(info, bg=BLUE)
        mf.pack(side="right")
        tk.Label(mf, text="Model:", font=("Segoe UI", 9),
                 bg=BLUE, fg=TEXT_MUTED).pack(side="left", padx=(0, 4))

        self.model_var = tk.StringVar(value=self._current_model)
        menu = tk.OptionMenu(mf, self.model_var, *MODELS,
                             command=self._on_model_change)
        menu.configure(bg=MODEL_BG, fg=TEXT,
                       activebackground=HOVER, activeforeground=TEXT,
                       highlightthickness=0, bd=0, relief="flat",
                       font=("Segoe UI", 9))
        menu["menu"].configure(bg=MENU_BG, fg=TEXT,
                               activebackground=MENU_HOVER, activeforeground=TEXT)
        menu.pack(side="left")

        # ══ 输入框 ══
        inp_bg = tk.Frame(outer, bg=INPUT_BG)
        inp_bg.pack(fill="x", padx=14, pady=(0, 6))

        self.input_entry = tk.Text(
            inp_bg, font=("Segoe UI", 12),
            bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, height=3,
            wrap="word", relief="flat", bd=6, padx=8, pady=8,
            selectbackground=SELECT, selectforeground=TEXT, highlightthickness=0,
        )
        self.input_entry.pack(fill="both", expand=True)

        self._placeholder = True
        self._set_placeholder()
        self.input_entry.bind("<FocusIn>", self._on_focus_in)
        self.input_entry.bind("<FocusOut>", self._on_focus_out)
        self.input_entry.bind("<Return>", self._on_submit)

        # ══ 底部按钮区 ══
        actions = tk.Frame(outer, bg=BLUE)
        actions.pack(fill="x", padx=14, pady=(0, 6))

        send_btn = tk.Label(actions, text="↵  Send",
                            font=("Segoe UI", 10, "bold"),
                            bg=HOVER, fg=TEXT, padx=14, pady=5)
        send_btn.pack(side="left")
        send_btn.bind("<Button-1>", lambda e: self._on_submit(None))
        send_btn.bind("<Enter>", lambda e: send_btn.configure(bg=SELECT))
        send_btn.bind("<Leave>", lambda e: send_btn.configure(bg=HOVER))

        self.status_label = tk.Label(actions, text="● Ready",
                                     font=("Segoe UI", 9), bg=BLUE, fg="#80ff80")
        self.status_label.pack(side="right")

        # ══ 输出区标题 ══
        oh = tk.Frame(outer, bg=BLUE)
        oh.pack(fill="x", padx=14, pady=(0, 2))
        tk.Label(oh, text="Output", font=("Segoe UI", 9, "bold"),
                 bg=BLUE, fg=TEXT_DIM).pack(side="left")

        self.line_count = tk.Label(oh, text="0 lines",
                                   font=("Segoe UI", 9), bg=BLUE, fg=TEXT_MUTED)
        self.line_count.pack(side="right", padx=(0, 4))

        clear_btn = tk.Label(oh, text="Clear", font=("Segoe UI", 9),
                             bg=BLUE, fg=TEXT_DIM, padx=6)
        clear_btn.pack(side="right")
        clear_btn.bind("<Button-1>", lambda e: self._clear_output())
        clear_btn.bind("<Enter>", lambda e: clear_btn.configure(bg=HOVER))
        clear_btn.bind("<Leave>", lambda e: clear_btn.configure(bg=BLUE))

        # ══ 输出框 ══
        oc = tk.Frame(outer, bg=OUTPUT_BG)
        oc.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        font_mono = "Cascadia Code" if "Cascadia" in [
            f for f in tkfont.families() if "Cascadia" in f] else "Consolas"
        self.output_text = tk.Text(
            oc, font=(font_mono, 10),
            bg=OUTPUT_BG, fg=TEXT,
            wrap="word", relief="flat", bd=6, padx=8, pady=6,
            state="disabled",
            selectbackground=SELECT, selectforeground=TEXT, highlightthickness=0,
        )
        self.output_text.pack(fill="both", expand=True)

    # ── 占位符 ──

    def _set_placeholder(self):
        if self._placeholder:
            self.input_entry.insert("1.0", "输入你的需求...")
            self.input_entry.configure(fg=TEXT_MUTED)

    def _on_focus_in(self, event=None):
        if self._placeholder:
            self.input_entry.delete("1.0", "end")
            self._placeholder = False
            self.input_entry.configure(fg=TEXT)

    def _on_focus_out(self, event=None):
        if not self.input_entry.get("1.0", "end-1c").strip():
            self._placeholder = True
            self._set_placeholder()

    # ── 拖拽 ──

    def _drag_start(self, event):
        self._drag_data["x"] = event.x_root
        self._drag_data["y"] = event.y_root
        self._drag_data["dragging"] = True

    def _drag_move(self, event):
        if not self._drag_data["dragging"]:
            return
        dx = event.x_root - self._drag_data["x"]
        dy = event.y_root - self._drag_data["y"]
        x = self.window.winfo_x() + dx
        y = self.window.winfo_y() + dy
        self.window.geometry(f"+{int(x)}+{int(y)}")
        self._drag_data["x"] = event.x_root
        self._drag_data["y"] = event.y_root

    def _drag_stop(self, event):
        self._drag_data["dragging"] = False

    # ── 模型 ──

    def _on_model_change(self, val):
        self._current_model = val

    # ── 提交 ──

    def _on_submit(self, event):
        if event and (event.state & 0x0001):
            return
        if self._running:
            return
        text = self.input_entry.get("1.0", "end-1c").strip()
        if not text or self._placeholder:
            return
        self._send_request(text)
        if event:
            return "break"

    def _send_request(self, text: str):
        self._running = True
        self.status_label.configure(text="● Working...", fg="#f5f5a0")
        self.input_entry.configure(state="normal")
        self.input_entry.delete("1.0", "end")
        self.input_entry.configure(state="disabled")
        t = threading.Thread(target=self._run_query,
                             args=(text, self._current_model), daemon=True)
        t.start()

    def _run_query(self, text: str, model: str):
        try:
            result = _ask_hermes(text, model)
        except Exception as e:
            result = f"[错误] {e}"
        self.queue.put(("result", (text, result)))

    def _handle_result(self, data):
        self._running = False
        self.status_label.configure(text="● Done", fg="#80ff80")
        self.input_entry.configure(state="normal")

        query, result = data
        display = f"> {query}\n\n{result}"

        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", display)
        self.output_text.configure(state="disabled")
        self.line_count.configure(text=f"{display.count(chr(10)) + 1} lines")
        self.window.after(2000, lambda: self.status_label.configure(
            text="● Ready", fg="#80ff80"
        ))

    def _clear_output(self):
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.configure(state="disabled")
        self.line_count.configure(text="0 lines")

    def _poll_queue(self):
        try:
            while True:
                msg_type, data = self.queue.get_nowait()
                if msg_type == "result":
                    self._handle_result(data)
        except queue.Empty:
            pass
        # 焦点抢取由主线程执行（keyboard 回调在后台线程）
        if self._need_focus:
            self._need_focus = False
            self._grab_focus()
        self.window.after(50, self._poll_queue)

    # ── 显示 / 隐藏 / 焦点 ──

    def toggle(self):
        if self._visible:
            self.hide()
        else:
            self.show()

    def show(self):
        self._visible = True
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
        self._center_window()
        self._need_focus = True
        if not self._placeholder:
            self.input_entry.see("end")

    def hide(self):
        self._visible = False
        self.window.withdraw()

    def _grab_focus(self):
        hwnd = self._get_hwnd()
        if not hwnd:
            return
        # 输入队列挂接到前台窗口线程，突破 Windows 焦点保护
        fore = user32.GetForegroundWindow()
        ftid = c_uint()
        user32.GetWindowThreadProcessId(fore, byref(ftid))
        ctid = kernel32.GetCurrentThreadId()
        attached = ftid.value and ftid.value != ctid
        if attached:
            user32.AttachThreadInput(ftid, ctid, True)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)
        self.window.focus_force()
        self.input_entry.focus_set()
        if attached:
            user32.AttachThreadInput(ftid, ctid, False)

    def _center_window(self):
        self.window.update_idletasks()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 3
        self.window.geometry(f"+{x}+{y}")

    def _on_close(self):
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        _release_lock()
        self.window.quit()
        self.window.destroy()


# ── 入口 ─────────────────────────────────────────────────
def main():
    if not _acquire_lock():
        return

    print("⚡ Hermes Quick Ask (纯蓝无边框)")
    print(f"   热键: {HOTKEY}")
    print(f"   当前模型: {_get_default_model()}")
    print("   按 Ctrl+H 弹出窗口")

    app = HermesQuickWindow()
    try:
        app.window.mainloop()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[错误] {e}")
        import traceback
        traceback.print_exc()
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
