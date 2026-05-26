#!/bin/bash
# 每日工作日报运行脚本 - Hermes 兼容版

cd "$(dirname "$0")"
python3 daily_report.py "$@"
