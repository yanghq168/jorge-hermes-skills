# `no_agent` scripts falsely reported as `error`

**Class:** Hermes cron misreporting. Parent skill: `../SKILL.md`
(§2 "Read the most recent output log" → §3 "Decode the common errors").

A Hermes cron job can show `last_status: error` while the script actually
succeeded (exit 0). This is a platform reporting bug, not a script bug — and it
is the mirror image of the `last_status=ok`-masks-delivery-failure case
(`case-m-last-status-masking.md`). Both directions of the scheduler's status
field are untrustworthy; the outbox and the script's own log are the ground
truth.

Migrated from the `content-platforms` skill, where it was filed as a
cron-diagnostics note; it belongs to the cron-debugging class.

---

# Cron 诊断手册

## 区分两类"失败"

Hermes cron 任务的 `last_status: error` 有两种完全不同的含义，排查方向完全不同。

### A）no_agent 脚本：误报 error（Exit 0 = 成功）

`no_agent: true` 的脚本退出码 0，但 Hermes 仍显示 `last_status: error`。这是平台的报告 bug，不是脚本问题。

**特征**：
- `last_status: error` 但 `last_run_at` 时间戳正常推进
- `last_delivery_error: null`
- 脚本自己写的 log 文件显示 ✅ 成功

**诊断命令**：
```bash
# 检查脚本自己的 log（最可信）
tail ~/.hermes/cron/logs/xhs-escape-weekend.log
tail ~/.hermes/cron/logs/wechat-article-daily.log
tail ~/.hermes/cron/logs/skill-backup.log

# 手动重跑验证
python3 ~/.hermes/cron/scripts/xhs-escape-weekend.py; echo "Exit: $?"
bash ~/.hermes/cron/scripts/skill-backup.sh; echo "Exit: $?"

# 检查 cron 系统自己的记录
cronjob(action='list')  # 看 last_run_at 是否推进
```

**已知误报任务**（Exit 0，实际成功）：
- `xhs-escape-weekend.py` — 周末出逃计划
- `wechat-article-daily.py` — 公众号情感长文
- `skill-backup.sh` — Skills 备份到 GitHub
- `agency-backup.sh` — Agency 备份到 GitHub

### 2026-10-28 验证：当前所有报 error 的 job 都是 no_agent

实测 `~/.hermes/cron/jobs.json` 中 `last_status == "error"` 的 job 共 4 个，
**全部** `no_agent=True`：

| Job | script | no_agent | enabled |
|-----|--------|----------|---------|
| 小红书周末出逃计划 | `cron/scripts/xhs-escape-weekend.py` | True | True |
| 公众号情感长文 | `cron/scripts/wechat-article-daily.py` | True | True |
| Skills备份到GitHub | `cron/scripts/skill-backup.sh` | True | True |
| Agency备份到GitHub | `agency-backup/scripts/agency-backup.sh` | True | True |

而所有 `no_agent=False`（agent-mode）的 job 报的都是 `ok`。**这与"调度器
状态字段在两个方向都不可信"的判断一致**：`last_status` 是 Hermes 对
`no_agent` 脚本退出码的映射问题，不是脚本本身坏了。

### ⚠️ 第三种情况：部分成功（partial success）—— 不要一律当成误报

`wechat-article-daily.py` 的日志长这样：

```
============================================================
HTML邮件已生成
============================================================
❌ 邮件发送失败: Connection unexpectedly closed

✅ MD文件已生成: /home/ubuntu/article-wechat-20261027-8a26c7.md
```

这里 **exit code 非 0**（所以 `last_status: error` 是"正确"的），但脚本
**已经产出了内容**——HTML 已生成、`.md` 文件已落盘（实测
`/home/ubuntu/article-wechat-*.md` 每天都有新文件）。SMTP 失败只影响**投递
环节**，不影响**生产环节**。

**处理原则（"部分成功" ≠ "误报" ≠ "彻底失败"）：**

| 情况 | 判定依据 | 处置 |
|------|----------|------|
| **误报** | exit 0，脚本自报成功 | 忽略 `last_status: error`；查脚本自己的 log |
| **部分成功** | exit 非 0，但产物已落盘（`.md` / outbox HTML） | 产物已保住；只修投递链路；**不要重跑脚本**（会产生第二份不同内容） |
| **彻底失败** | exit 非 0，且无任何产物 | 按 `../SKILL.md` §1–§7 的完整诊断循环走 |

`last_status: error` 本身**不能**区分后两者。区分方法是看产物：
`ls -lt /home/ubuntu/article-wechat-*.md` 或
`ls -lt ~/.hermes/cron/outbox/<platform>/*.html`。
这正是 `../SKILL.md` "run-count rule" 的依据 —— 已有产物就不要再跑一次。

### B）LLM-driven 任务：真正失败

`no_agent: false`（默认）的任务，error 状态通常是真的有问题。

**诊断方向**：
```bash
# 检查 cron agent 的执行日志
tail -50 ~/.hermes/logs/agent.log | grep <job_name>
grep "<job_id>" ~/.hermes/logs/errors.log
```

### C）agent-mode 任务：**会话迭代预算耗尽**（2026-11-22 实测）—— 第三种误报

这一类既不是 A（no_agent 误报）也不是 B（真失败），而是**报告会话自己
没跑完**。内容早已生成并投递成功，但调度器把该夜记成了 `error`。

**特征（三个一起看才成立）**：
1. `jobs.json` 的 `last_error` **不是异常摘要，而是一段 markdown 报告正文**
   —— 开头形如 `RuntimeError: ## 📰 头条号日报 · 2026-11-22（20:30）`。
   正常的异常摘要会带 `Traceback` 或短错误串。
2. `~/.hermes/logs/agent.log` 里能搜到：
   `Turn ended: reason=max_iterations_reached(N/N)`。
   N 通常等于本次运行实际生效的迭代上限（实测本部署为 **60**）。
   ⚠️ 注意配置路径：`cron/scheduler.py` 读的是 `agent.max_turns` →
   `max_turns` → 默认 90；`agent.max_iterations` 是**另一条**路径，
   **以日志里实际的 N 为准**，不要凭配置猜。
3. `~/.hermes/logs/errors.log` 里有
   `ERROR cron.scheduler: Job '<name>' failed: RuntimeError: ## …`。

**机理**（`cron/scheduler.py` → `run_job()`）：agent 返回
`result["failed"] is True` 或 `result["completed"] is False` 时，
调度器 **raise RuntimeError(报告正文)** —— 于是报告文本被当成异常消息
写进了 `last_error`，`last_status` 被置为 `error`。**这不是投递失败。**

**实测根因链（2026-11-22）**：
`cron-job-debugging/SKILL.md` 已达 **96,668 字符**（`skill_manage` 上限
100,000）⇒ 当晚要往 SKILL.md 追加案例时**连续 3 次被拒**
（`SKILL.md content is 100,314 characters (limit: 100,000)`）⇒ agent
在同一个失败调用上反复重试 ⇒ 迭代额度耗尽 ⇒ 报告没写完 ⇒ 调度器记
`error`。**文章本身当晚已通过飞书附件送达**（`message.get` 回查
`msg_type=file`、`deleted=False`、文件名匹配）。

**⇒ 结论：`last_status: error` + 内容已送达 = 报告会话超预算，不是内容管线坏了。**
处置：① **不要重跑生产脚本**（Case R：会产生第二份产物）② 补做该夜漏掉的
持久化动作（README 追加等）③ **把 SKILL.md 压到安全水位**（≤ 75k 字符），
否则每晚都会重演。

**排查命令**：
```bash
# 1. 是不是迭代耗尽？
grep "max_iterations_reached" ~/.hermes/logs/agent.log | tail -5

# 2. last_error 是报告正文还是异常摘要？
python3 -c "
import json
d = json.load(open('$HOME/.hermes/cron/jobs.json'))
for j in d['jobs']:
    e = j.get('last_error') or ''
    if e:
        kind = 'REPORT-BODY(会话超预算)' if e.lstrip().startswith('RuntimeError: #') else 'EXCEPTION'
        print(j['name'], '|', j.get('last_status'), '|', kind, '|', e[:90].replace(chr(10),' '))
"

# 3. 本技能自己的体积（关键！）
python3 -c "print(len(open('/home/ubuntu/.hermes/skills/cron-job-debugging/SKILL.md',encoding='utf-8').read()))"
```

**通用教训**：`skill_manage` 因体积拒绝写入时，**不要重试同一个写入** ——
先把 SKILL.md 压缩，或把细节写进 `references/` 支持文件
（`skill_manage(action='write_file', file_path='references/...')`）。

---

## 快速定位任务状态

```bash
# 列出所有任务及关键字段
cronjob(action='list')

# 已知误报状态的任务，手动验证
python3 ~/.hermes/cron/scripts/xhs-escape-weekend.py 2>&1 | tail -5
python3 ~/.hermes/cron/scripts/wechat-article-daily.py 2>&1 | tail -5
```

---

---

## Update log

- **v1.0.0 (2026-05-31)** — created under `content-platforms` as a cron-diagnostics note.
- **Moved** to `cron-job-debugging` — this is Hermes cron diagnosis, not content
  generation.
