"""账单流水线的入口。运行 .venv/bin/python main.py，然后打开 http://127.0.0.1:8080"""
from nicegui import ui

from web.pages import register

register()

if __name__ in {"__main__", "__mp_main__"}:
    # 明确只监听本机：NiceGUI 默认监听 0.0.0.0，同一网络里的人都能打开
    ui.run(host="127.0.0.1", port=8080, title="账单流水线", reload=False)
