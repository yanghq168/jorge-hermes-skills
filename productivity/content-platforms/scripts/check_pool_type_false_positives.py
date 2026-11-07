#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨池型假阳性检测器 —— 2026-11-07 实测新增。

## 为什么需要这个脚本

给 `lint_content_consistency.py` 新增检查规则时，本技能此前只要求两步验证：
  ① 正例不报（干净内容 exit 0）
  ② 反例必报（造真反例，断言 exit 1 + 报出预期 code）

2026-11-07 落地 `HOOK_PROMISE` 规则时，这两步**都过了**，
但规则立刻产生了 **14 处假阳性**（15 处命中里只有 1 处是真缺陷）。

根因：规则自己的装配函数 `_hook_promise_body()` 只认 `story_a`/`story_b` 系列字段，
而**微头条池 `MICRO_TOPICS_POOL` 根本没有这些字段** —— 它的正文在 `content`。
微头条的「正文」被装配成空串 → 钩子/标题里的每个数字都判成「未兑现」。

## 本脚本做什么

对**每一个**选题池，按该池自己的正文字段装配出「正文」，
再把 linter 报的命中项与该池正文的对照**一起打出来**，供人工逐条核对。

关键点：**不要只看汇总数**。汇总数（15）会让人以为是 15 个缺陷，实际只有 1 个。
本脚本的输出是「命中项 + 该池正文片段」并排，方便一眼看出是真缺陷还是装配口径漏了。

## 用法

    python3 check_pool_type_false_positives.py \
        --pool ~/.hermes/cron/scripts/toutiao-article-daily.py \
        --extensions ~/.hermes/cron/scripts/toutiao_story_extensions.py \
        --rule HOOK_PROMISE

    # --json 机器可读

## 退出码

  0 = 跑完了（不代表无假阳性 —— 必须人工核对输出）
  2 = 工具自己坏了（装配不出正文 / 模块加载失败）
"""
import argparse
import importlib.util
import json
import os
import re
import sys

CJK_RE = re.compile(r'[\u4e00-\u9fff]')


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _discover_pools(mod):
    """找出模块里的选题池（list[dict]，含 direction / title 键）。"""
    pools = []
    for attr in ('TOPICS_POOL', 'MICRO_TOPICS_POOL', 'EXTRA_TOPICS',
                 'EXTRA_MICRO_TOPICS'):
        val = getattr(mod, attr, None)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            pools.append((attr, val))
    return pools


def _ext_pair(ext):
    """扩写值 → (a, b)。兼容 tuple/list 二元组与单字符串。"""
    if isinstance(ext, (tuple, list)):
        a = ext[0] if len(ext) > 0 else ''
        b = ext[1] if len(ext) > 1 else ''
        return (a or ''), (b or '')
    if isinstance(ext, str):
        return ext, ''
    return '', ''


def _load_extensions(path, script_dir):
    if not path:
        return {}
    if not os.path.isfile(path):
        return {}
    mod = _load(path, '_ext_mod')
    for attr in ('STORY_EXTENSIONS', 'EXTENSIONS', 'STORY_EXTENSION_MAP'):
        val = getattr(mod, attr, None)
        if isinstance(val, dict) and val:
            return val
    # 同目录 import 兜底
    stem = os.path.splitext(os.path.basename(path))[0]
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    try:
        m = __import__(stem)
    except Exception:
        return {}
    for attr in ('STORY_EXTENSIONS', 'EXTENSIONS'):
        val = getattr(m, attr, None)
        if isinstance(val, dict) and val:
            return val
    return {}


def body_for(topic, ext):
    """**按池型分叉**装配正文 —— 这正是 HOOK_PROMISE 最初漏掉的那一步。

    微头条池：正文在 `content` + `micro_dialogue`。
    长文池：  正文在 story_a / story_a_dialogue / story_a_ending /
               story_b / story_b_ending + 对应扩写段。
    """
    def g(k):
        return str(topic.get(k, '') or '')

    if g('content'):
        return '\n'.join(x for x in (g('content'), g('micro_dialogue')) if x)

    ea, eb = _ext_pair(ext) if ext else ('', '')
    body = '\n'.join(x for x in (g('story_a'), g('story_a_dialogue'),
                                  g('story_a_ending'), g('story_b'),
                                  g('story_b_ending')) if x)
    if ea:
        body += '\n' + ea
    if eb:
        body += '\n' + eb
    return body


def _quotes(text):
    qre = re.compile(r"'([^']{2,80})'|\"([^\"]{2,80})\"|「([^」]{2,80})」|『([^』]{2,80})』")
    out = []
    for a, b, c, d in qre.findall(text or ''):
        q = a or b or c or d
        if q and len(CJK_RE.findall(q)) >= 2:
            out.append(q)
    return out


def _nums(text):
    return re.findall(r'\d+(?:\.\d+)?', text or '')


NUM_IGNORE = {'2024', '2025', '2026', '2027'}


def check_hook_promise(hook, title, body):
    """与 linter 里的同名函数保持同口径（复刻以便独立核对）。"""
    issues = []
    body = body or ''
    src = (hook or '') + ' || ' + (title or '')
    for q in _quotes(src):
        if q not in body:
            issues.append(('HOOK_PROMISE', f'引语「{q}」未在正文兑现', q))
    for n in _nums(src):
        if n in NUM_IGNORE:
            continue
        if n not in body:
            issues.append(('HOOK_PROMISE', f'数字「{n}」未在正文兑现', n))
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pool', required=True, help='生成器脚本路径')
    ap.add_argument('--extensions', default='', help='扩写段落模块路径')
    ap.add_argument('--rule', default='HOOK_PROMISE', help='要核对的规则（目前只支持 HOOK_PROMISE）')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    if args.rule != 'HOOK_PROMISE':
        print(f'⚠️ 本脚本目前只复刻了 HOOK_PROMISE（收到 {args.rule}）', file=sys.stderr)

    if not os.path.isfile(args.pool):
        print(f'❌ 找不到 pool 文件: {args.pool}', file=sys.stderr)
        return 2

    script_dir = os.path.dirname(os.path.abspath(args.pool))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    try:
        mod = _load(args.pool, '_pool_mod')
    except Exception as e:
        print(f'❌ 加载 pool 失败: {e}', file=sys.stderr)
        return 2

    ext_map = _load_extensions(args.extensions, script_dir)
    pools = _discover_pools(mod)
    if not pools:
        print('❌ 没找到任何选题池', file=sys.stderr)
        return 2

    results = []
    for pool_name, pool in pools:
        for t in pool:
            direction = t.get('direction', '?')
            ext = ext_map.get(direction)
            body = body_for(t, ext)
            if not body.strip():
                print(f'❌ [{pool_name}] {direction}: 装配不出正文 —— '
                      f'该池的字段结构与本脚本的 body_for() 不匹配（假阳性来源）',
                      file=sys.stderr)
                return 2
            for code, msg, ctx in check_hook_promise(t.get('hook', ''), t.get('title', ''), body):
                results.append({
                    'pool': pool_name,
                    'direction': direction,
                    'title': t.get('title', ''),
                    'code': code,
                    'message': msg,
                    'context': ctx,
                    'body_len': len(body),
                })

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    by_pool = {}
    for r in results:
        by_pool.setdefault(r['pool'], []).append(r)

    print('=' * 72)
    print('跨池型假阳性核对 —— 每条命中都请人工确认是「真缺陷」还是「装配口径漏了」')
    print('=' * 72)
    for pool_name, items in by_pool.items():
        print(f'\n【{pool_name}】命中 {len(items)} 条')
        for r in items:
            print(f'  · [{r["direction"]}] {r["message"]}')
            print(f'    标题：{r["title"][:50]}')
            print(f'    该池正文长度：{r["body_len"]} 字符')
    if not results:
        print('\n✅ 无命中。')
    print('\n⚠️ 汇总数会骗人 —— 逐条核对上面的每一项，再决定改文案还是改规则。')

    return 0


if __name__ == '__main__':
    sys.exit(main())
