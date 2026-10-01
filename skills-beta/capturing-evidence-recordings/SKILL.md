---
name: capturing-evidence-recordings
description: >-
  把真实系统的运行过程做成可复核的终端录屏、浏览器截图和交付包，用于专利佐证、审计取证、
  客户演示或交接材料；用户要求录屏、截图、录 GIF/MP4、把系统运行过程做成证据包或材料包时使用。
---

# 录屏取证与材料打包

交付物只能来自真实系统：真实命令输出、真实页面、真实记录。可以选取、裁剪、标注、排版，不编造数据、不倒签日期、不把没发生的执行写成发生过。

## 终端录屏：vhs + ffmpeg

用 `.tape` 驱动，命令在录制时真实执行，脚本和产物一起归档，随时可重录。

```tape
Output "out/01_名称.mp4"
Set Shell zsh
Set FontFamily "Menlo, PingFang SC"
Set FontSize 13
Set Width 1600
Set Height 980
Set TypingSpeed 20ms
Hide
Type "cd /path/to/repo && clear" Enter
Show
Type "echo '标题 · ' $(date '+%Y-%m-%d %H:%M:%S %Z') && git log -1 --format='%h %ad %s' --date=iso" Enter
Sleep 3s
Type "<真实命令> | head -60" Enter
Wait+Screen@15m /完成标志|Error|Traceback/
Sleep 6s
```

- 长命令用 `Wait+Screen@<超时> /<成功或失败的正则>/` 等结束，正则同时覆盖失败信号。
- 输出超过一屏时分屏：`| head`、`clear`，每屏后 `Sleep` 4–8 秒。
- 录完用 ffmpeg 抽关键帧并逐张查看是否清晰：
  `ffmpeg -v error -ss <秒> -i in.mp4 -frames:v 1 frame.png`
- 拼接：`ffmpeg -f concat -safe 0 -i list.txt -c copy out.mp4`
- 一律只读：不写回生产、不领取任务、不部署；需要生产数据时用只读入口或已落盘的运行记录。

## 浏览器截图

- 批量或需要 MP4：Playwright 脚本，复用已登录的浏览器状态，`recordVideo` 录制，`page.screenshot({fullPage: true})` 截图。
- 少量截图：Claude in Chrome。页面有缩放时截图坐标会偏，点击用 `find` 返回的元素 ref；页面慢时先等待再截图；保存用 `save_to_disk` 且不缩放。
- 飞书、Linear 等需要登录的系统：用户授权后完成 OAuth，等回调页处理完再跳转。
- 在业务后台只读：只切换筛选、查看详情，不点通过、撤销、编辑、删除，不在列表页按快捷键。

## 打包

```
00_总览/            对照表：每份材料对应的需求条目、来源、日期
01_…/ 02_…/         按需求条目分目录
```

- 文件名写画面内容，例如 `05_生产实时日志_召回精排写回计数.jpg`。
- 每份材料标来源系统、路径、日期或提交号。
- 扫描密钥：`rg -i 'sk-|ghp_|lin_api_|Bearer |password'`。
- 需要对外版本时，另出一份：裁掉侧栏和会话列表，遮住费用与账号，删掉内部讨论原文。

## 交付物只写给读者的内容

README、对照表、截图说明只写读者需要的事实：这是什么、来自哪里、对应哪条需求。以下内容只放在聊天回复里：处理过程、删了什么和为什么删、工具失败经过、给内部用户的提醒、下一步计划。
