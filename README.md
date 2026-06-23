# ⚡ Hermes Quick Ask

A borderless quick-input tool for **Hermes Agent** — press `Ctrl+H` anywhere to pop up a small window, type your question, and get an answer instantly from Hermes CLI.

---

## Features

- **Global hotkey** `Ctrl+H` — works in any app
- **Borderless pure-blue UI** — overrideredirect, no title bar, no window frame
- **Model selector** — switch between models on the fly
- **Auto-cleanup** — each query creates a throwaway Hermes session that is deleted immediately after the response
- **Single instance** — only one process runs at a time
- **Auto-start on boot** — installs a Startup shortcut on first run
- **Draggable** — drag by the title bar area

## Requirements

- Windows 10+
- Python 3.10+
- [Hermes Agent](https://hermes-agent.nousresearch.com) installed and `hermes.exe` on `PATH`
- `tkinter` (included with the standard Python installer — check the "tcl/tk and IDLE" option)
- `keyboard` library (`pip install keyboard`)

## Quick Start

```bash
# 1. Install Python dependency
pip install keyboard

# 2. Run
python hermes-quick.py
```

Press **Ctrl+H** to show/hide the window. Type your query and press **Enter** to send.

The output box displays the response. Press **Ctrl+H** again or **Esc** to hide.

## Startup

The script automatically adds itself to Windows Startup (`shell:startup`) on first run so it launches with every login.

## Project Structure

```
hermes-quick-ask/
├── hermes-quick.py      # Main application
├── requirements.txt     # Python dependencies
├── README.md            # This file
└── .gitignore           # Git ignore rules
```

## How It Works

1. `keyboard.add_hotkey` registers a global `Ctrl+H` listener
2. On hotkey: the window toggles via `tkinter` (borderless, always-on-top)
3. On submit: a background thread calls `hermes.exe chat -q` with the query
4. The response is parsed, the temp `session_id` is extracted and deleted via `hermes sessions delete`
5. The result is displayed in the output box

## License

MIT

---

## Upload to GitHub

```bash
# From the project directory (C:\Users\16281\Desktop\hermes-quick-ask)
git init
git add .
git commit -m "Initial commit: Hermes Quick Ask borderless input tool"

# 1. Create a NEW repo on https://github.com (no README, no .gitignore, no license)
# 2. Then run:
git remote add origin https://github.com/YOUR_USERNAME/hermes-quick-ask.git
git branch -M main
git push -u origin main
```

> **Note:** Replace `YOUR_USERNAME` with your GitHub username.
> The lock file (`.hermes_quick_ask.lock`) is runtime-only and is already in `.gitignore`.

