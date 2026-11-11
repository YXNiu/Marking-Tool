#!/bin/bash
set -e
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "尚未创建 Python 环境，请按 README 的安装步骤创建 .venv。"
  read -r -p "按回车退出。" _answer
  exit 1
fi
exec .venv/bin/python main.py "$@"
