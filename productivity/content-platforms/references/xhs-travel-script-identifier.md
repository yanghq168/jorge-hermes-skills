# 小红书旅游攻略脚本辨析（踩坑记录）

##背景

`~/.hermes/cron/scripts/`目录下存在两个名字相近的小红书旅游脚本，历史上反复混淆，导致执行错脚本或修改错脚本。

|脚本 | 文件大小（约） |实际状态 |何时启用 |
|------|------|------|------|
| `xhs-travel-daily.py` |78 KB | ✅ **当前主用脚本**，2026-06仍在 cron 注册 |每天23:00 |
| `xiaohongshu-travel-daily.py` |12 KB | ⏸旧版，2026 年早期使用过，已被 `xhs-travel-daily.py`取代 |历史上21:30 |

##区分方法

**文件名靠前的版本号不是判断依据**——名字相似但实际是新版/旧版。判断依据是：

1. **大小**：当前版约78 KB（含完整20 个景点 DESTINATIONS + HTML模板 + 林芝篇风格规范）
2. **日志文件**：`~/.hermes/cron/logs/` 下 `xhs-travel-daily.log`（已建）才是新脚本的日志
3. **cronjob实际任务**：当前 cron调度的 `023 * * * python3 .../xhs-travel-daily.py >> logs/xhs-travel-daily.log2>&1`
4. **visited追踪文件**：`.xhs_travel_visited.json`（与 `xiaohongshu-travel` 不互通）

## 用户描述对应

当用户说"小红书旅游攻略"时，**默认指 `xhs-travel-daily.py`（每天23:00）**，不是 `xiaohongshu-travel-daily.py`。

如果用户明确提到路径 `~/.hermes/cron/scripts/xhs-travel-daily.py`，**直接执行该文件即可**——这是 cron调度的同一脚本。

##手动触发验证

```bash
# ✅ 推荐：用 cron调度的同一脚本
python3 /home/ubuntu/.hermes/cron/scripts/xhs-travel-daily.py

# ✅ 也可以走 logs（确保 shell 转义正确）
python3 /home/ubuntu/.hermes/cron/scripts/xhs-travel-daily.py >> /home/ubuntu/.hermes/cron/logs/xhs-travel-daily.log2>&1
```

预期输出：

```
📍 小红书旅游攻略生成器 -2026-MM-DD HH:MM
📌今日景点: <景点名>
📌攻略标题: ...
HTML邮件已生成
✅邮件已发送: <景点名>
```

执行后应同时看到：
-邮件到达 `569545015@qq.com`
- `.xhs_travel_visited.json` 中追加新景点名
-终端退出码0

## ⚠️常见踩坑

###1. Shell 转义 `2>&1`粘到文件名

当通过 Python `terminal()` 调用 shell 时，**`"${script}"2>&1` 这种紧贴写法会被解释为带 `2>&1` 后缀的文件名**：

```python
# ❌错误：终端找不到 'xhs-travel-daily.py2' 这个文件
terminal(f'python3 "{script}" > "{log}"2>&1')
# →报错：can't open file '/.../xhs-travel-daily.py2': No such file or directory
```

**解决**：用空格分隔 token，或先 `cd &&整行命令`：

```python
# ✅正确：空格分隔，避免拼接到文件名
terminal(f'python3 "{script}" > "{log}"2>&1')
# 或
terminal(f'cd /home/ubuntu/.hermes/cron/scripts && python3 xhs-travel-daily.py > {log}2>&1')
```

###2. 直接运行不重定向也行

脚本本体自带 `print()` 输出，无需重定向到日志文件也能看到结果：

```python
result = terminal(f'python3 "{script}"', timeout=600)
print(result.get("output", ""))
```

适合临时手动验证，不污染 cron 日志。

###3. 不要删除 `xiaohongshu-travel-daily.py`

虽然已停用，但**不要主动删除**——它记录了早期版本的实现细节，删除后无法回溯对比。保留作为参考。

###4. 两个 visited 文件不要合并

- `.xhs_travel_visited.json` → `xhs-travel-daily.py`（主脚本）
- `.xhs_escape_visited.json` → `xhs-escape-weekend.py`（周末出逃）

两个池子**故意分开**，因为它们推的是不同类型的目的地（长期攻略 vs周末短途）。合并会导致跨池推送，破坏去重语义。

##排错清单

|现象 | 检查项 |
|------|--------|
|脚本退出码非0 | `python3 -m py_compile <script>` 检查语法 |
|邮件未到达 | `~/.hermes/.env` 中 `QQ_EMAIL_AUTH_CODE` 是否配置；SMTP端口465 是否通 |
|景点重复出现 | `.xhs_travel_visited.json` 是否被外部清空；DESTINATIONS数量是否够大 |
|选了不在 DESTINATIONS里的景点 | `_search_new_destinations()` fallback路径触发，可能因百度搜索规则改版失效 |
