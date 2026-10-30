import shutil
import subprocess
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]


def test_desktop_entry_valid():
    validator=shutil.which('desktop-file-validate')
    if not validator:pytest.skip('desktop validator not installed')
    result=subprocess.run([validator,str(ROOT/'启动账单服务.desktop')],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_running_service_is_reused(monkeypatch,capsys):
    from scripts import launch
    opened=[]
    monkeypatch.setattr(launch,'server_state',lambda:'ours')
    monkeypatch.setattr(launch.webbrowser,'open',lambda url:opened.append(url))
    monkeypatch.setattr(launch.subprocess,'call',lambda *a,**k:pytest.fail('must not duplicate service'))
    assert launch.main()==0
    assert opened==[launch.URL]
    assert '已经在运行' in capsys.readouterr().out


def test_other_service_not_stopped_or_reused(monkeypatch,capsys):
    from scripts import launch
    monkeypatch.setattr(launch,'server_state',lambda:'other')
    monkeypatch.setattr(launch.subprocess,'call',lambda *a,**k:pytest.fail('must not start second server'))
    assert launch.main()==1
    assert '其他程序' in capsys.readouterr().out


def test_new_service_uses_project_python_and_directory(monkeypatch):
    from scripts import launch
    calls=[]
    monkeypatch.setattr(launch,'server_state',lambda:'closed')
    monkeypatch.setattr(launch.subprocess,'call',lambda args,**kw:(calls.append((args,kw)) or 0))
    assert launch.main()==0
    assert calls[0][0]==[launch.sys.executable,str(ROOT/'main.py')]
    assert calls[0][1]['cwd']==ROOT


def test_interactive_start_restarts_into_current_terminal(monkeypatch,capsys):
    from scripts import launch
    actions=[]
    monkeypatch.setattr(launch,'server_state',lambda:'ours')
    monkeypatch.setattr(launch.sys.stdin,'isatty',lambda:True)
    monkeypatch.setattr(launch,'service_pid',lambda:123)
    monkeypatch.setattr('builtins.input',lambda prompt:'')
    monkeypatch.setattr(launch,'restart_service',lambda pid:(actions.append(('restart',pid)) or True))
    monkeypatch.setattr(launch.subprocess,'call',lambda *a,**kw:(actions.append(('foreground',None)) or 0))
    assert launch.main()==0
    assert actions==[('restart',123),('foreground',None)]
    assert 'Ctrl+C' in capsys.readouterr().out


def test_unverified_owner_is_never_stopped(monkeypatch):
    from scripts import launch
    monkeypatch.setattr(launch,'server_state',lambda:'ours')
    monkeypatch.setattr(launch.sys.stdin,'isatty',lambda:True)
    monkeypatch.setattr(launch,'service_pid',lambda:None)
    monkeypatch.setattr('builtins.input',lambda prompt:'')
    monkeypatch.setattr(launch,'restart_service',lambda pid:pytest.fail('unverified process'))
    assert launch.main()==1


def test_ctrl_c_is_normal_shutdown_without_traceback(monkeypatch):
    import runpy
    from nicegui import ui
    monkeypatch.setattr('web.pages.register',lambda:None)
    def interrupt(**kwargs):raise KeyboardInterrupt()
    monkeypatch.setattr(ui,'run',interrupt)
    runpy.run_path(str(ROOT/'main.py'),run_name='__main__')
