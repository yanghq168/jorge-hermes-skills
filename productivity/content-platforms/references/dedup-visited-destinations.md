# 小红书旅游景点去重机制

## 背景

两个小红书旅游脚本各自维护独立的目的地池，每天随机选取。若不加追踪，同一景点可能短期内反复出现，用户明确表示不希望重复。

## 实现方案

在每个脚本头部插入一个 `_pick_unvisited()` 函数，配合 JSON 文件追踪已推送过的景点。

### 代码模板

```python
import json
import os

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_VISITED_FILE = os.path.join(_SCRIPT_DIR, '.xhs_travel_visited.json')

def _load_visited():
    if os.path.exists(_VISITED_FILE):
        try:
            with open(_VISITED_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def _save_visited(visited):
    with open(_VISITED_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(visited), f, ensure_ascii=False, indent=2)

def _pick_unvisited(destinations):
    visited = _load_visited()
    unvisited = [d for d in destinations if d['name'] not in visited]
    if not unvisited:
        visited.clear()  # 全部用完，重置
        unvisited = destinations
    dest = random.choice(unvisited)
    visited.add(dest['name'])
    _save_visited(visited)
    return dest
```

### 使用方式

将原来的：
```python
dest = random.choice(DESTINATIONS)
```
替换为：
```python
dest = _pick_unvisited(DESTINATIONS)
```

## 追踪文件

每个脚本对应独立的 JSON 文件，互不干扰：

| 脚本 | 目的地数 | 追踪文件 |
|------|---------|---------|
| `xhs-travel-daily.py`（21:30，长期旅游攻略） | 19 | `.xhs_travel_visited.json` |
| `xhs-escape-weekend.py`（10:00，周末出逃） | 13 | `.xhs_escape_visited.json` |

## 重置逻辑

当所有目的地均被推送过（visited == len(destinations)），清空visited集合，重新从全部目的地中随机选取，实现循环覆盖。

## 验证方法

```bash
# 查看已访问记录
cat ~/.hermes/cron/scripts/.xhs_travel_visited.json

# 测试脚本（不发送邮件，只看选中了哪个目的地）
python3 -c "
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/cron/scripts')
import xhs_travel_daily as m
print('可用目的地:', len(m.DESTINATIONS))
"
```