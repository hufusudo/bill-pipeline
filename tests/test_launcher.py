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
