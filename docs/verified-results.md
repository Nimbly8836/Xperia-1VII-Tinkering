# 实机结果与验证边界

本页由本地成功记录和用户反馈整理，不公开设备序列号、IMEI、EID、ICCID、套餐或原始电话 dump。历史研究中“未刷写”“未取得能力”“未识别内置 eUICC”等中间状态，不能替代这里的最新结果。

## 已确认的单机组合

- 原设备：港版 Xperia 1 VII XQ-FS72，SKU `c001526`。
- 刷前基线：原厂 `71.1.A.2.265`，锁定 Bootloader、Verified Boot green、DSDS。
- 目标：FS54 EU/UK `71.1.A.2.265` 原始固定包，受限 14 镜像流程。
- 用户明确反馈：**刷机成功，数据保留**。这是用户实际使用验收，不是全盘逐字节一致性或数据可恢复性证明。
- 刷后记录：仍为锁定、Verified Boot green；不 Root、不解锁、不主动清用户数据。

## 内置 eSIM 的结果

在未插入可插拔物理 eSIM 卡的前提下，原两个槽均为普通实体 SIM，`mIsEuicc=false`、EID 为空。Qti 报告第二槽支持 `PHYSICAL_ESIM`，但当前为 `PHYSICAL`。

通过定向 `com.qti.phone` 的 `SIM_TYPE_UPDATE_ACTION` 请求 `extra_sim_type=1` 后：

- HAL 回应 `errorCode=0`；Qti 当前类型从 `[0,0]` 变为 `[0,1]`，支持类型为 `[0,3]`。
- 系统报告内置 eUICC 存在、`mIsEuicc=true`、EID 长度 32。
- 用户随后确认套餐已经激活并联网。
- 取样时 eUICC 报告 MEP_A1、两个端口，映射为 `{0=1, 1=-1}`；这不是其他设备可直接套用的固定映射。
- 在最初 eSIM 取样阶段，第二实体卡暂停读取；当时助手未执行回切、重启或删除套餐。**后续用户已自行验证完整往返切换，见下节。**

这些证据支持“本机内置 eUICC 可访问，且 eSIM 实际可用”，不只是出现设置菜单，也不是外置 eSIM 卡的成功案例。

## 后续用户实机验收：双向切换与 Termux

用户补充反馈：

> 我的实际机器已经验证能自由切换 eSIM 和实体双 SIM 卡，并且能用 Termux 脚本快速切换。

据此将 **“实体卡 + eSIM ↔ 双实体 SIM”完整往返** 更新为**用户实机验证通过**，不再沿用“仅有代码路径、回切未验证”的旧结论。Termux 快速切换也记为用户已验证。

这次切换成功的结论依据用户实际使用反馈，不是助手新采集的切卡日志。随后 ADB 只读核查确认当前仍为 XQ-FS54 / `71.1.A.2.265 release-keys`、SKU `c001526`、locked/green，且安装了 Termux、Termux:Widget 和 Shizuku。

用户进一步提供了 `~/.shortcuts/` 中两个原始脚本，确认实际通路是 **Termux:Widget → Termux Bash → Shizuku/rish → 系统广播**。脚本用 `RISH_APPLICATION_ID=com.termux RISH_PRESERVE_ENV=0` 调用 `$HOME/.local/share/xperia-rish/rish`，再通过 `/system/bin/am broadcast` 分别请求 `extra_sim_type=1` 和 `0`。普通 Termux 进程不等同于 ADB shell，脚本依赖已授权的 Shizuku 服务。

已收录[英文文件名/提示的两个版本](../scripts/termux-widget/)及[配置指南](termux-widget.md)。核心请求与退出码处理保持不变；本次没有在手机上重新运行它们。Widget 版本直接发送请求、不含电脑端 Python 封装的预览/身份检查，因此仍不将用户反馈视为 Python 封装、`.35` 或其他环境的验收。

## 未验证／不能外推

| 项目 | 状态 |
|---|---|
| 重启后保持模式 | 尚未测试 |
| OTA 后仍可用、无损回退 | 尚未验证 |
| 所有运营商、通话短信、VoLTE/VoWiFi | 未全面验证 |
| 其他 FS72 批次/地区/版本 | 不可由单机推断 |
| 未跨刷的原厂 FS72 可否直接启用 | 尚未证明；不宣称跨刷是唯一必要条件 |
| LPA 原流程未自动切换的准确根因 | 仍未独立定位，不归咎于某个未经证实的 flag |
| 本仓库 Python 切换封装实机执行 | 本次反馈未指定使用该封装；目前保留命令核对和 mock 测试结论 |
| Termux 全新环境安装复测 | 脚本已由用户提供，配置步骤按脚本及官方指南整理；未清空实机环境重新安装验证 |

历史成功不替代操作前核对。电脑端 Python 封装保留交互确认；用户提供的 Widget 快捷脚本点击即发送，末尾回车不是事前确认。两者均不能把广播回执视为硬件切换成功，已正常工作的手机不必重复运行。
