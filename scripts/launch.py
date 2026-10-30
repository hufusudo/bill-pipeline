"""本机启动入口：复用已有账单服务，避免双击重复占用端口。"""
import errno
import html
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser

ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:8080/'


def server_state():
    try:
        # 本机请求不经过用户配置的远端代理。
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL,timeout=3) as response:
            page=response.read(65536).decode('utf-8',errors='replace')
            title=re.search(r'<title[^>]*>(.*?)</title>',page,re.S|re.I)
            return 'ours' if title and html.unescape(title.group(1)).strip()=='账单流水线' else 'other'
    except urllib.error.HTTPError:
        return 'other'
    except urllib.error.URLError as error:
        return 'closed' if getattr(error.reason,'errno',None)==errno.ECONNREFUSED else 'other'
    except (TimeoutError,OSError):
        return 'other'


def main():
    state=server_state()
    if state=='ours':
        print('账单服务已经在运行，无需重复启动。',flush=True)
        print('打开：'+URL,flush=True)
        if not os.environ.get('BILL_LAUNCH_NO_BROWSER'):
            webbrowser.open(URL)
        return 0
    if state=='other':
        print('8080端口被其他程序占用，或该端口的服务暂时不可访问。',flush=True)
        print('没有停止任何现有程序。请先检查：'+URL,flush=True)
        return 1
    print('正在启动账单流水线…\n服务地址：'+URL+'\n按 Ctrl+C 停止服务。\n',flush=True)
    try:
        return subprocess.call([sys.executable,str(ROOT/'main.py')],cwd=ROOT)
    except KeyboardInterrupt:
        print('\n服务已停止。',flush=True)
        return 0


if __name__=='__main__':
    raise SystemExit(main())
