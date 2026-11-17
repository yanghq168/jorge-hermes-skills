#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨夜同故事碰撞验证器（通用）—— 检测 + 反向验证，零生产污染。

解决什么问题
------------
「长文 ↔ 微头条」两个池 LRU 同步推进 ⇒ 同一个故事内核会在**不同夜晚**
落到读者面前（读者连续两封邮件读同一个故事 = 订阅体验最伤的失败）。
现有规则全都只查「单篇内的重复」和「单字段内的算式」，查不到跨夜关系。

**关键：只跑「现在碰撞 0 次」证明不了任何事** —— 它无法区分
「改好了」与「检测器坏了」。本脚本支持 **--before-config** 反向对照：
用同一份种子 history、同一段模拟、同一份检测口径，只换池/映射/守卫参数，
跑出「修复前」与「修复后」两组数据。

用法
----
  # 基本检测（当前生产配置）
  python3 verify_cross_night_collisions.py \
      --pool ~/.hermes/cron/scripts/toutiao-article-daily.py \
      --nights 60

  # 反向验证：跑「修复前」配置作对照（池/映射/守卫全换成旧的）
  python3 verify_cross_night_collisions.py \
      --pool ~/.hermes/cron/scripts/toutiao-article-daily.py \
      --nights 60 --before-script /tmp/bak_toutiao-article-daily.py

  # 池型分叉：微头条正文在 `content`、长文在 `story_a`/`story_b`
  #（本脚本只读方向/标题，不需要正文，故与池型无关）

退出码
------
  0 = 跑完（碰撞数在 --max-collisions 内）
  1 = 碰撞数超标（有跨夜孪生故事）
  2 = 工具自身问题（脚本加载失败 / 池结构不符 / 参数用错）

⚠️ 本脚本**只读**生产 history（拷贝到临时目录后再模拟），不写生产文件。
   每次 simulate() 都用 shutil.copy 从生产 history 重置种子，
   保证「修复前」与「修复后」两组数据起点一致、可比。
"""

import argparse
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from collections import Counter

SHADOW_MAP_ATTR = 'SHADOW_MAP'
GUARD_ATTR = 'SHADOW_GUARD_NIGHTS'
LONG_POOL_ATTR = 'TOPICS_POOL'
MICRO_POOL_ATTR = 'MICRO_TOPICS_POOL'


def load_module(path, name):
    """加载生产脚本（文件名带连字符 ⇒ 不能直接 import）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError('无法加载: %s' % path)
    mod = importlib.util.module_from_spec(spec)
    # 扩库模块用 __file__ 定位，测试时 cwd 可能不同 ⇒ 显式插入脚本目录
    d = os.path.dirname(os.path.abspath(path))
    if d not in sys.path:
        sys.path.insert(0, d)
    spec.loader.exec_module(mod)
    return mod


def read_dirs(mod, attr):
    return [str(t.get('direction')) for t in getattr(mod, attr)]


def simulate(mod, prod_hist, prod_micro, micro_pool=None, shadow_map=None,
             guard=None, nights=60, per_night_micro=2):
    """跑 N 夜，返回每夜的 (长文方向, [微头条方向...])。

    每轮都从生产 history 复制种子 ⇒ 多组配置起点一致、可比。
    """
    tmp = tempfile.mkdtemp(prefix='xnight_')
    H = os.path.join(tmp, 'topic_history.json')
    M = os.path.join(tmp, 'micro_topic_history.json')
    try:
        # 记录原始配置，便于还原
        orig = {
            MICRO_POOL_ATTR: getattr(mod, MICRO_POOL_ATTR),
            SHADOW_MAP_ATTR: getattr(mod, SHADOW_MAP_ATTR),
            GUARD_ATTR: getattr(mod, GUARD_ATTR),
        }
        if micro_pool is not None:
            setattr(mod, MICRO_POOL_ATTR, micro_pool)
        if shadow_map is not None:
            setattr(mod, SHADOW_MAP_ATTR, shadow_map)
        if guard is not None:
            setattr(mod, GUARD_ATTR, guard)

        # history 路径指向临时目录（生产零污染）
        mod.HISTORY_FILE = H
        mod.MICRO_HISTORY_FILE = M

        # 用生产 history 做种子，**只复制一次**然后连续推进 N 夜
        # （每夜都重置种子会让每夜起点相同、模拟失真）
        shutil.copy(prod_hist, H)
        shutil.copy(prod_micro, M)

        out = []
        for _ in range(nights):
            topic = mod._pick_topic(getattr(mod, LONG_POOL_ATTR),
                                    H, key='direction')
            mod._record_topic(H, topic, key='direction')
            micros = mod.generate_micro_articles(long_direction=topic['direction'])
            out.append((topic['direction'], [x['direction'] for x in micros]))

        # 还原
        for k, v in orig.items():
            setattr(mod, k, v)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def count_collisions(nights, shadow_map, lookback):
    """统计跨夜孪生碰撞。

    ⚠️ 回看窗口必须 ≥ 被测池的轮换周期，否则统计一定偏乐观（假绿）。
    """
    collisions = []
    for i in range(len(nights)):
        for back in range(1, lookback + 1):
            j = i - back
            if j < 0:
                break
            long_prev = nights[j][0]
            for md in nights[i][1]:
                if md in shadow_map and shadow_map[md] == long_prev:
                    collisions.append({
                        'night_index': i,
                        'distance': back,
                        'long_direction': long_prev,
                        'micro_direction': md,
                    })
    return collisions


def report(name, nights, shadow_map, lookback, micro_dirs):
    c = count_collisions(nights, shadow_map, lookback)
    long_cov = Counter(n[0] for n in nights)
    micro_cov = Counter(d for _, ds in nights for d in ds)
    same_night = sum(1 for _, ds in nights if len(set(ds)) != len(ds))
    long_consec = sum(1 for i in range(1, len(nights))
                      if nights[i][0] == nights[i - 1][0])
    print('\n=== %s ===' % name)
    print('  长文方向覆盖   : %d/%d' % (len(long_cov), len(set(long_cov))))
    print('  微头条方向覆盖 : %d/%d' % (len(micro_cov), len(set(micro_cov))))
    print('  同夜两条微头条方向相同: %d 夜' % same_night)
    print('  长文方向连续重复      : %d 夜' % long_consec)
    print('  跨夜孪生碰撞 : %d/%d 夜   (回看 %d 夜)' % (len(c), len(nights), lookback))
    for x in c[:10]:
        print('     night#%d 距离%d夜  长文=%s ↔ 微头条=%s'
              % (x['night_index'], x['distance'], x['long_direction'], x['micro_direction']))
    if len(c) > 10:
        print('     ... 另有 %d 处' % (len(c) - 10))
    return c


def main():
    ap = argparse.ArgumentParser(description='跨夜同故事碰撞验证器')
    ap.add_argument('--pool', required=True,
                    help='生产生成器脚本路径（必须是脚本本身，不是池数据文件）')
    ap.add_argument('--nights', type=int, default=60)
    ap.add_argument('--before-script', default=None,
                    help='修复前的旧脚本路径（备份）—— 跑反向对照')
    ap.add_argument('--max-collisions', type=int, default=0,
                    help='允许的最大碰撞数（默认 0）')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    if not os.path.exists(args.pool):
        print('❌ --pool 指向的文件不存在: %s' % args.pool)
        return 2
    try:
        mod = load_module(args.pool, 'xnight_prod')
    except Exception as e:
        print('❌ 加载生产脚本失败: %s' % e)
        return 2

    for attr in (LONG_POOL_ATTR, MICRO_POOL_ATTR, SHADOW_MAP_ATTR, GUARD_ATTR):
        if not hasattr(mod, attr):
            print('❌ 生产脚本缺少属性 %s（--pool 是否指向生成器脚本本身？）' % attr)
            return 2

    # 定位生产 history
    hist_dir = os.path.dirname(os.path.abspath(args.pool))
    prod_hist = mod.HISTORY_FILE
    prod_micro = mod.MICRO_HISTORY_FILE
    for p in (prod_hist, prod_micro):
        if not os.path.exists(p):
            print('❌ 找不到 history 文件: %s' % p)
            return 2

    micro_dirs = read_dirs(mod, MICRO_POOL_ATTR)
    guard = getattr(mod, GUARD_ATTR)
    shadow_map = getattr(mod, SHADOW_MAP_ATTR)
    rotation = max(1, -(-len(micro_dirs) // 2))
    lookback = max(rotation, guard)

    print('长文池 : %s' % ', '.join(read_dirs(mod, LONG_POOL_ATTR)))
    print('微头条池: %s' % ', '.join(micro_dirs))
    print('SHADOW_MAP: %s' % (shadow_map if shadow_map else '(空 —— 池中已无孪生故事)'))
    print('守卫夜数: %d   微头条轮换周期: %d 夜   回看窗口: %d 夜'
          % (guard, rotation, lookback))

    after_nights = simulate(mod, prod_hist, prod_micro, nights=args.nights)
    after_c = report('修复后（当前生产配置）', after_nights, shadow_map, lookback, micro_dirs)

    before_c = None
    if args.before_script:
        if not os.path.exists(args.before_script):
            print('❌ --before-script 不存在: %s' % args.before_script)
            return 2
        try:
            before = load_module(args.before_script, 'xnight_before')
        except Exception as e:
            print('❌ 加载旧脚本失败: %s' % e)
            return 2
        # ⚠️ 不要手搓 stub —— 从备份脚本 import 真实旧池（含 tags/content/hook）
        b_micro = list(getattr(before, MICRO_POOL_ATTR))
        if hasattr(before, 'EXTRA_MICRO_TOPICS'):
            b_micro = b_micro + list(before.EXTRA_MICRO_TOPICS)
        b_shadow = dict(getattr(before, SHADOW_MAP_ATTR, {}) or {})
        b_guard = getattr(before, GUARD_ATTR, 3)
        b_lookback = max(max(1, -(-len(b_micro) // 2)), b_guard)
        before_nights = simulate(mod, prod_hist, prod_micro,
                                 micro_pool=b_micro, shadow_map=b_shadow,
                                 guard=b_guard, nights=args.nights)
        before_c = report('修复前（对照: %s）' % os.path.basename(args.before_script),
                           before_nights, b_shadow, b_lookback, b_micro)

    if args.json:
        print(json.dumps({
            'after_collisions': len(after_c),
            'before_collisions': len(before_c) if before_c is not None else None,
            'nights': args.nights,
            'lookback': lookback,
            'guard': guard,
            'rotation_period': rotation,
        }, ensure_ascii=False, indent=2))

    if before_c is not None:
        print('\n🔬 反向对照：修复前 %d 处 → 修复后 %d 处'
              % (len(before_c), len(after_c)))
        if len(before_c) == 0:
            print('⚠️ 修复前也是 0 ⇒ 本次对照无法证明改动带来了行为变化'
                  '（检测口径可能有问题，或本来就没碰撞）')

    if len(after_c) > args.max_collisions:
        print('\n❌ 跨夜孪生碰撞 %d 处 > 允许值 %d' % (len(after_c), args.max_collisions))
        return 1
    print('\n✅ 跨夜孪生碰撞检查通过（%d/%d 夜）' % (len(after_c), args.nights))
    return 0


if __name__ == '__main__':
    sys.exit(main())