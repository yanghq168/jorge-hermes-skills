# 小红书旅游景点去重机制

## 背景

两个小红书旅游脚本各自维护独立的目的地池，每天随机选取。若不加追踪，同一景点可能短期内反复出现，用户明确表示不希望重复。

## 当前实现（v2：搜索新目的地，2026-06 升级）

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

def _search_new_destinations(exclude_names, count=5):
    """库内全部用完后，从百度搜索新景点（占位条目）"""
    # 真实实现见 xhs-travel-daily.py 第 37-91 行
    # 1. 随机抽取一个搜索 query（"2024 2025 国内小众旅游景点"等）
    # 2. urllib.request 抓取百度搜索结果 HTML
    # 3. 用正则提取 [中文]省/市/景区/古镇/古城/草原/雪山/湖泊 等地名
    # 4. 去重 + 排除已用过的，返回随机一个
    # 5. 若搜索失败，返回 None（让外层 fallback）
    pass

def _pick_unvisited(destinations):
    visited = _load_visited()
    unvisited = [d for d in destinations if d['name'] not in visited]
    if not unvisited:
        # 库内全部用完：先去网上搜新景点
        new_dest = _search_new_destinations(visited)
        if new_dest:
            visited.add(new_dest['name'])
            _save_visited(visited)
            return new_dest
        # 搜索失败时 fallback：用全库（允许短期重复，比"无景点可推"好）
        unvisited = destinations
    dest = random.choice(unvisited)
    visited.add(dest['name'])
    _save_visited(visited)
    return dest
```

### 关键变化（相对于 v1）

| 行为 | v1（旧） | v2（现） |
|------|---------|---------|
| 库用完后处理 | `visited.clear()` 重置 | 优先调用 `_search_new_destinations()` 抓新景点 |
| 搜索失败时 | N/A | Fallback 用全库（允许短期重复） |
| 搜索来源 | N/A | 百度网页 + 正则提取地名 |
| 搜索 query 池 | N/A | `["2024 2025 国内小众旅游景点 推荐", "冷门但惊艳的国内旅行地", "被忽视的宝藏旅行目的地 国内"]` |
| 抽取规则 | N/A | 用正则 `[\u4e00-\u9fa5]{2,8}(?:省\|市\|县\|镇\|景区\|风景区\|度假区\|海岛\|沙滩\|古镇\|古城\|草原\|雪山\|冰川\|湖泊)` 抽取 |

> ⚠️ 搜索得到的新景点数据是"占位骨架"（location/days/season 都是默认值），用户体验会下降。生产环境建议人工补全后再纳入 DESTINATIONS 主库。

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
| `xhs-travel-daily.py`（**23:00**，长期旅游攻略） | 19 | `.xhs_travel_visited.json` |
| `xhs-escape-weekend.py`（10:00，周末出逃） | 13 | `.xhs_escape_visited.json` |

## 重置逻辑

**v1（已废弃）**：visited == len(destinations) 时 `visited.clear()` 重置循环。
**v2（当前）**：visited == len(destinations) 时优先 `_search_new_destinations()`，失败再 fallback 到全库。**visited 不会自动清空**。若发现景点池严重不足，需手动：
1. 编辑脚本，扩充 `DESTINATIONS` 列表
2. 编辑 `.xhs_travel_visited.json`，移除已推送过但希望重新推送的景点

## 监控推荐目的地耗尽

```bash
# 查看已访问记录
cat ~/.hermes/cron/scripts/.xhs_travel_visited.json

# 统计已用/总数
python3 -c "
import sys, json
sys.path.insert(0, '/home/ubuntu/.hermes/cron/scripts')
import xhs_travel_daily as m
visited = set(json.load(open('/home/ubuntu/.hermes/cron/scripts/.xhs_travel_visited.json')))
print(f'已用: {len(visited)}/{len(m.DESTINATIONS)}')
print(f'未用: {[d[\"name\"] for d in m.DESTINATIONS if d[\"name\"] not in visited]}')
"
```

## 验证方法

```bash
# 测试脚本（不发送邮件，只看选中了哪个目的地）
python3 -c "
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/cron/scripts')
import xhs_travel_daily as m
print('可用目的地:', len(m.DESTINATIONS))
"
```
