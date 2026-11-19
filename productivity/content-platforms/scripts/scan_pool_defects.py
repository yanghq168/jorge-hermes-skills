#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全池六段式缺陷扫描器（通用，2026-11-18 落地）

用途：把「当晚一篇」的通读扩展成「全池 20 条」的结构化粗筛，
      一次性把下列缺陷族捞出来，供**人工逐条核对**（不要直接照单改文案）。

覆盖段落：
  ① 钩子整句在正文逐字复读（含扩写段）
  ② 标题引语 vs 正文（HOOK_PROMISE 的**设计约束**项 —— 命中不代表有缺陷）
  ③ 金句 ↔ 正文复读（阈值 8 字，含扩写）
  ④ 人物姓氏撞车（故事A ↔ 故事B）
  ⑤ 年龄撞车（故事A ↔ 故事B）
  ⑥ 微头条：标题/钩子的**否定式承诺** vs 正文（缺陷二十一）

⚠️ 关键纪律：
  - 本脚本是**粗筛**，不是判定器。命中≠缺陷。② 段的命中是设计约束（钩子必须兑现承诺），
    ④⑤ 段当晚实测全部是假阳性（「她的做法跟王阿姨完全不一样」是对比式提及）。
  - **假阳性必须逐条人工确认**，不能看到告警就改文案（会把对的改回错的）。
  - 本脚本**只读**，不写任何生产文件。

用法：
    python3 scan_pool_defects.py --pool <生成器脚本.py> [--extensions <扩写.py>] [--json]

退出码：
    0 = 跑完了（不代表内容没问题！命中项需要人工核对）
    2 = 参数用错 / 装配不出正文（工具侧问题，不是内容问题）
"""

import argparse
import importlib.util
import itertools
import json
import os
import re
import sys


# ---------------------------------------------------------------- helpers

def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def cjk(s):
    return ''.join(re.findall(r'[一-鿿]', s or ''))


def norm(s):
    """去标点空格，用于整句逐字比对。"""
    return re.sub(r'[^\u4e00-\u9fff]', '', s or '')


def lcs(a, b):
    """最长公共连续子串。"""
    if not a or not b:
        return ''
    prev = [0] * (len(b) + 1)
    best = ''
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > len(best):
                    best = a[i - cur[j]:i]
        prev = cur
    return best


def quotes(s):
    """抽取引号内的对白（≥2 汉字）。"""
    out = []
    for pat in (r'「([^」]{2,})」', r'『([^』]{2,})』',
                r'"([^"]{2,})"', r"'([^']{2,})'"):
        out.extend(re.findall(pat, s or ''))
    return [x for x in out if len(cjk(x)) >= 2]


NAMES_RE = re.compile(
    r'[一-龥]{1,3}(?:大爷|大娘|阿姨|叔叔|婶儿|婶子|大哥|大姐|老头|老太婆'
    r'|师傅|老师|医生|会计|律师|姑娘|小伙)')
AGES_RE = re.compile(r'(\d{2})\s*(?:岁|周岁)')


def names(txt):
    """抽取人名/称呼 —— 必须带称谓后缀，避免抽出「房管局」「红本子」这类。"""
    return set(NAMES_RE.findall(txt or ''))


def ages(txt):
    return set(AGES_RE.findall(txt or ''))


# 否定式承诺：触发词 + 完成态反查
NEG_TRIGGER = re.compile(
    r'(?:一分没出|一分钱没出|没出过?|没给过?|没拿过?|没掏过?|没花过?'
    r'|没管过?|没过问过?|没来过?|没回过?|没理会过?|没吭过声|没露面'
    r'|未(?:出|给|拿|花|掏|管|过问|来|回)|不(?:管|过问|理会|吭声|露面|参与)'
    r'|一(?:分|个)(?:钱)?也?没)')
DONE_ACT = re.compile(
    r'(?:出了|给了|拿了|花了|掏了|转了|寄了|交了|管了|来了|回了|过问了|'
    r'拿出|拿出钱|汇款|打款)')
# 🔴 2026-11-19 实测：段⑥ 只认「同一动词」，导致**已知真缺陷漏报** ——
# 标题断言「一分没出」（动词=出），正文写「小儿子转了5000块过来」（动词=转），
# 动词不同 ⇒ 规则不 fire ⇒ 11-18 报的丧葬费硬伤，扫描器全程报 0 命中。
# 修法：**加一条粗筛兜底**（转账类动词 + 邻近金额），并按「是否已写明解释句」
# 分级标注。⚠️ 本段是**粗筛不是判定器** —— 语义上「出了丧葬费」≠「出了份子钱」，
# 正则分不出主体与语义，**命中必须人工核对**（命中 ≠ 缺陷）。
TRANSFER_ACT = re.compile(r'(?:转了|给了|掏了|寄了|汇了|打过来|打了钱|交了)')
# 解释句标志：正文里明写「这钱不算…」「这是…不算…」⇒ 已按缺陷二十一修过
DISCLAIMER = re.compile(r'(?:不算|不算是|不属于|不是他出|不是她出|不算他|不算她|'
                        r'是[^。]{0,8}补的|后补|事后补)')
NUM_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(?:块|元|万|块钱)')


def check_negative_promise(title, hook, body):
    """标题/钩子断言「某人没做某事」，正文里这个人后来做了吗？"""
    claim = f'{title or ""} {hook or ""}'
    out = []
    for m in NEG_TRIGGER.finditer(claim):
        neg = m.group(0)
        for d in DONE_ACT.finditer(body or ''):
            # 同一个动作词（出/给/拿/花/掏/转/寄/交/管/来/回/过问）
            neg_v = re.search(r'[出给拿花掏转寄交管来回问]', neg)
            done_v = re.search(r'[出给拿花掏转寄交管来回问]', d.group(0))
            if neg_v and done_v and neg_v.group(0) == done_v.group(0):
                ctx = (body or '')[max(0, d.start() - 40):d.end() + 40]
                nums = NUM_RE.findall(ctx)
                out.append({
                    'negative_claim': neg,
                    'contradicted_by': d.group(0),
                    'context': ctx.strip(),
                    'amounts_nearby': nums,
                    'note': '同一动词 ⇒ 高置信度，仍需人工核对主体',
                })
                break
        else:
            # 兜底：动词不同但出现「转账类动作 + 邻近金额」⇒ 粗筛信号
            for d in TRANSFER_ACT.finditer(body or ''):
                ctx = (body or '')[max(0, d.start() - 50):d.end() + 50]
                nums = NUM_RE.findall(ctx)
                if not nums:
                    continue
                if re.search(r'[出给拿花掏转寄交管来回问]', neg) == re.search(
                        r'[出给拿花掏转寄交管来回问]', d.group(0)):
                    continue
                explained = bool(DISCLAIMER.search(ctx))
                out.append({
                    'negative_claim': neg,
                    'contradicted_by': d.group(0),
                    'context': ctx.strip(),
                    'amounts_nearby': nums,
                    'note': ('粗筛：动词不同（出 vs %s）但正文出现转账动作+金额 ⇒ '
                             '**必须人工核对主体与语义**（命中 ≠ 缺陷）；'
                             '%s'
                             % (d.group(0)[0],
                                '已见解释句 ⇒ 大概率已按缺陷二十一修过'
                                if explained else '未见解释句 ⇒ 疑似真缺陷')),
                })
                break
    return out


# ---------------------------------------------------------------- segments

def scan(pool, ext_map):
    """返回 {段落名: [命中项...]}"""
    res = {k: [] for k in (
        '1_hook_echo', '2_title_quote', '3_golden_echo',
        '4_name_collision', '5_age_collision', '6_negative_claim')}

    for t in pool:
        d = t.get('direction', '?')
        ext = ext_map.get(d, (None, None))
        ea = ext[0] if (ext and len(ext) > 0 and ext[0]) else ''
        eb = ext[1] if (ext and len(ext) > 1 and ext[1]) else ''


        story_a = (t.get('story_a') or '') + (t.get('story_a_dialogue') or '') \
            + (t.get('story_a_ending') or '') + ea
        story_b = (t.get('story_b') or '') + (t.get('story_b_ending') or '') + eb
        body = story_a + story_b + (t.get('viewpoint') or '') + (t.get('action') or '')
        nb = norm(body)

        # ① 钩子整句复读
        # 🔴 2026-11-19 实测：只按句号切分会把引语前的「她说：」前缀粘连进句子，
        # 导致整句不再是正文子串 ⇒ **漏报**（远居赡养「孩子的心是真的，可手不在你身边。」
        # 在钩子与 story_a_ending 各出现一次，扫描器却报 0 命中）。
        # 修法：**额外单独检测钩子里的每一段引语**（引号内 ≥6 字）是否在正文出现，
        # 命中即报「引语级复读」—— 引语级重复是设计约束（HOOK_PROMISE 要求兑现），
        # 但必须**人工核对兑现点有没有带新细节**（复制粘贴式兑现 = 缺陷）。
        for sent in re.split(r'[。！？；\n]', t.get('hook') or ''):
            ns = norm(sent)
            if len(ns) >= 6 and ns in nb:
                res['1_hook_echo'].append({
                    'direction': d, 'sentence': sent.strip(),
                    'note': '修法：改正文那一句，不动钩子；断言用 count()==1'})
        for q in quotes(t.get('hook') or ''):
            nq = norm(q)
            if len(nq) >= 6 and nq in nb:
                res['1_hook_echo'].append({
                    'direction': d, 'sentence': q.strip(),
                    'note': '引语级复读（HOOK_PROMISE 要求兑现 ⇒ 属设计约束）：'
                            '人工核对兑现点是否带新细节（动作/心理/后果），'
                            '纯复制钩子原句才是缺陷'})

        # ② 标题引语 vs 正文（设计约束）
        for q in quotes(t.get('title') or ''):
            if norm(q) not in nb:
                res['2_title_quote'].append({
                    'direction': d, 'quote': q,
                    'note': '设计约束：标题引语必须在正文兑现'})

        # ③ 金句 ↔ 正文（8 字阈值）
        for gk in ('golden1', 'golden2', 'golden3'):
            g = cjk(t.get(gk) or '')
            if not g:
                continue
            for fname, fval in (('story_a_ending', t.get('story_a_ending') or ''),
                                ('story_b_ending', t.get('story_b_ending') or ''),
                                ('viewpoint', t.get('viewpoint') or ''),
                                ('action', t.get('action') or ''),
                                ('ext_a', ea), ('ext_b', eb)):
                s = lcs(g, cjk(fval))
                if len(s) >= 8:
                    res['3_golden_echo'].append({
                        'direction': d, 'pair': f'{gk}↔{fname}',
                        'len': len(s), 'text': s})

        # ④⑤ 身份撞车
        sn = names(story_a) & names(story_b)
        sa = ages(story_a) & ages(story_b)
        if sn:
            res['4_name_collision'].append({
                'direction': d, 'names': sorted(sn),
                'note': '多半是假阳性：对比式提及是双故事论证法的标准写法'})
        if sa:
            res['5_age_collision'].append({
                'direction': d, 'ages': sorted(sa),
                'note': '年龄撞车通常不是缺陷（中老年题材 68 岁是主力年龄）'})

        # ⑥ 否定式承诺（长文 + 微头条都查）
        for neg in check_negative_promise(t.get('title'), t.get('hook'), body):
            neg['direction'] = d
            res['6_negative_claim'].append(neg)

        content = t.get('content')
        if content:
            for neg in check_negative_promise(t.get('title'), t.get('hook'),
                                              content + (t.get('micro_dialogue') or '')):
                neg['direction'] = d
                res['6_negative_claim'].append(neg)

    return res


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pool', required=True, help='生成器脚本本身（如 toutiao-article-daily.py）')
    ap.add_argument('--extensions', default=None, help='扩写段落脚本（如 toutiao_story_extensions.py）')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    if not os.path.isfile(args.pool):
        print(f'❌ --pool 指向的文件不存在: {args.pool}')
        return 2

    try:
        mod = load_module(args.pool, '_scan_pool')
    except Exception as e:
        print(f'❌ 装配失败（工具侧问题，不是内容问题）: {e}')
        return 2

    pool = list(getattr(mod, 'TOPICS_POOL', []) or [])
    # 🔴 2026-11-19 实测：**微头条池根本没被扫** —— 只装配了 TOPICS_POOL，
    # ⇒ 段⑥（否定承诺）只在长文池上跑，而 11-18 报的丧葬费硬伤**在微头条池**里，
    # 扫描器全程报「无命中」＝假绿。
    # 修法：把 MICRO_TOPICS_POOL 一并扫（微头条正文在 content + micro_dialogue）。
    micro_pool = list(getattr(mod, 'MICRO_TOPICS_POOL', []) or [])
    ext_map = {}
    if args.extensions:
        try:
            ext_mod = load_module(args.extensions, '_scan_ext')
            ext_map = getattr(ext_mod, 'STORY_EXTENSIONS', {}) or {}
        except Exception as e:
            print(f'❌ 扩写模块加载失败: {e}')
            return 2

    if not pool and not micro_pool:
        print('❌ 装配不出正文（TOPICS_POOL 与 MICRO_TOPICS_POOL 均为空）⇒ '
              '参数用错或脚本已改，不是内容有问题')
        return 2

    res = scan(pool, ext_map)
    if micro_pool:
        res_micro = scan(micro_pool, ext_map)
        for k, v in res_micro.items():
            for item in v:
                item['pool'] = '微头条'
            res[k].extend(v)

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    titles = {
        '1_hook_echo': '① 钩子整句在正文逐字复读（含扩写段）',
        '2_title_quote': '② 标题引语 vs 正文（HOOK_PROMISE 设计约束，命中≠缺陷）',
        '3_golden_echo': '③ 金句 ↔ 正文复读（阈值 8 字，含扩写）',
        '4_name_collision': '④ 人物姓氏撞车（故事A ↔ 故事B）',
        '5_age_collision': '⑤ 年龄撞车（故事A ↔ 故事B）',
        '6_negative_claim': '⑥ 微头条/长文：否定式承诺被正文推翻（缺陷二十一）',
    }
    for k, title in titles.items():
        print('=' * 78)
        print(title)
        print('=' * 78)
        hits = res.get(k) or []
        if not hits:
            print('  （无命中）')
        for h in hits:
            print('  ⚠️ ', json.dumps(h, ensure_ascii=False))
        print()

    print('=' * 78)
    print('⚠️ 本脚本是【粗筛】。命中 ≠ 缺陷 —— 必须逐条人工核对后再改文案。')
    print('   ② 段的命中是设计约束（钩子/标题必须兑现自己的承诺）。')
    print('   ④⑤ 段当晚实测全部是假阳性。')
    print('=' * 78)
    return 0


if __name__ == '__main__':
    sys.exit(main())
