#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反向验证扫描器规则「真的会 fire」—— 通用工具（2026-11-19 落地）。

【为什么需要这个】
`HOOK_PROMISE` 的教训是「只跑干净内容 exit 0 证明不了规则接上了」。
2026-11-19 把这条纪律推广到**所有粗筛脚本**：扫描器报「无命中」时，
必须先证明它**看得到**那一段内容、且**会**报出缺陷 ——
否则「无命中」是**假绿**（当晚实测三处假绿：段⑥ 只认同一动词 /
段① 引语前缀粘连 / **微头条池根本没被扫**）。

【用法】
    # 1) 反向验证「否定承诺」规则（用修复前的版本当反例）
    python3 verify_scanner_fires.py negative-promise \
        --scanner ~/.hermes/skills/productivity/content-platforms/scripts/scan_pool_defects.py

    # 2) 列出「扫描器盲区」自检项（装配口径类漏报）
    python3 verify_scanner_fires.py blindspot \
        --scanner ~/.hermes/skills/productivity/content-platforms/scripts/scan_pool_defects.py

【退出码】
    0 = 通过（规则会 fire / 无盲区）
    1 = 规则不会 fire（⇒ 规则或装配口径坏了，别去改文案）
    2 = 工具侧问题（参数用错 / 模块加载失败）
"""

import argparse
import importlib.util
import os
import re
import sys


def load_module(path, name):
    if not os.path.isfile(path):
        raise RuntimeError(f'文件不存在: {path}')
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'无法加载: {path}')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 反例库

# 每个用例 = (用例名, 池条目, 期望命中数)
# 用例刻意**自带缺陷**，断言扫描器必须报出来。
NEGATIVE_CLAIM_CASES = [
    (
        '标题断言「一分没出」，正文后段却写「转了5000块过来」（动词不同）',
        {
            'direction': '反例-否定承诺',
            'title': '老伴走了，丧葬费三个子女一分没出，最后是大女儿一个人掏的',
            'hook': '这是读者@李阿姨的投稿。',
            'content': (
                "后事是女儿张罗的，前后花了三万二。她垫的钱，弟妹两个一分没出。\n\n"
                "就这么一句，各自上了车。回到家，小儿子转了5000块过来，"
                "附言写着：'姐，先给一部分。'女儿收了，没回话。"
            ),
        },
        1,
    ),
    (
        '标题断言「一分没出」，正文已写明「不算他出的丧葬费」（已修版本，'
        '粗筛仍应命中但 note 标「已见解释句」）',
        {
            'direction': '反例-否定承诺-已修',
            'title': '老伴走了，丧葬费三个子女一分没出，最后是大女儿一个人掏的',
            'hook': '这是读者@李阿姨的投稿。',
            'content': (
                "后事是女儿张罗的，前后花了三万二。她垫的钱，弟妹两个一分没出。\n\n"
                "就这么一句，各自上了车。回到家，小儿子转了5000块过来，"
                "附言写着：'姐，先给一部分。'女儿收了，没回话。"
                "这5000是丧事办完之后他补的份子钱，不算他出的丧葬费。"
            ),
        },
        1,
    ),
]


# ---------------------------------------------------------------- 自检项

BLINDSPOT_CHECKS = [
    (
        '扫描器是否装配了微头条池（MICRO_TOPICS_POOL）',
        lambda src: 'MICRO_TOPICS_POOL' in src,
        '只在长文池上扫 ⇒ 微头条池的缺陷永远不被检出（2026-11-19 实测漏报）',
    ),
    (
        '扫描器是否逐条检测钩子里的引语（而非只按句号切分）',
        lambda src: bool(re.search(r'for\s+\w+\s+in\s+quotes\(', src))
        or bool(re.search(r"quotes\(\s*t\.get\('hook'", src)),
        '只按句号切分会把「她说：」前缀粘进引语 ⇒ 引语级复读全漏报',
    ),
    (
        '否定承诺规则是否有「动词不同」的兜底分支',
        lambda src: ('TRANSFER_ACT' in src or 'DISCLAIMER' in src),
        '只认同一动词 ⇒ 标题「没出」vs 正文「转了」不 fire',
    ),
]


def cmd_negative_promise(args):
    """反向验证：否定承诺规则对已知反例会不会 fire"""
    try:
        sc = load_module(args.scanner, '_verify_scanner')
    except Exception as e:
        print(f'❌ 扫描器加载失败（工具侧问题）: {e}')
        return 2

    fn = getattr(sc, 'check_negative_promise', None)
    if fn is None:
        print('❌ 扫描器里没有 check_negative_promise() ⇒ '
              '工具侧问题（不是内容问题）')
        return 2

    ok = True
    for name, topic, expect in NEGATIVE_CLAIM_CASES:
        hits = fn(topic.get('title'), topic.get('hook'),
                  topic.get('content', '') + topic.get('micro_dialogue', ''))
        status = '✅' if len(hits) >= expect else '❌'
        if len(hits) < expect:
            ok = False
        print(f'  {status} {name}')
        print(f'       命中 {len(hits)} 条（期望 ≥{expect}）')
        for h in hits:
            print(f'       - 否定承诺「{h.get("negative_claim")}」'
                  f' ← 触发「{h.get("contradicted_by")}」'
                  f' 金额 {h.get("amounts_nearby")}')
            if h.get('note'):
                print(f'         note: {h["note"]}')

    print()
    if ok:
        print('✅ 反向验证通过：规则对已知反例会 fire')
        return 0
    print('❌ 反向验证失败：规则对已知反例**不** fire ⇒ '
          '规则或装配口径坏了（去修工具，别去改文案）')
    return 1


def cmd_blindspot(args):
    """列出扫描器自身的装配口径盲区"""
    try:
        src = open(args.scanner, encoding='utf-8').read()
    except Exception as e:
        print(f'❌ 扫描器读取失败（工具侧问题）: {e}')
        return 2

    ok = True
    print('=== 扫描器盲区自检 ===')
    for name, fn, why in BLINDSPOT_CHECKS:
        passed = bool(fn(src))
        status = '✅' if passed else '⚠️ '
        if not passed:
            ok = False
        print(f'  {status} {name}')
        if not passed:
            print(f'       ⇒ {why}')
    print()
    print('✅ 未发现已知盲区' if ok else
          '⚠️ 发现疑似盲区 —— 命中≠有缺陷，但「扫描器报无命中」'
          '在这类情况下是**假绿**，必须人工核对')
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['negative-promise', 'blindspot'])
    ap.add_argument('--scanner', required=True)
    args = ap.parse_args()

    if args.mode == 'negative-promise':
        return cmd_negative_promise(args)
    return cmd_blindspot(args)


if __name__ == '__main__':
    sys.exit(main())
