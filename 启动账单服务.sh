#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin="$project_dir/.venv/bin/python"

if [[ ! -x "$python_bin" ]]; then
    printf '项目虚拟环境未就绪：%s\n' "$python_bin" >&2
    printf '请先在项目目录运行：python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt\n' >&2
    exit 1
fi

cd "$project_dir"
if "$python_bin" "$project_dir/scripts/launch.py"; then
    exit 0
else
    launch_status=$?
    printf '\n启动未完成（退出码 %s），请查看上面的原因。\n' "$launch_status" >&2
    if [[ -t 0 ]]; then
        read -r -p '按回车关闭窗口…' || true
    fi
    exit "$launch_status"
fi
