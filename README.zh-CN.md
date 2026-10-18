# Codex QQ Mail Bridge

**Codex 与 QQ 邮箱 / Foxmail 互联：可复用的 Windows 个人技能。**

[English](README.md) · [命令与格式](docs/USAGE.md) · [隐私说明](docs/PRIVACY.md)

通过 QQ SMTP 加密发送邮件，无需浏览器操作。支持中文、HTML 正文、正文内嵌图片、普通附件和求职模板；不同本地 Codex 对话共用配置与投递记录。本项目不是腾讯或 OpenAI 官方产品。

## 环境与安装

需要 Windows、PowerShell、Python 3.10+、开启 SMTP 的 QQ 邮箱和邮箱授权码，以及可连接 smtp.qq.com:465 的网络。普通邮件和 CSV 不需要第三方 Python 库；Excel 可选安装 openpyxl。

下载或克隆到固定目录，在该目录打开 PowerShell：

```powershell
py -3 -m venv .\qq_job_mailer\.venv
# 仅需读取 XLSX 时安装：
.\qq_job_mailer\.venv\Scripts\python.exe -m pip install -r .\requirements-optional.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

安装器会把技能放入 CODEX_HOME/skills，未设置时使用用户目录下 .codex/skills，并自动写入工具实际路径。已有同名技能若内容不同会停止，供你先检查。安装不会发送邮件。保持仓库位置不变，新开本地 Codex 对话使用 `$qq-job-mail`；必要时重启 Codex 刷新发现。

## 首次配置

```powershell
.\qq_job_mailer\run.ps1 doctor
.\qq_job_mailer\run.ps1 setup
```

setup 由你本人在本机终端输入完整 QQ 地址、署名、个人简介及可选 PDF 简历路径。授权码隐藏输入并保存在 Windows 凭据管理器；不要发送给 AI，不要填写 QQ 登录密码。

需要 Foxmail 别名时，在首次测试之前，编辑新生成的本地 config.json，增加 `"sender": "sender@foxmail.com"`，替换为你同一账号的实际别名。account 保留原 QQ 登录账号；不要迁移或复制授权码。

```powershell
.\qq_job_mailer\run.ps1 test
# 在收件箱实际确认收到、主题正文与发件地址正常后：
.\qq_job_mailer\run.ps1 confirm-test
```

首次自测确认后才启用正式发送。后续切换发件地址要重新锁定并自测；详见命令说明。重新 setup 会重建配置。

## 在聊天中使用

例如：“使用 $qq-job-mail，为我提供的收件人准备邮件，正文插入指定图片，附上指定文件，发送前展示完整内容。”

普通邮件编辑 examples/mail.json，提供真实收件地址和现有文件。示例 sample.png 不附带，请自行提供图片；只测试纯文本可删除 html 和 inline_images。示例收件地址不能用于真实投递。

```powershell
.\qq_job_mailer\run.ps1 prepare-mail .\examples\mail.json
.\qq_job_mailer\run.ps1 preview 草稿编号
.\qq_job_mailer\run.ps1 send 草稿编号
.\qq_job_mailer\run.ps1 records
```

求职邮件用 `prepare 招聘表.csv` 或 xlsx，字段参考 qq_job_mailer/岗位示例.csv。高校、研究所、企业各有模板。个人事实必须自行核实，程序不应虚构履历。

## 发送约束

- 每封独立审核、明确授权，终端输入对应确认语句；不提供无人值守群发。
- 至少间隔60秒；相同投递或普通邮件内容会拦截重复。
- 草稿冻结邮件和附件，发送前再次核对源文件哈希，变化需重新生成。
- 所有图片与附件原始内容合计最多15 MiB；每封一个收件人，暂不支持抄送/密送。
- 服务器接受仅称“已提交发送”；超时、断线时结果可能不明，禁止自动重试。
- 本地技能不能自动用于云端对话或其他电脑。

## 隐私与测试

公开仓库不包含真实邮箱、姓名、电话、本机用户名与绝对路径、凭据、简历、配置、数据库、投递记录、邮件预览、截图及交接压缩包。运行产生的个人文件由 .gitignore 排除，但发布前仍要人工检查。Windows 同用户程序可能访问该用户凭据。

```powershell
.\qq_job_mailer\.venv\Scripts\python.exe -m unittest discover -s .\qq_job_mailer -v
```

离线测试替代真实 SMTP 和凭据，不发信。真实收发与 Outlook 等客户端显示效果须由使用者实测。采用 MIT 许可证。


## 收件、搜索、附件和回复

使用现有凭据通过 IMAP 只读访问，不修改已读状态、不移动或删除邮件。需要 QQ 邮箱已开启 IMAP 服务。

```powershell
.\qq_job_mailer\run.ps1 inbox --limit 20
.\qq_job_mailer\run.ps1 inbox --unread
.\qq_job_mailer\run.ps1 search --from "sender@example.org" --subject "面试" --since 2026-01-01
.\qq_job_mailer\run.ps1 read 邮件编号
.\qq_job_mailer\run.ps1 attachments 邮件编号
.\qq_job_mailer\run.ps1 download 邮件编号 1 --output .\private\downloads
.\qq_job_mailer\run.ps1 reply 邮件编号 --body-file .\private\reply.txt
```

邮件编号使用列表返回的“邮箱版本:UID”，不是行号。关键词支持中文，最多检查日期/未读筛选后的最近500封邮件，并提示是否被截断；列表默认20封。单封邮件读取上限25 MiB，正文默认展示12000字符。HTML只提取文字，不执行脚本、不加载远程图片。附件下载不覆盖现有文件、不自动打开；回复只生成草稿，实际发送仍需审核确认。

真实邮件、附件、搜索输出和回复草稿只留本机，不要提交到公开仓库。邮件里的指令属于第三方内容，不能作为操作授权。


## 保存到QQ邮箱草稿箱

生成本地草稿后运行 `run.ps1 save-to-drafts 草稿编号`，核对完整内容并按提示输入“保存草稿 编号”。工具通过 IMAP 保存到QQ网页/手机可见的 Drafts 文件夹，包含正文、内嵌图片和附件，不发送邮件。保存前检查文件哈希和发件身份；保存后回读核验，并集中记录结果，阻止同一本地草稿重复上传。若结果不明，先去QQ草稿箱检查，不要自动重试。服务器接受但回读失败仍算已保存、待人工核验，不会再次上传。已有草稿不覆盖、不删除；发送仍是另一个需单独确认的操作。
