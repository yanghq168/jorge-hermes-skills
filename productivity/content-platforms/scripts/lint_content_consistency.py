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

五类缺陷（2026-11-04 新增，同样全程绿灯）：

  5. SPLIT_SUM_VS_INHERITED_TOTAL
     分家各项之和 ≠ 同段声明的总额。
     「存了40万…女儿拿了35万，儿子拿了15万」→ 35+15 = 50万 ≠ 40万。
  6. PERIOD_TOTAL_VS_SEGMENTS / CARE_COST_VS_MONTHS
     「一共住了十四个月」但明细 4.5+4+3 = 11.5 个月；
     「凑了2万请护工」但护工 6000/月 × 2 月 = 1.2 万。
  7. ORPHAN_CHARACTER（孤儿扩写）
     扩写段落整个换成了另一个故事 —— 主体讲孙大爷过户被赶，扩写却写
     「老李头从房管局出来」。读者看到主角无预兆地换了人。

     ⚠️ 检测口径（三次踩坑）：
     - **不能按出现频次判主角** —— 孤儿人物在自己的扩写里往往出现得
       更频繁，按频次取主角会把孤儿当主角。
     - **不能拿整篇单元比** —— 故事B 主角本就与故事A 不同，且故事B 里
       合法提到故事A 的人物。必须按 **A对A、B对B 配对比较**。
     - **人名抽取不许跨功能字**，否则抽出「房管局」「张问刘婶」。

用法
----
    python3 lint_content_consistency.py                          # 默认头条号池
    python3 lint_content_consistency.py --pool <content_script.py>
    python3 lint_content_consistency.py --extensions <ext_module.py>
    python3 lint_content_consistency.py --json                   # 机器可读

退出码：0 = 未发现问题，1 = 发现问题，**2 = 检查器自身自检失败（工具坏了，
不是内容坏了）**。新增规则时**必须**在 `_self_test()` 里配「正例不报 +
反例必报」两条算例 —— 否则你不知道规则本身对不对。

关键设计（都是踩过的坑）
------------------------
* **扩写段落是独立文件**，渲染时才拼上去。只读选题池看不到跨文件矛盾，
  必须把扩写并进来一起查。
* **故事A 与故事B 是不同人物**，绝不能合并成一个单元查角色：养老院故事A
  的刘婶是「老大/老二/老三」（两个儿子一个女儿），故事B 的老陈是「两个女儿」。
  合并后刘婶那句合法的「跟儿子说」会被误报。所以 A/B 分开成两个单元。
* **中文金额口语缩写**：「7万3」= 73000、「一万五」= 15000、
  「五千八」= 5800。解析必须还原这些省略写法，否则算式全部误判。
* **金额单位口径要分开**：捕获组不含「万」时（`存了40万` → `40`）数值本身
  就是「万」；组内自带「万」（`十八万七`）才是「元」。混用差 1e4。
* **匹配「一个月X」必须确认紧邻业务词**（护工），否则会把「养老院月费
  4200」当成护工费。
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


_UNITS = {'十': 10, '百': 100, '千': 1000, '万': 10000}
# 口语尾数省略单位时，尾数代表**下一级**单位：
# 「7万3」= 7万 + 3千 = 73000；「五千八」= 5千 + 8百 = 5800。
_NEXT_UNIT = {'万': 1000, '千': 100, '百': 10, '十': 1}

_CN_DIGITS = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
              '六': 6, '七': 7, '八': 8, '九': 9}


def _parse_cn_amount(s):
    """纯中文数字 → 数值，处理「省尾数单位」的省略写法。

    「一万五」= 15000、「五千八」= 5800、「十八万七」= 187000、
    「三百二十」= 320、「二十三」= 23。

    规则：读到单位字就结算该级；结尾若还剩一个**没有单位**的裸数字，
    它代表**上一个单位的下一级**（省略写法）。
    「三百二十」里的「二十」自带单位，不适用省略规则 —— 这正是
    正则写法会算错的地方（三百二十 被误算成 500）。
    """
    total = 0.0
    section = 0.0
    number = None
    last_unit = None
    for ch in s:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _UNITS:
            if ch == '万':
                total += (section + (number or 0)) * 10000
                section = 0.0
            else:
                section += (number if number is not None else 1) * _UNITS[ch]
            number = None
            last_unit = ch
        else:
            return None
    if number is not None and number != 0:
        # 结尾的裸数字 = 省略了单位的下一级
        mult = _NEXT_UNIT.get(last_unit, 1) if last_unit else 1
        total += number * mult
    return total + section


def _num(s):
    """把 '8000' / '八千' / '一千五' / '7万3' 解析成数字（单位：元）。

    「7万3」是中文口语里 73000 的省略写法（万位 + 尾数省略单位），
    「一万五」= 15000、「五千八」= 5800、「十八万七」= 187000 同理。

    ⚠️ 尾数不是简单相加，而是要带上**下一级单位**：
       旧实现把 '7万3' 算成 70003、把 '一万五' 算成 10005 —— 这会让
       「已经写对的文案」被误报成缺陷，害得修复方把对的改回错的。
       见 _self_test()：写完解析器必须用已知正确的算例验证它本身。
    """
    s = str(s).strip()
    if re.fullmatch(r'\d+(\.\d+)?', s):
        return float(s)
    # 阿拉伯数字前缀 + 单位 + 阿拉伯尾数：'7万3' / '5千8'
    m = re.fullmatch(r'(\d+(?:\.\d+)?)([十百千万])(\d+(?:\.\d+)?)', s)
    if m:
        base = float(m.group(1)) * _UNITS[m.group(2)]
        return base + float(m.group(3)) * _NEXT_UNIT[m.group(2)]
    # 阿拉伯数字前缀 + 单位（无尾数）：'8万' / '18万'
    m = re.fullmatch(r'(\d+(?:\.\d+)?)([十百千万])', s)
    if m:
        return float(m.group(1)) * _UNITS[m.group(2)]
    # 纯中文数字（含省略尾数写法）
    if s and all(ch in _CN_DIGITS or ch in _UNITS for ch in s):
        return _parse_cn_amount(s)
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


def _wan_amount(prefix: str, tail: str):
    """「万」为单位时解析金额：'5'+'6' → 5.6万；'8'+'7' → 8.7万。

    中文口语里「5万6」= 5.6 万、「7万3」= 7.3 万，尾数省略单位。
    在**万**为单位时，尾数位是 0.1 万（= 1000 元）：

        一人 5万6 → 5.6 万；一人 7万3 → 7.3 万

    ⚠️ 与 _num() 的口径不同：_num('5万6') = 56000（元），
       _wan_amount('5','6') = 5.6（万）。两者差 1e4，别混用。
    """
    base = None
    if re.fullmatch(r'\d+(\.\d+)?', prefix or ''):
        base = float(prefix)
    else:
        base = _cn(prefix)
    if base is None:
        return None
    tail_v = 0.0
    if tail:
        if re.fullmatch(r'\d+(\.\d+)?', tail):
            tail_v = float(tail)
        else:
            tail_v = _cn(tail)
        if tail_v is None:
            return None
        tail_v = tail_v * 0.1          # 万为单位的尾数 = 0.1 万
    return base + tail_v


def check_split_vs_sum(text):
    """'存款22万，一人7万3，剩下的5万1' —— 拆分项之和 vs 总额。"""
    issues = []
    # 总额也可能是 '8万7' 这种带尾数的写法，要一并还原
    for mm in re.finditer(r'存款\s*([\d零一二两三四五六七八九十百千万]+)\s*万'
                          r'\s*([\d零一二两三四五六七八九十百千万]*)', text):
        total = _wan_amount(mm.group(1), mm.group(2))   # 单位：万
        if total is None:
            continue
        window = text[mm.start(): mm.start() + 260]
        # 每人分摊：'一人5万6' / '每人2万9' / '三人各2万9'（尾数省略单位）
        per_m = re.search(r'(?:一人|每人|各)\s*([\d零一二两三四五六七八九十百千万]+)\s*万'
                          r'\s*([\d零一二两三四五六七八九十百千万]*)', window)
        rest_m = re.search(r'剩下(?:的)?\s*([\d零一二两三四五六七八九十百千万]+)\s*万'
                           r'\s*([\d零一二两三四五六七八九十百千万]*)', window)
        count = re.search(r'([三四五六\d])\s*(?:个)?(?:孩子|子女|儿子|女儿|儿)', window)
        if not per_m or not rest_m:
            continue
        p = _wan_amount(per_m.group(1), per_m.group(2))
        r = _wan_amount(rest_m.group(1), rest_m.group(2))
        n = 3
        if count:
            n = _cn(count.group(1)) or 3
        if p is None or r is None:
            continue
        if abs(p * n + r - total) > 0.05:
            ctx = window[:180].replace('\n', ' ')
            issues.append(('SPLIT_VS_TOTAL',
                           f'一人 {p} × {int(n)} + 剩下 {r} = {round(p*n+r, 2)} ≠ 总额 {total}（万）',
                           ctx))
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


def _to_wan(s):
    """把「40」/「18万7」这类捕获组还原成「万」为单位的数值。

    ⚠️ 捕获组通常**不含**「万」字（如 '存了40万' 捕获到 '40'），
    此时数值本身就是「万」；但若组内自带「万」（如 '十八万七'），
    `_num()` 返回的是「元」，要再除 1e4。两种口径必须分开判断。
    """
    v = _num(s)
    if v is None:
        return None
    if '万' in str(s):
        return v / 10000.0
    return v


def check_inherited_total(text):
    """分家/分遗产：各项之和 vs 文中声明的总额。

    「老陈头存了40万…最后女儿拿了35万，儿子拿了15万」→ 35+15 = 50万 ≠ 40万。

    ⚠️ 「差不多」是模糊量，不能直接当总额做等式判定 —— 这里只在
    同一段里**显式出现**总额数字（「存了40万」「存款40万」）时才判。
    """
    issues = []
    totals = []
    for mm in re.finditer(r'(?:存了|存下|存款|攒了|一共|共有|总额|遗产是|手里有)'
                          r'\s*([\d零一二两三四五六七八九十百千万]+)\s*万', text):
        v = _to_wan(mm.group(1))
        if v:
            totals.append((v, text[max(0, mm.start() - 40): mm.end() + 20].replace('\n', ' ')))
    if not totals:
        return issues

    parts = []
    for mm in re.finditer(r'(?:拿了|拿|分到|分给|得了|分走)'
                          r'\s*([\d零一二两三四五六七八九十百千万]+)\s*万', text):
        v = _to_wan(mm.group(1))
        if v:
            parts.append((v, mm.group(0)))
    if len(parts) < 2:
        return issues

    total = totals[0][0]
    s = sum(p[0] for p in parts)
    if abs(s - total) > max(0.01, total * 0.01):
        issues.append(('SPLIT_SUM_VS_INHERITED_TOTAL',
                       f'分家合计 {round(s, 2)} 万 ≠ 文中总额 {total} 万'
                       f'（分项: {", ".join(p[1] for p in parts)}）',
                       totals[0][1]))
    return issues


# 常见姓氏（用于孤儿人物检测，避免把「马路/方向/周末」当成人名）
_SURNAMES = ('赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦许何吕施张孔曹严华金魏陶姜谢邹喻柏水窦章云苏潘葛'
             '范彭郎鲁韦昌马苗凤方俞任袁柳史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平'
             '黄穆萧尹姚邵湛汪祁毛戴谈宋庞熊纪舒屈祝董梁杜阮蓝闵季席麻强贾路娄江童颜郭林刁钟徐邱骆高夏蔡田樊胡'
             '凌霍虞万柯管卢莫房解应宗丁宣邓郁单杭洪包左石崔吉龚程嵇裴陆荣翁荀羊惠甄曲家封储靳井段富巫乌焦巴'
             '牧山谷车侯班秋仲伊宫宁仇栾甘厉祖武符刘景詹叶幸韶郜黎印宿白怀鄂索赖卓蔺屠蒙池乔翟谭姬申冉雍桑桂'
             '牛通边燕浦尚农温庄柴瞿阎充慕连茹艾鱼容向古易慎戈廖步耿满匡国文寇广师巩聂敖冷辛阚简饶空曾沙鞠巢关'
             '相查荆红游权逯盖桓')


def _person_names(text):
    """抽取「称谓型人名」：姓+称谓后缀 / 老X头 / 老X。

    ⚠️ 必须排除普通词 —— 「房管局」「红本子」「的周大爷」都不是人名。
    做法：
    - **姓 + 称谓后缀**（孙大爷/吴老师/赵大爷/刘婶），中间**不允许**跨过
      功能字（否则「张问刘婶」「元的周大爷」会被误抽）。
    - **老 + 姓 + 头/儿/王/婶/姨/叔**（老李头/老周头/老陈头）。
    - **光杆 老X**（老张/老李）只在**出现 ≥2 次**时才认（否则「老王」可能
      是「老王下棋」这类普通词）。
    - 泛称词（老伴/老太太/老大/老家…）与常见非人名词一律排除。
    """
    generic = {'老伴', '老太太', '老人', '老家', '老宅', '老乡', '老年', '老爷',
               '老大', '老二', '老三', '老四', '老大爷', '老太太们', '老同事',
               '老邻居', '老规矩', '老样子', '老账本', '老朋友', '老规矩'}
    block = {'房管局', '红本子', '房产证', '人民币', '房款总', '任何', '事情'}
    names = set()
    # 姓 + 称谓后缀（中间 0 个字）
    for mm in re.finditer(r'[' + _SURNAMES + r'](?:大爷|大妈|老师|师傅|婶|叔|姨|总)', text):
        names.add(mm.group(0))
    # 老 + 姓 + 头/儿/王/婶/姨/叔
    for mm in re.finditer(r'老[' + _SURNAMES + r'](?:头|儿|王|婶|姨|叔)', text):
        names.add(mm.group(0))
    # 光杆 老X：只在出现 ≥2 次时认（老张、老李、老陈…）
    for mm in re.finditer(r'老[' + _SURNAMES + r']', text):
        n = mm.group(0)
        if text.count(n) >= 2:
            names.add(n)
    return {n for n in names if n not in generic and n not in block and len(n) >= 2}


def _ext_orphan_issues(direction, base, ext, label):
    """扩写段落 vs 它对应的主体故事：扩展里出现主体故事没有的人名 = 孤儿。

    ⚠️ 关键口径：**必须按「A对A、B对B」配对比较**。
    - 故事B 的主角本来就和故事A 不同（周大爷 vs 老陈头）—— 拿整篇比会误报。
    - 故事B 里合法地提到故事A 的人物（「比孙大爷还大两岁」）也不是孤儿。
    所以只比：**扩展文本里出现、但对应主体故事里没有**的人名。
    """
    issues = []
    if not ext:
        return issues
    base_names = _person_names(base or '')
    for n in sorted(_person_names(ext)):
        if n in base_names:
            continue
        # 派生名（主体姓氏 + 不同后缀）不算孤儿
        if any(n[0] == b[0] or (n.startswith('老') and len(n) > 1 and n[1] == b[0])
               for b in base_names):
            continue
        pos = ext.find(n)
        issues.append(('ORPHAN_CHARACTER',
                       f'{direction} {label} 出现「{n}」，但对应的主体故事里没有这个人 —— '
                       f'疑似孤儿段落（整个故事被换掉了）',
                       ext[max(0, pos - 60): pos + 60].replace('\n', ' ')))
    return issues


def check_period_total(text):
    """「一共住了X个月」vs 各段时长之和；护工月费×月数 vs 实际凑的钱。"""
    issues = []
    # ① 合计月数 vs 明细月数
    for mm in re.finditer(r'一共住了\s*([\d零一二两三四五六七八九十]+)\s*个月', text):
        want = _cn(mm.group(1))
        if not want:
            continue
        segs = []
        for sm in re.finditer(
                r'([\d零一二两三四五六七八九十]+)个月(?:零([\d零一二两三四五六七八九十]+)个?月)?',
                text):
            whole = _cn(sm.group(1))
            if whole is None:
                continue
            half = (_cn(sm.group(2)) or 0) if sm.group(2) else 0
            segs.append(whole + half * 0.5)
        if len(segs) < 2:
            continue
        s = sum(segs)
        if abs(s - want) > 0.01:
            issues.append(('PERIOD_TOTAL_VS_SEGMENTS',
                           f'声明「一共住了 {int(want)} 个月」，但各段相加 = {round(s, 2)} 个月',
                           text[max(0, mm.start() - 60): mm.end() + 60].replace('\n', ' ')))
    # ② 护工费：一个月X元 × N个月 vs 凑了Y
    for mm in re.finditer(r'([\d零一二两三四五六七八九十]+)\s*个月', text):
        n = _cn(mm.group(1))
        if not n or n < 2:
            continue
        w = text[max(0, mm.start() - 150): mm.start() + 200]
        if '护工' not in w:
            continue
        pm = re.search(r'一个月\s*([\d零一二两三四五六七八九十百千万]+)\s*(?:元|块)?', w)
        if not pm:
            continue
        per = _num(pm.group(1))
        # 「一个月4200」可能是养老院月费而不是护工费 —— 必须确认窗口里有护工语境，
        # 且该「一个月X」紧邻护工字样，否则跳过（避免把月费当护工费）。
        if '护工' not in w[max(0, w.find(pm.group(0)) - 30): w.find(pm.group(0)) + 60]:
            continue
        pays = re.findall(r'(?:凑了|给了|出了|拿出)\s*'
                          r'([\d零一二两三四五六七八九十百千万]+\s*万?'
                          r'[\d零一二两三四五六七八九十]*)', w)
        # 窗口里出现多个出资方 → 无法判定，跳过（避免误报）
        if len(pays) != 1:
            continue
        paid = _num(pays[0].replace(' ', ''))
        if not per or not paid:
            continue
        if abs(per * n - paid) > max(1.0, per * n * 0.05):
            issues.append(('CARE_COST_VS_MONTHS',
                           f'「{int(n)} 个月」× 一个月 {per:.0f} 元 = {per * n:.0f} 元，'
                           f'但文中说凑了 {paid:.0f} 元',
                           w.replace('\n', ' ')[:200]))
    return issues


FIELD_CHECKERS = (check_sum_vs_total, check_fraction, check_period,
                  check_split_vs_sum, check_inherited_total,
                  check_period_total)


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


def _self_test():
    """解析器自检 —— 用已知正确的算例验证，而不是只看「有没有报错」。

    规则（来自 2026-11-01 的实战教训）：写完检查器要用已知正确的算例
    验证解析器本身。一个把「5万2」当「5」的解析器，会把**已经修好的**
    文本报成缺陷，害得修复方把对的改回错的。

    期望全绿；任何一条失败 → 退出码 2（工具坏了，不是内容坏了）。
    """
    cases = [
        # (输入, 期望值)  —— 中文金额口语缩写
        ('8000', 8000.0), ('7万3', 73000.0), ('5万2', 52000.0),
        ('一万五', 15000.0), ('五千八', 5800.0), ('十八万七', 187000.0),
        ('两千九', 2900.0), ('一万', 10000.0), ('三十', 30.0),
        ('三百二十', 320.0),
    ]
    failed = []
    for raw, want in cases:
        got = _num(raw)
        if got is None or abs(got - want) > 1e-6:
            failed.append(f'_num({raw!r}) = {got!r}，期望 {want!r}')

    wan_cases = [('5', '6', 5.6), ('7', '3', 7.3), ('10', '', 10.0),
                 ('十', '二', 10.2), ('8', '7', 8.7)]
    for pre, tail, want in wan_cases:
        got = _wan_amount(pre, tail)
        if got is None or abs(got - want) > 1e-6:
            failed.append(f'_wan_amount({pre!r},{tail!r}) = {got!r}，期望 {want!r}')

    # 已知正确的拆分：5.6 × 3 + 5.2 = 22 ✔；已知错误的：7.3 × 3 + 5.1 = 27.0 ✘
    ok = check_split_vs_sum('存款22万，按三个孩子平分，一人5万6，剩下的5万2留给他和老伴看病。')
    if ok:
        failed.append('正确的拆分（5.6×3+5.2=22）被误报为缺陷')
    bad = check_split_vs_sum('存款22万，按三个孩子平分，一人7万3，剩下的5万1留给他和老伴看病。')
    if not bad:
        failed.append('错误的拆分（7.3×3+5.1=27≠22）未被发现')

    # ── 新增规则自检（2026-11-04）─────────────────────────────────────
    # ① SPLIT_SUM_VS_INHERITED_TOTAL：分家之和 vs 声明总额
    ok = check_inherited_total('老陈头存了40万。最后女儿拿了25万，儿子拿了15万。')
    if ok:
        failed.append('正确的分家（25+15=40万）被误报为缺陷')
    bad = check_inherited_total('老陈头存了40万。最后女儿拿了35万，儿子拿了15万。')
    if not bad:
        failed.append('错误的分家（35+15=50≠40万）未被发现')

    # ② PERIOD_TOTAL_VS_SEGMENTS：合计月数 vs 各段之和
    ok = check_period_total('她在三个儿子家一共住了十一个半月，大儿子家四个月零半个月，'
                            '二儿子家四个月，三儿子家三个月。')
    if ok:
        failed.append('正确的月数合计（11.5）被误报为缺陷')
    bad = check_period_total('她在三个儿子家一共住了十四个月，大儿子家四个月零半个月，'
                            '二儿子家四个月，三儿子家三个月。')
    if not bad:
        failed.append('错误的月数合计（14 ≠ 11.5）未被发现')

    # ③ CARE_COST_VS_MONTHS：护工月费 × 月数 vs 凑的钱
    ok = check_period_total('子女凑了1万2给他请护工，护工照顾了两个月就走了。'
                            '请护工一个月6000，比这贵。')
    if ok:
        failed.append('正确的护工费（6000×2=1.2万）被误报为缺陷')
    bad = check_period_total('子女凑了2万块钱给他请护工，护工照顾了两个月就走了。'
                            '请护工一个月6000，比这贵。')
    if not bad:
        failed.append('错误的护工费（6000×2=1.2万 ≠ 2万）未被发现')

    # ④ ORPHAN_CHARACTER：扩写段落里出现主体故事没有的人物
    ok = check_orphan_character('孙大爷69岁，退休前是中学老师。房子写的是孙涛的名字。'
                                '过户那天，孙大爷从房管局出来。他心里有一笔账。')
    if ok:
        failed.append('正确的主体故事被误报为孤儿段落')
    bad = check_orphan_character('孙大爷69岁，退休前是中学老师。房子写的是孙涛的名字。'
                                '过户那天，老李头从房管局出来。他心里有一笔账。')
    if not bad:
        failed.append('孤儿人物（老李头 vs 孙大爷）未被发现')

    if failed:
        print('❌ 解析器自检失败 —— 工具本身有问题，不是内容有问题：', file=sys.stderr)
        for f in failed:
            print('   - ' + f, file=sys.stderr)
        return False
    print('✅ 解析器自检通过（金额口语缩写 + 拆分算例）')
    return True


if __name__ == '__main__':
    if not _self_test():
        raise SystemExit(2)
    raise SystemExit(main())
