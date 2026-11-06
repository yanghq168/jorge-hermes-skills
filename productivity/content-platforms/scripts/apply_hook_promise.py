#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HOOK_PROMISE 检查器补丁 —— 2026-11-06 实测新增的第八类缺陷。

钩子（hook）/标题承诺的具体场景、引语、数字，正文经常一个字都没写 →
读者点进来想看的画面看不到 = 标题党翻车。

⚠️ 落地说明见
   productplatforms/references/hook-promise-and-title-payoff-audit.md 第四节。

用法：
    python3 apply_hook_promise.py <lint_content_consistency.py>
    # 然后：python3 -m py_compile <lint_content_consistency.py>
    #       python3 <lint_content_consistency.py> --pool ... --extensions ...
"""
import re
import sys

QUOTE_RE = re.compile(r"'([^']{2,80})'|\"([^\"]{2,80})\"|「([^」]{2,80})」|『([^』]{2,80})』")
CJK_RE = re.compile(r'[\u4e00-\u9fff]')
NUM_RE = re.compile(r'\d+(?:\.\d+)?')

# 年份等与故事无关的数字，不参与承诺检查
NUM_IGNORE = {'2024', '2025', '2026', '2027'}


def _quotes(text):
    """抽出引号内的中文引语片段（>=2 汉字）。"""
    out = []
    for a, b, c, d in QUOTE_RE.findall(text or ''):
        q = a or b or c or d
        if q and len(CJK_RE.findall(q)) >= 2:
            out.append(q)
    return out


def check_hook_promise(hook, title, body):
    """钩子/标题里的引语与数字，必须在装配后的正文出现。

    返回 [(code, msg, ctx), ...]；内容干净返回 []。

    ⚠️ body 必须是**装配后**的正文（含扩写段落），否则会误报。
    """
    issues = []
    body = body or ''
    src = (hook or '') + ' || ' + (title or '')

    for q in _quotes(src):
        if q not in body:
            issues.append((
                'HOOK_PROMISE',
                f'钩子/标题承诺的引语「{q}」在正文里没有 —— '
                f'读者点进来想看的就是这句话',
                q))

    for n in NUM_RE.findall(src):
        if n in NUM_IGNORE:
            continue
        if n not in body:
            issues.append((
                'HOOK_PROMISE',
                f'钩子/标题出现的数字「{n}」在正文里没有 —— '
                f'标题的数字必须能在正文里对上',
                n))
    return issues


# ==================== 待插入 lint_content_consistency.py 的代码块 ====================

CONSTS_BLOCK = '''# ── HOOK_PROMISE（2026-11-06）─────────────────────────────
QUOTE_RE = re.compile(r"'([^']{2,80})'|\\"([^\\"]{2,80})\\"|「([^」]{2,80})」|『([^』]{2,80})』")
CJK_RE = re.compile(r'[\\u4e00-\\u9fff]')
NUM_RE = re.compile(r'\\d+(?:\\.\\d+)?')
NUM_IGNORE = {'2024', '2025', '2026', '2027'}


def _quotes(text):
    """抽出引号内的中文引语片段（>=2 汉字）。"""
    out = []
    for a, b, c, d in QUOTE_RE.findall(text or ''):
        q = a or b or c or d
        if q and len(CJK_RE.findall(q)) >= 2:
            out.append(q)
    return out


'''

FUNC_BLOCK = '''def check_hook_promise(hook, title, body):
    """钩子/标题承诺的引语与数字，必须在装配后的正文出现。

    🔴 2026-11-06 实测新增的第八类缺陷：钩子承诺的具体场景/引语/数字，
    正文经常一个字都没有 —— 读者点进来想看的画面看不到 = 标题党翻车。
    当时 10 条长文**全部**命中，且 audit/lint/脚本全程绿灯。

    ⚠️ body 必须是**装配后**的正文（含扩写段落），否则会误报。
    """
    issues = []
    body = body or ''
    src = (hook or '') + ' || ' + (title or '')

    for q in _quotes(src):
        if q not in body:
            issues.append(('HOOK_PROMISE',
                           f'钩子/标题承诺的引语「{q}」在正文里没有',
                           q))

    for n in NUM_RE.findall(src):
        if n in NUM_IGNORE:
            continue
        if n not in body:
            issues.append(('HOOK_PROMISE',
                           f'钩子/标题出现的数字「{n}」在正文里没有',
                           n))
    return issues


def _hook_promise_body(topic, ext):
    """装配正文：story_a + dialogue + ending + story_b + ending + 扩写。

    ⚠️ 只测 story_a 会误报 —— 很多兑现段写在扩写里。
    """
    def g(k):
        return str(topic.get(k, '') or '')
    body = '\\n'.join(x for x in (g('story_a'), g('story_a_dialogue'),
                                  g('story_a_ending'), g('story_b'),
                                  g('story_b_ending')) if x)
    if ext:
        ea, eb = _ext_pair(ext)
        if ea:
            body += '\\n' + ea
        if eb:
            body += '\\n' + eb
    return body


'''

LINT_CALL_BLOCK = '''
            # ⑤ 钩子/标题承诺兑现：引语与数字必须在装配后的正文出现
            #    ⚠️ 2026-11-06 新增。必须接进主流程 ——
            #    「写了函数」≠「规则生效」（ORPHAN 就是这么空转了两晚）。
            hook_body = _hook_promise_body(t, ext)
            for code, msg, ctx in check_hook_promise(
                    t.get('hook', ''), t.get('title', ''), hook_body):
                issues.append({'pool': pool_name, 'direction': direction,
                               'field': '钩子/标题承诺', 'code': code,
                               'message': msg, 'context': ctx.strip()})
'''

SELF_TEST_BLOCK = '''    # ⑦ HOOK_PROMISE：钩子/标题承诺必须在正文兑现
    ok = check_hook_promise(
        "王阿姨说：'我老了，不想拖累你们。'",
        "67岁老人被三个儿子轮流养老",
        "王阿姨说：'我老了，不想拖累你们。'她今年67岁。")
    if ok:
        failed.append('正确兑现的钩子承诺被误报为缺陷')
    bad = check_hook_promise(
        "侄子发来一条消息，只有四个字：'大伯，我忙。'",
        "63岁大伯给侄子出了20万学费",
        "李大爷63岁，有个侄子叫小强。")
    if not bad:
        failed.append('钩子承诺的引语未在正文兑现，未被发现')
    # 数字承诺（标题里的年龄）同样必须兑现
    bad2 = check_hook_promise(
        "他72岁，存了40万。", "72岁老人存了40万",
        "老陈头62岁那年开始存钱。")
    if not bad2:
        failed.append('标题里的年龄/数字未在正文兑现，未被发现')
'''


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 0

    path = sys.argv[1]
    src = open(path, encoding='utf-8').read()

    # ① 注入模块级常量 + _quotes()
    if 'def _quotes(' not in src:
        anchor = 'def _cn(s):'
        if src.count(anchor) != 1:
            print(f"❌ 找不到常量插入锚点 ({src.count(anchor)} hits): {anchor}")
            return 1
        src = src.replace(anchor, CONSTS_BLOCK + anchor, 1)
        print("✅ 注入模块级常量 + _quotes()")

    # ② 注入 check_hook_promise + _hook_promise_body
    if 'def check_hook_promise(' not in src:
        anchor = 'FIELD_CHECKERS = ('
        if src.count(anchor) != 1:
            print(f"❌ 找不到函数插入锚点 ({src.count(anchor)} hits): {anchor}")
            return 1
        src = src.replace(anchor, FUNC_BLOCK + anchor, 1)
        print("✅ 注入 check_hook_promise() + _hook_promise_body()")

    # ③ 接进 lint() 主流程
    if "'钩子/标题承诺'" not in src:
        anchor = ("                   'field': fname, 'code': code,\n"
                  "                                   'message': msg, 'context': ctx.strip()})\n"
                  "    return issues")
        if src.count(anchor) != 1:
            print(f"❌ 找不到 lint() 插入锚点 ({src.count(anchor)} hits)")
            return 1
        src = src.replace(
            anchor,
            anchor.replace("    return issues",
                           LINT_CALL_BLOCK.rstrip() + "\n    return issues"),
            1)
        print("✅ 接进 lint() 主流程")

    # ④ 注入自检算例
    if 'HOOK_PROMISE：钩子/标题承诺必须在正文兑现' not in src:
        anchor = "    if failed:\n        print('❌ 解析器自检失败"
        if src.count(anchor) != 1:
            print(f"❌ 找不到自检插入锚点 ({src.count(anchor)} hits)")
            return 1
        src = src.replace(anchor, SELF_TEST_BLOCK + '\n' + anchor, 1)
        print("✅ 注入 _self_test() 算例（正例不报 + 反例必报）")

    open(path, 'w', encoding='utf-8').write(src)
    print(f"\n✅ 已写入 {path}")
    print("下一步：")
    print(f"  python3 -m py_compile {path}")
    print(f"  python3 {path} --pool <script.py> --extensions <ext.py>")
    print("  （退出码必须单独看，别用管道吞掉）")
    return 0


if __name__ == '__main__':
    sys.exit(main())
