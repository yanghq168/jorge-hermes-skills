#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内容自洽性 lint：数值链 + 角色一致性 + 频次冲突。

为什么需要这个（2026-11-01 头条号审计实测）
--------------------------------------------
`audit_rendered_article.py` 测的是**长度与结构**：正文字数够不够、
【故事A·对话】在不在、配图提示词够不够5张、标签够不够、微头条字数
落在 [150,250]。它**不测数字是否算得通、角色是否存在**。

于是一篇「月费8000，子女出了5000+5000+3000=13000，剩下的一大半是她
自己掏的」的文章能一路绿灯：脚本 exit 0、HTML 渲染成功、飞书附件送达、
审计脚本报「全部检查通过」。读者只要拿计算器一按就穿帮 —— 而头条中老年
用户恰恰最爱这类「算账」题材。

四类缺陷（全部静默）：

  1. SUM_EXCEEDS_FEE / SUM_VS_HALF_CLAIM
     逐项出资合计 > 文中声明的月费/费用；或文中说「才出一半多」而合计
     已经过半。
  2. SPLIT_VS_TOTAL
     「存款22万…一人7万3…剩下的5万1」→ 5.3×3+6.1=22（对），
     但原文写 7万3×3+5万1=27 ≠ 22（错）。
  3. PHANTOM_SON（角色凭空多出）
     老陈明写「两个女儿」，扩写段落却写「他不跟儿子要钱」，结尾又问
     「你不跟儿子住」—— 一个只有女儿的人凭空多了个儿子。
  4. FREQ_CONFLICT / PERIODIC_VS_COUNT / CONTRIB_VS_FEE
     一处写「每月15号轮流打」（1通/月），另一处写「每个月加起来打16次」；
     「每家每月出600，加起来1800，刚好够」但月费写的是1500。

用法
----
    python3 lint_content_consistency.py                          # 默认头条号池
    python3 lint_content_consistency.py --pool <content_script.py>
    python3 lint_content_consistency.py --extensions <ext_module.py>
    python3 lint_content_consistency.py --json                   # 机器可读

退出码：0 = 未发现问题，1 = 发现问题。

关键设计（都是踩过的坑）
------------------------
* **扩写段落是独立文件**，渲染时才拼上去。只读选题池看不到跨文件矛盾，
  必须把扩写并进来一起查。
* **故事A 与故事B 是不同人物**，绝不能合并成一个单元查角色：养老院故事A
  的刘婶是「老大/老二/老三」（两个儿子一个女儿），故事B 的老陈是「两个女儿」。
  合并后刘婶那句合法的「跟儿子说」会被误报。所以 A/B 分开成两个单元。
* **中文金额口语缩写**：「7万3」= 73000、「一万五」= 15000、
  「五千八」= 5800。解析必须还原这些省略写法，否则算式全部误判。
"""

import argparse
import importlib.util
import json
import os
import re
import sys

DEFAULT_POOL = os.path.expanduser('~/.hermes/cron/scripts/toutiao-article-daily.py')

POOL_ATTRS = ('TOPICS_POOL', 'MICRO_TOPICS_POOL', 'TOPICS', 'MICRO_TOPICS',
              'ARTICLE_POOL', 'MICRO_POOL')
EXT_ATTRS = ('STORY_EXTENSIONS', 'TOPIC_EXTENSIONS', 'STORY_EXTRAS')


# ---------------------------------------------------------------- 数值解析

def _cn(s):
    """中文数字 → float（支持 十/百/千/万 与阿拉伯数字混排）。"""
    if not s:
        return None
    s = str(s).strip()
    if re.fullmatch(r'\d+(\.\d+)?', s):
        return float(s)
    digits = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
              '六': 6, '七': 7, '八': 8, '九': 9}
    total, section, number = 0, 0, 0
    unit = {'十': 10, '百': 100, '千': 1000}
    for ch in s:
        if ch in digits:
            number = digits[ch]
        elif ch in unit:
            section += (number or 1) * unit[ch]
            number = 0
        elif ch == '万':
            total += (section + number) * 10000
            section, number = 0, 0
        else:
            return None
    return float(total + section + number)


def _num(s):
    """把 '8000' / '八千' / '一千五' / '7万3' 解析成数字。

    「7万3」是中文口语里 73000 的省略写法（万位 + 尾数省略单位），
    「一万五」= 15000、「五千八」= 5800 同理。
    """
    s = str(s).strip()
    if re.fullmatch(r'\d+(\.\d+)?', s):
        return float(s)
    m = re.fullmatch(r'(\d+)([十百千万])(\d+(?:\.\d+)?)', s)
    if m:
        mult = {'十': 10, '百': 100, '千': 1000, '万': 10000}[m.group(2)]
        return float(m.group(1)) * mult + float(m.group(3))
    m = re.fullmatch(r'([零一二两三四五六七八九]+)([十百千万])([零一二两三四五六七八九])', s)
    if m:
        base = _cn(m.group(1) + m.group(2))
        tail = _cn(m.group(3))
        if base is not None and tail is not None:
            return base + tail
    return _cn(s)


# ---------------------------------------------------------------- 检查项

def check_sum_vs_total(text):
    """'老大出了5000，老二出了5000，老三出了3000，剩下的一大半是她自己掏的'。"""
    issues = []
    pat = re.compile(
        r'((?:[老大二小三四五六七八九\d]+[^，。；、]{0,6}出了\s*[\d零一二两三四五六七八九十百千万]+'
        r'[块元]?[^，。；]{0,10}[，、]?){2,})'
        r'([^。；]{0,60})')
    for mm in pat.finditer(text):
        items = re.findall(r'出了\s*([\d零一二两三四五六七八九十百千万]+)\s*[块元]?',
                           mm.group(1))
        vals = [_num(x) for x in items]
        if not vals or any(v is None for v in vals):
            continue
        s = sum(vals)
        tail = mm.group(2)
        ctx = text[max(0, mm.start() - 25): mm.end() + 20].replace('\n', ' ')

        tot_m = re.search(r'(?:加起来|一共|共计|总共|合起来|一个月)?\s*'
                          r'([\d零一二两三四五六七八九十百千万]+)\s*[块元]?\s*'
                          r'(?:的)?(?:月费|钱|费用|租金)?\s*(?:是|：)?', tail)
        says_self_pays = bool(re.search(r'剩下[^。；]{0,20}自己掏|剩下的[^。；]{0,20}自己出|'
                                         r'多出来的[^。；]{0,20}自己', tail))
        says_half = bool(re.search(r'才出[^。；]{0,6}一半|加起来才出[^。；]{0,6}一半|'
                                   r'一半多', tail))

        head = text[max(0, mm.start() - 120): mm.start()]
        fee_m = re.search(r'月费\s*([\d零一二两三四五六七八九十百千万]+)|'
                          r'费用[^。；]{0,6}([\d零一二两三四五六七八九十百千万]+)\s*[块元]', head)
        if fee_m:
            fee = _num(fee_m.group(1) or fee_m.group(2))
            if fee and s > fee + 1e-6:
                issues.append(('SUM_EXCEEDS_FEE',
                               f'逐项出资合计 {int(s)} > 文中月费/费用 {int(fee)}', ctx))
        elif says_half:
            issues.append(('SUM_VS_HALF_CLAIM',
                           f'逐项出资合计 {int(s)}，文中却说「才出一半多」，二者矛盾', ctx))
        elif says_self_pays and tot_m:
            tot = _num(tot_m.group(1))
            if tot and s > tot + 1e-6:
                issues.append(('SUM_EXCEEDS_TOTAL',
                               f'逐项合计 {int(s)} > 文中总额 {int(tot)}', ctx))
    return issues


def check_fraction(text):
    """'1600，是退休金的三分之一' —— 推算出的被除数是否自洽。"""
    issues = []
    for mm in re.finditer(
            r'([\d零一二两三四五六七八九十百千万]+)\s*[块元]?[^。；]{0,12}是'
            r'([\d零一二两三四五六七八九十百千万]+)\s*[块元]?'
            r'(?:的)?(三分之一|二分之一|一半|四分之一)', text):
        a, b = _num(mm.group(1)), _num(mm.group(2))
        frac = mm.group(3)
        if a is None or b is None:
            continue
        mult = {'三分之一': 3, '二分之一': 2, '一半': 2, '四分之一': 4}[frac]
        implied = a * mult
        if abs(implied - b) > max(1.0, b * 0.15):
            ctx = text[max(0, mm.start() - 30): mm.end() + 30].replace('\n', ' ')
            issues.append(('FRACTION_MISMATCH',
                           f'{mm.group(3)} 推算应为 {int(implied)}，文中为 {int(b)}', ctx))
    return issues


def check_period(text):
    """'一个月X' → '一年Y'；'一天N块' → '一个月M'。"""
    issues = []
    for mm in re.finditer(r'一个月\s*([\d零一二两三四五六七八九十百千万]+)\s*[块元]?'
                          r'[^。；]{0,30}?一年\s*([\d零一二两三四五六七八九十百千万]+)', text):
        a, y = _num(mm.group(1)), _num(mm.group(2))
        if a is None or y is None:
            continue
        if abs(a * 12 - y) > max(1.0, y * 0.12):
            ctx = text[max(0, mm.start() - 20): mm.end() + 20].replace('\n', ' ')
            issues.append(('PERIOD_MONTH_YEAR',
                           f'每月 {int(a)} × 12 = {int(a*12)}，文中写一年 {int(y)}', ctx))
    for mm in re.finditer(r'一天\s*([\d零一二两三四五六七八九十百千万]+)\s*块'
                          r'[^。；]{0,25}?一个月\s*([\d零一二两三四五六七八九十百千万]+)', text):
        d, mo = _num(mm.group(1)), _num(mm.group(2))
        if d is None or mo is None:
            continue
        if abs(d * 30 - mo) > max(2.0, mo * 0.15):
            ctx = text[max(0, mm.start() - 20): mm.end() + 20].replace('\n', ' ')
            issues.append(('PERIOD_DAY_MONTH',
                           f'一天 {int(d)} × 30 ≈ {int(d*30)}，文中写一个月 {int(mo)}', ctx))
    return issues


def check_split_vs_sum(text):
    """'存款22万，一人7万3，剩下的5万1' —— 拆分项之和 vs 总额。"""
    issues = []
    for mm in re.finditer(r'存款\s*([\d零一二两三四五六七八九十百千万]+)\s*万', text):
        total = _num(mm.group(1))          # 单位：万
        if total is None:
            continue
        window = text[mm.start(): mm.start() + 220]
        per = re.search(r'一人\s*([\d零一二两三四五六七八九十百千万]+)\s*万', window)
        rest = re.search(r'剩下(?:的)?\s*([\d零一二两三四五六七八九十百千万]+)\s*万', window)
        count = re.search(r'([三四五六\d])\s*(?:个)?(?:孩子|子女|儿子|女儿|儿)', window)
        if not per or not rest:
            continue
        p, r = _num(per.group(1)), _num(rest.group(1))
        n = 3
        if count:
            n = _cn(count.group(1)) or 3
        if p is None or r is None:
            continue
        if abs(p * n + r - total) > 0.05:
            ctx = window[:180].replace('\n', ' ')
            issues.append(('SPLIT_VS_TOTAL',
                           f'一人 {p} × {int(n)} + 剩下 {r} = {p*n+r} ≠ 总额 {total}（万）', ctx))
    return issues


def check_role_consistency(text):
    """单元里声明了「两个女儿」且无「有个儿子」式声明时，出现「儿子」= 凭空多出。"""
    issues = []
    if not re.search(r'(两个|两)\s*女儿', text):
        return issues
    if re.search(r'(有个儿子|一个儿子|儿子在|儿子和|老伴是儿子|儿子是)', text):
        return issues
    generic = re.compile(r'(儿子的事|孝顺是儿子|养儿防老|生儿子|儿子女儿|'
                         r'儿子(?:都|也)?孝顺|不孝的儿子|坏儿子)')
    for mm in re.finditer(r'儿子', text):
        if generic.search(text[max(0, mm.start() - 8): mm.start() + 8]):
            continue
        ctx = text[max(0, mm.start() - 30): mm.start() + 25].replace('\n', ' ')
        issues.append(('PHANTOM_SON',
                       '文中声明「两个女儿」，此处却出现「儿子」', ctx))
    return issues


def check_periodic_vs_count(text):
    """'轮流打电话'（一个周期一次） vs '每个月加起来打16次电话'。"""
    issues = []
    counts = []
    for mm in re.finditer(r'([\d零一二两三四五六七八九十]+)\s*次\s*电话', text):
        v = _cn(mm.group(1))
        if v is not None:
            counts.append((v, text[max(0, mm.start() - 45): mm.end() + 20].replace('\n', ' ')))
    rot = re.search(r'轮流[^。；]{0,12}(?:打电话|来电话|来看)|'
                     r'每人[^。；]{0,12}(?:打|来)[^。；]{0,8}电话', text)
    if rot and counts:
        for v, ctx in counts:
            if v >= 4:
                issues.append(('PERIODIC_VS_COUNT',
                               f'文中一处是「轮流/每人」（一个周期一次），'
                               f'另一处却是「{int(v)}次电话」', ctx))
                break
    return issues


def check_per_child_contribution(text):
    """'每家每月出600，加起来1800' vs '一个月1500'。"""
    issues = []
    for mm in re.finditer(r'每(?:个)?(?:家|人|户)[^。；]{0,10}出\s*'
                          r'([\d零一二两三四五六七八九十百千万]+)\s*[块元]?'
                          r'[^。；]{0,20}?加起来\s*([\d零一二两三四五六七八九十百千万]+)', text):
        per, total = _num(mm.group(1)), _num(mm.group(2))
        if per is None or total is None:
            continue
        ctx = text[max(0, mm.start() - 60): mm.end() + 30].replace('\n', ' ')
        head = text[max(0, mm.start() - 160): mm.start()]
        fee = re.search(r'一个月\s*([\d零一二两三四五六七八九十百千万]+)\s*[块元]?'
                        r'[^。；]{0,10}(?:钱|费用|工钱)?', head)
        if fee:
            f = _num(fee.group(1))
            if f and abs(total - f) > 1e-6:
                issues.append(('CONTRIB_VS_FEE',
                               f'分摊合计 {int(total)} ≠ 文中月费 {int(f)}', ctx))
        elif abs(per * 3 - total) > 1e-6:
            issues.append(('CONTRIB_SUM_MISMATCH',
                           f'每份 {int(per)} × 3 = {int(per*3)} ≠ 文中「加起来」{int(total)}', ctx))
    return issues


def check_freq_conflict(text):
    """同一故事里两个不同的探访/通话频次声明。"""
    issues = []
    pat = re.compile(r'([\d零一二两三四五六七八九十]+)\s*次'
                     r'(?:电话|回来|来看|回来看|探?望|轮休)')
    found = []
    for mm in pat.finditer(text):
        v = _cn(mm.group(1))
        if v is None:
            continue
        found.append((v, text[max(0, mm.start() - 40): mm.end() + 15].replace('\n', ' ')))
    if len(found) >= 2:
        vals = [f[0] for f in found]
        if len(set(vals)) > 1 and max(vals) >= 4:
            issues.append(('FREQ_CONFLICT',
                           f'同一故事出现多个不同频次声明: {[int(v) for v in vals]}',
                           found[0][1]))
    return issues


FIELD_CHECKERS = (check_sum_vs_total, check_fraction, check_period,
                  check_split_vs_sum)


# ---------------------------------------------------------------- 装配

def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _discover_pools(mod):
    """找出模块里的选题池（list[dict]，含 direction / title 键）。"""
    pools = []
    for attr in POOL_ATTRS:
        val = getattr(mod, attr, None)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            pools.append((attr, val))
    return pools


def _discover_extensions(mod, script_dir):
    """找出扩写段落字典 {direction: (ext_a, ext_b)}。

    优先看模块自身属性；否则按 '<模块名>_story_extensions' 在同目录 import。
    """
    for attr in EXT_ATTRS:
        val = getattr(mod, attr, None)
        if isinstance(val, dict) and val:
            return val
    stem = os.path.splitext(os.path.basename(mod.__file__))[0]
    for cand in (stem.replace('-', '_') + '_story_extensions', 'toutiao_story_extensions'):
        try:
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)
            ext_mod = __import__(cand)
            for attr in EXT_ATTRS:
                val = getattr(ext_mod, attr, None)
                if isinstance(val, dict) and val:
                    return val
        except Exception:
            continue
    return {}


def _ext_pair(ext):
    """扩写值 → (a, b)。兼容 tuple/list 二元组与单字符串。"""
    if isinstance(ext, (tuple, list)):
        a = ext[0] if len(ext) > 0 else ''
        b = ext[1] if len(ext) > 1 else ''
        return str(a), str(b)
    return str(ext), ''


def _units_for(topic, ext):
    """把一篇选题切成「故事A单元」/「故事B单元」/「微头条单元」。

    ⚠️ A 与 B 是**不同人物**，绝不合并 —— 否则合法指代会被误报。
    """
    def g(k):
        return str(topic.get(k, '') or '')

    unit_a = '\n'.join(x for x in (g('story_a'), g('story_a_dialogue'),
                                    g('story_a_ending')) if x)
    unit_b = '\n'.join(x for x in (g('story_b'), g('story_b_ending')) if x)
    unit_m = '\n'.join(x for x in (g('content'), g('micro_dialogue')) if x)

    ea, eb = _ext_pair(ext) if ext else ('', '')
    if ea:
        unit_a += '\n' + ea
    if eb:
        unit_b += '\n' + eb

    units = []
    if unit_a.strip():
        units.append(('故事A单元', unit_a))
    if unit_b.strip():
        units.append(('故事B单元', unit_b))
    if unit_m.strip():
        units.append(('微头条单元', unit_m))
    return units


UNIT_CHECKERS = (check_role_consistency, check_freq_conflict,
                 check_periodic_vs_count, check_per_child_contribution)


def lint(pools, extensions):
    issues = []
    for pool_name, pool in pools:
        for t in pool:
            direction = t.get('direction', '?')
            ext = extensions.get(direction)

            # ① 字段级：数值链（扩写段落并入对应字段一起查）
            merged = dict(t)
            ea, eb = _ext_pair(ext) if ext else ('', '')
            if ea:
                merged['story_a'] = (t.get('story_a', '') or '') + '\n\n' + ea
            if eb:
                merged['story_b'] = (t.get('story_b', '') or '') + '\n\n' + eb
            for fname, txt in merged.items():
                if not isinstance(txt, str) or not txt:
                    continue
                for checker in FIELD_CHECKERS:
                    for code, msg, ctx in checker(txt):
                        issues.append({'pool': pool_name, 'direction': direction,
                                       'field': fname, 'code': code,
                                       'message': msg, 'context': ctx.strip()})

            # ② 单元级：角色一致性 / 频次冲突（必须跨字段）
            for uname, unit in _units_for(t, ext):
                for checker in UNIT_CHECKERS:
                    for code, msg, ctx in checker(unit):
                        issues.append({'pool': pool_name, 'direction': direction,
                                       'field': uname, 'code': code,
                                       'message': msg, 'context': ctx.strip()})
    return issues


def main(argv=None):
    ap = argparse.ArgumentParser(description='内容自洽性 lint（数值链/角色/频次）')
    ap.add_argument('--pool', default=DEFAULT_POOL,
                    help='内容生成脚本路径（默认头条号）')
    ap.add_argument('--extensions', default=None,
                    help='扩写段落模块路径（默认在 --pool 同目录自动发现）')
    ap.add_argument('--json', action='store_true', help='机器可读输出')
    args = ap.parse_args(argv)

    if not os.path.isfile(args.pool):
        print(f'❌ 找不到内容脚本: {args.pool}', file=sys.stderr)
        return 2

    script_dir = os.path.dirname(os.path.abspath(args.pool))
    # ⚠️ 必须在加载 pool 之前就位：pool 模块在 import 时会加载同目录的
    #    扩写模块（如 toutiao_topics_extra），届时依赖 sys.path 已含该目录。
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    try:
        mod = _load_module(args.pool, '_lint_pool_mod')
    except Exception as e:
        print(f'❌ 加载内容脚本失败: {e}', file=sys.stderr)
        return 2

    pools = _discover_pools(mod)
    if not pools:
        print('❌ 未在内容脚本里发现选题池（TOPICS_POOL / MICRO_TOPICS_POOL …）',
              file=sys.stderr)
        return 2

    if args.extensions:
        try:
            ext_mod = _load_module(args.extensions, '_lint_ext_mod')
            extensions = {}
            for attr in EXT_ATTRS:
                val = getattr(ext_mod, attr, None)
                if isinstance(val, dict) and val:
                    extensions = val
                    break
        except Exception as e:
            print(f'⚠️ 扩写段落加载失败: {e}', file=sys.stderr)
            extensions = {}
    else:
        extensions = _discover_extensions(mod, script_dir)

    issues = lint(pools, extensions)

    if args.json:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
        return 1 if issues else 0

    total_pool = sum(len(p) for _, p in pools)
    if not issues:
        print(f'✅ 内容自洽性检查通过：{total_pool} 条选题'
              f'（{len(extensions)} 条扩写）未发现数值链/角色/频次矛盾')
        return 0

    print(f'❌ 发现 {len(issues)} 处内容自洽性问题\n')
    by_dir = {}
    for it in issues:
        by_dir.setdefault(it['direction'], []).append(it)
    for direction in sorted(by_dir):
        print(f'【{direction}】')
        for it in by_dir[direction]:
            print(f"  [{it['code']}] ({it['field']}) {it['message']}")
            print(f"      … {it['context'][:130]}")
        print()
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
