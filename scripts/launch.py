"""本机启动入口：复用已有账单服务，避免双击重复占用端口。"""
import errno
import html
import os
from pathlib import Path
import re
import subprocess
import signal
import sys
import time
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


def service_pid():
    """只识别监听8080、同用户、同项目目录的 main.py。"""
    inodes=set()
    try:
        for line in Path('/proc/net/tcp').read_text().splitlines()[1:]:
            cols=line.split()
            if cols[1]=='0100007F:1F90' and cols[3]=='0A':inodes.add(cols[9])
        matches=[]
        for path in Path('/proc').iterdir():
            if not path.name.isdigit():continue
            try:
                if path.stat().st_uid!=os.getuid() or (path/'cwd').resolve()!=ROOT:continue
                args=(path/'cmdline').read_bytes().decode(errors='replace').split('\0')
                if len(args)<2 or 'python' not in Path(args[0]).name:continue
                script=Path(args[1])
                if (script if script.is_absolute() else ROOT/script).resolve()!=ROOT/'main.py':continue
                if any(os.readlink(fd) in {'socket:['+inode+']' for inode in inodes} for fd in (path/'fd').iterdir()):matches.append(int(path.name))
            except (OSError,ValueError):continue
        return matches[0] if len(matches)==1 else None
    except OSError:
        return None


def restart_service(pid):
    if service_pid()!=pid:
        print('服务进程已变化，未停止任何进程。',flush=True);return False
    os.kill(pid,signal.SIGINT)
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        if server_state()=='closed':return True
        time.sleep(0.2)
    print('旧服务尚未退出，未强制结束进程，请稍后重试。',flush=True)
    return False


def main():
    state=server_state()
    if state=='ours':
        print('账单服务已经在运行。代码更新后需要重启服务，刷新网页不会加载新的后台代码。',flush=True)
        if sys.stdin.isatty():
            print('回车：重启并由当前窗口运行（之后 Ctrl+C 可停止）\no：只打开旧页面（当前窗口不控制旧服务）\nq：退出',flush=True)
            try:choice=input('请选择 [回车重启 / o / q]：').strip().lower()
            except (EOFError,KeyboardInterrupt):return 0
            if choice=='q':return 0
            if choice in ('','r'):
                pid=service_pid()
                if pid is None:
                    print('无法确认旧进程属于本项目，未停止它。',flush=True);return 1
                if not restart_service(pid):return 1
                state='closed'
            elif choice!='o':
                print('未识别选项，未执行操作。',flush=True);return 1
        if state=='ours':
            print('打开：'+URL+'\n当前服务由原进程运行；这个窗口退出不会停止它。',flush=True)
            if not os.environ.get('BILL_LAUNCH_NO_BROWSER'):webbrowser.open(URL)
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
