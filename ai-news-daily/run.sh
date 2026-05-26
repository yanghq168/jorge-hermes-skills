#!/bin/bash
# AI 新闻日报运行脚本 - Hermes 兼容版

cd "$(dirname "$0")"
python3 src/daily_fetch.py "$@"
