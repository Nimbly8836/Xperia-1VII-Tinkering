# Termux:Widget 脚本与配置说明

把两个切卡脚本放到手机桌面，在“实体卡 + 内置 eSIM”和“双实体 SIM”之间切换。

## 前提

- 安装签名来源兼容的 Termux 和 Termux:Widget，打开 Termux 完成初始化；不要混装不同签名来源。
- 安装并启动 Shizuku，授权 Termux 使用。无线调试/ADB 启动的 Shizuku 在手机重启后需重新启动。
- 不需要刷机包、编译或重新刷机；已有可用配置时无需覆盖。

切换会短暂中断通信，完成后到 SIM 设置检查卡片状态。

官方说明：[Termux:Widget](https://github.com/termux/termux-widget#setup-instructions)、[Shizuku](https://shizuku.rikka.app/guide/setup/)。

## 1. 复制 rish

从已安装的 Shizuku 终端使用说明中导出同版本的 `rish` 和 `rish_shizuku.dex` 到 `Documents/xperia-rish/`。它们不随本仓库提供。

在 **Termux** 中执行；如果尚未授权共享存储，先运行 `termux-setup-storage` 并授权：

```bash
mkdir -p "$HOME/.local/share/xperia-rish"
chmod 700 "$HOME/.local/share/xperia-rish"
cp -i "$HOME/storage/shared/Documents/xperia-rish/rish" "$HOME/.local/share/xperia-rish/rish"
cp -i "$HOME/storage/shared/Documents/xperia-rish/rish_shizuku.dex" "$HOME/.local/share/xperia-rish/rish_shizuku.dex"
chmod 700 "$HOME/.local/share/xperia-rish/rish"
chmod 400 "$HOME/.local/share/xperia-rish/rish_shizuku.dex"
```

保留 DEX 的只读权限，不要直接从共享存储运行。脚本已设置 Termux 应用标识和所需环境变量。

可先检查 rish 是否可用（不切卡）：

```bash
RISH_APPLICATION_ID=com.termux RISH_PRESERVE_ENV=0 \
  /system/bin/sh "$HOME/.local/share/xperia-rish/rish" -c '/system/bin/id'
```

无线调试/ADB 启动时通常显示 `uid=2000`；若服务或授权报错，先解决再继续。

## 2. 复制两个脚本

将仓库中的 [`enable-esim.sh`](../scripts/termux-widget/enable-esim.sh) 和 [`enable-dual-sim.sh`](../scripts/termux-widget/enable-dual-sim.sh) 下载到手机的 `Documents/xperia-widget/`，然后在 Termux 执行：

```bash
mkdir -p "$HOME/.shortcuts"
chmod 700 "$HOME/.shortcuts"
cp -i "$HOME/storage/shared/Documents/xperia-widget/enable-esim.sh" "$HOME/.shortcuts/enable-esim.sh"
cp -i "$HOME/storage/shared/Documents/xperia-widget/enable-dual-sim.sh" "$HOME/.shortcuts/enable-dual-sim.sh"
chmod 700 "$HOME/.shortcuts/enable-esim.sh" "$HOME/.shortcuts/enable-dual-sim.sh"
```

遇到同名文件先核对再覆盖。放在 `~/.shortcuts/`，不要放进 `tasks/`，也不要用软链接代替复制。

## 3. 使用 Widget

1. 在桌面添加 Termux:Widget 小组件，点击刷新，确认显示两个脚本。
2. 确认 Shizuku 正在运行并已授权 Termux，不在进行重要通话。
3. 点击 `enable-esim.sh` 切到实体卡 + 内置 eSIM，或点击 `enable-dual-sim.sh` 切回双实体卡。
4. **点击切换后检查 SIM 状态**，然后回到终端按 Enter 关闭窗口。

这不是三卡同时工作。失败时先检查 Shizuku 和实际卡片状态，不要连续点击；不要公开 EID、ICCID、激活码或配对信息。
