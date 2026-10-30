#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
审计已渲染的内容产物（HTML）：字数、结构完整性、配图提示词、标签、话题。

用途
----
内容脚本的「发布前检查清单」经常写着「1500 字以上」「配图 5 张」「微头条 150-250 字」，
但这些数字从来没人真的量过（头条号曾连续 60+ 晚每篇只有 813-1159 字而清单写着 1500）。
本脚本对**已渲染的产物**做一次测量，给出可比较的基线，
让下一次会话在改动生成器之前/之后都有客观数字，而不是靠感觉。

两个实战教训（决定了本脚本的形态）
----------------------------------
1. **必须测量「最终装配后的产物」，不是中间返回值。**
   `toutiao-article-daily.py` 的 `generate_article()` 只返回**长文** HTML；
   微头条 HTML 是在 `send_email()` 里才 `html + '\\n'.join(m['html'] for m in micros)` 拼上去的。
   只测 `generate_article()` 的返回值 → 会误判「微头条缺失/渲染失败」。

2. **微头条的字数要测选题池里的 `content` 字段，不是渲染块。**
   渲染块 = content + 对话高亮 + 配图提示词 + 标签。
   实测：content 250 字（合规）→ 渲染块读到 322 字，看起来像违反 250 上限 —— 那是量错了对象。
   真正受 150-250 约束的是 `MICRO_TOPICS_POOL[*]['content']`。

用法
----
    # 审计产物
    python3 audit_rendered_article.py <article.html>

    # 指定要检查的结构标记
    python3 audit_rendered_article.py <article.html> --sections '故事A·对话,观点,金句1'

    # 顺便核对选题池里微头条 content 的字数区间（需要能 import 的脚本）
    python3 audit_rendered_article.py <article.html> --pool /path/to/toutiao-article-daily.py

    # 机器可读
    python3 audit_rendered_article.py <article.html> --json

退出码：0 = 通过（无缺失结构、无越界字数）；1 = 有问题；2 = 用法/IO 错误。
"""

import argparse
import json
import os
import re
import sys

# 需要从正文中剔除的展示型块（它们是给人看的工具区，不是文章正文）
STRIP_CLASSES = [
    'prompt-text',        # 封面/文中配图的英文提示词
    'img-prompt-text',
    'checklist-item',     # 发布前检查清单每一行
    'check-warning',      # 检查警告框
]

DEFAULT_SECTIONS = [
    '故事A·对话', '故事A·结局', '故事B·结局',
    '观点', '行动', '金句1', '金句2', '金句3',
    '互动问题', '话题标签',
]

CN = re.compile(r'[\u4e00-\u9fff]')


def strip_elements(html, class_names):
    """移除带指定 class 的 <div> 元素（含其内容），正确处理嵌套 div。

    用深度计数找配对的 </div>，而不是非贪婪正则 —— 非贪婪会在第一个
    内部 </div> 处截断，把外层容器的尾部漏进正文里，污染字数统计。
    """
    for cls in class_names:
        out = []
        i = 0
        needle = '<div class="%s"' % cls
        while True:
            j = html.find(needle, i)
            if j == -1:
                out.append(html[i:])
                break
            out.append(html[i:j])
            k, depth = j, 0
            while k < len(html):
                nxt_open = html.find('<div', k)
                nxt_close = html.find('</div>', k)
                if nxt_close == -1:
                    k = len(html)
                    break
                if nxt_open != -1 and nxt_open < nxt_close:
                    depth += 1
                    k = nxt_open + 4
                    continue
                depth -= 1
                k = nxt_close + 6
                if depth == 0:
                    break
            i = k
        html = ''.join(out)
    return html


def count_cn(text):
    return len(CN.findall(text))


def measure_micro_blocks(html):
    """统计渲染后的微头条块。

    返回 (数量, 每块的渲染字数)。
    ⚠️ 渲染字数包含对话高亮与配图提示词，**不是** content 字数；
       受 150-250 约束的 content 字数请用 --pool 核对。
    """
    heads = list(re.finditer(r'微头条\s*(\d+)', html))
    blocks = []
    for idx, m in enumerate(heads):
        start = m.start()
        end = heads[idx + 1].start() if idx + 1 < len(heads) else len(html)
        seg = html[start:end]
        # 去掉配图提示词块再数字数，避免英文提示词干扰
        seg = strip_elements(seg, ['prompt-text', 'img-prompt-text'])
        blocks.append(count_cn(re.sub(r'<[^>]+>', '', seg)))
    return len(heads), blocks


def audit_pool(script_path):
    """核对选题池里微头条 content 的字数是否落在 [lo, hi] 区间。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location('audited_script', script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    pool = getattr(mod, 'MICRO_TOPICS_POOL', None)
    if pool is None:
        return {'error': '模块里没有 MICRO_TOPICS_POOL'}

    lo, hi = 150, 250
    rows = []
    for t in pool:
        n = count_cn(t.get('content', ''))
        rows.append({
            'direction': t.get('direction'),
            'chars': n,
            'in_range': lo <= n <= hi,
            'title': t.get('title'),
        })
    return {
        'pool_size': len(pool),
        'range': [lo, hi],
        'out_of_range': [r for r in rows if not r['in_range']],
        'rows': rows,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('html_path')
    ap.add_argument('--sections', default=None,
                    help='逗号分隔的结构标记，默认用内置清单')
    ap.add_argument('--pool', default=None,
                    help='内容脚本路径，用于核对微头条 content 字数')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    if not os.path.isfile(args.html_path):
        print('ERROR: 文件不存在: %s' % args.html_path, file=sys.stderr)
        return 2

    with open(args.html_path, encoding='utf-8') as fh:
        html = fh.read()

    sections = (args.sections.split(',') if args.sections else DEFAULT_SECTIONS)
    sections = [s.strip() for s in sections if s.strip()]

    stripped = strip_elements(html, STRIP_CLASSES)
    plain = re.sub(r'<[^>]+>', '', stripped)
    body_cn = count_cn(plain)
    total_cn = count_cn(re.sub(r'<[^>]+>', '', html))

    missing = [s for s in sections if s not in html]
    micro_count, micro_blocks = measure_micro_blocks(html)

    report = {
        'file': args.html_path,
        'size_bytes': os.path.getsize(args.html_path),
        'body_chinese_chars': body_cn,
        'total_chinese_chars': total_cn,
        'sections_checked': sections,
        'sections_missing': missing,
        'image_prompt_blocks': len(re.findall(r'img-prompt-item', html)),
        'cover_prompt_present': 'cover_prompt' in html or 'cover-prompt' in html,
        'no_text_occurrences': html.count('no text'),
        'hashtag_count': html.count('hashtag'),
        'micro_block_count': micro_count,
        'micro_render_chars': micro_blocks,
    }

    pool_report = None
    if args.pool:
        pool_report = audit_pool(args.pool)
        report['pool'] = pool_report

    problems = []
    warnings = []
    if missing:
        problems.append('缺失结构: %s' % ', '.join(missing))
    if micro_count and not all(150 <= n <= 250 for n in micro_blocks):
        # ⚠️ 只是提醒，不是问题：渲染块 = content + 对话高亮 + 配图提示词 + 标签，
        # 必然超出 content 的 [150,250] 区间。真正受约束的是 pool 里的 content 字段。
        warnings.append(
            '微头条渲染块字数 %s 超出 [150,250] —— 这是正常的（渲染块含对话与提示词）；'
            '请以 --pool 输出的 content 字数为准' % micro_blocks)
    if pool_report and pool_report.get('out_of_range'):
        problems.append('微头条 content 越界: %s' % [
            '%s=%d' % (r['direction'], r['chars']) for r in pool_report['out_of_range']])
    if report['image_prompt_blocks'] and report['no_text_occurrences'] < report['image_prompt_blocks']:
        problems.append('有配图提示词但缺少 "no text" 约束')

    report['problems'] = problems
    report['warnings'] = warnings
    report['ok'] = not problems

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['ok'] else 1

    print('=== 内容产物审计: %s ===' % os.path.basename(args.html_path))
    print('文件大小        : %d B' % report['size_bytes'])
    print('正文中文字数    : %d  (整篇 %d)' % (body_cn, total_cn))
    print('结构完整性      : %d/%d 在位' % (
        len(sections) - len(missing), len(sections)))
    if missing:
        print('  ❌ 缺失: %s' % ', '.join(missing))
    print('配图提示词块    : %d   ("no text" 出现 %d 次)' % (
        report['image_prompt_blocks'], report['no_text_occurrences']))
    print('话题标签        : %d' % report['hashtag_count'])
    print('微头条块        : %d  (渲染字数 %s)' % (micro_count, micro_blocks))
    if pool_report:
        print('微头条 content  : 池子 %d 条，目标区间 %s，越界 %d 条' % (
            pool_report['pool_size'], pool_report['range'],
            len(pool_report.get('out_of_range', []))))
        for r in pool_report.get('out_of_range', []):
            print('  ❌ %s = %d 字' % (r['direction'], r['chars']))
    if warnings:
        print()
        print('⚠️ 提醒:')
        for w in warnings:
            print('   - %s' % w)
    print()
    if problems:
        print('❌ 发现问题:')
        for p in problems:
            print('   - %s' % p)
        return 1
    print('✅ 全部检查通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
