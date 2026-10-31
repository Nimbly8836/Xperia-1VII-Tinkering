# Termux:Widget + Shizuku/rish 快速切卡

本页记录用户实机使用的方案：**Termux:Widget → Termux Bash 脚本 → Shizuku/rish → 系统 SIM 类型广播**。用户已验证“实体卡 + eSIM ↔ 双实体 SIM”往返切换。

仓库收录两个英文文件名、英文提示的版本，切换命令、环境变量、退出码处理与用户提供的脚本一致：

| 脚本 | 请求 |
|---|---|
| [`enable-esim.sh`](../scripts/termux-widget/enable-esim.sh) | `extra_sim_type=1`，请求内置 eSIM |
| [`enable-dual-sim.sh`](../scripts/termux-widget/enable-dual-sim.sh) | `extra_sim_type=0`，请求实体卡模式 |

> [!WARNING]
> **点击 Widget 就会发送真实切换请求，没有预览、二次确认或自动设备/版本检查。** 脚本末尾的 `Press Enter` 是命令结束后的关窗暂停，不是执行前确认。
>
> 切换会中断相关卡的通信。适用案例是港版 FS72 硬件、FS54 `.265` 系统；不能因为脚本能启动就认定其他版本、`.35` 或任意 MEP 映射也适用。退出码 0 / `Broadcast completed` 不证明实际切换成功，必须到 SIM 设置和实际业务中确认。操作风险自负。

如果希望默认预览并检查型号/版本，使用[电脑端 Python 脚本](../scripts/switch_sim.py)，不要把它的保护措施误认为这两个快捷脚本也具备。

## 1. 已确认的环境

- 用户已提供原始 `内置eSIM.sh` 和 `双实体卡.sh` 的完整内容。
- ADB 只读检查确认：XQ-FS54、`71.1.A.2.265 release-keys`、SKU `c001526`、locked/green；安装了 Termux、Termux:Widget、Shizuku。
- 实际脚本调用的是 **`$HOME/.local/share/xperia-rish/rish`**，不是直接运行共享目录中的文件。
- 实机成功来自用户反馈。本次收录只做英文命名/提示、静态核对和 Bash 语法检查，没有为发布而在手机上再次切卡。
- 不需要 C 编译、固件包或重新刷机。脚本本身不调用 `su`，但需要事先启动并授权的 Shizuku 服务；不能把普通 Termux 应用进程当成 ADB shell。

## 2. 安装并启动相关应用

1. 安装 Termux 和 Termux:Widget，注意使用兼容的签名来源，不混装 F-Droid 与 GitHub 的不同签名构建。先打开 Termux，完成初始环境安装。
2. 安装 Shizuku，按其官方说明启动服务。无 Root 的 Android 11+ 可使用无线调试启动，也可按官方电脑 ADB 方式启动；不需要为本项目 Root 或解锁。
3. 允许 Termux 使用 Shizuku。首次通过 rish 请求时如果出现授权提示，确认请求来自你自己的 Termux 后再授权。

Shizuku 通过无线调试/ADB 启动时，设备重启后需要重新启动服务。**这是 Shizuku 服务的生命周期，不是“重启后 SIM 模式一定改变或保持”的证明。**

官方说明：[Termux:Widget](https://github.com/termux/termux-widget#setup-instructions)、[Shizuku 启动指南](https://shizuku.rikka.app/guide/setup/)。

## 3. 准备 rish（首次配置）

**已经按原方案正常使用的手机跳过此节，不要覆盖工作中的 rish。**

从所安装的 Shizuku 的终端使用说明中，导出同版本的 `rish` 和 `rish_shizuku.dex`。这两个辅助文件不随本仓库分发，也不要使用来源不明的 DEX。

以下假设导出到共享存储的 `Documents/xperia-rish/`。如 Termux 尚未取得共享存储访问权限，先在 Termux 中运行 `termux-setup-storage`，按系统提示授权。接着在 **Termux** 内执行，复制前若已有文件，先核对，不要盲目覆盖：

```bash
mkdir -p "$HOME/.local/share/xperia-rish"
chmod 700 "$HOME/.local/share/xperia-rish"
cp -i "$HOME/storage/shared/Documents/xperia-rish/rish" "$HOME/.local/share/xperia-rish/rish"
cp -i "$HOME/storage/shared/Documents/xperia-rish/rish_shizuku.dex" "$HOME/.local/share/xperia-rish/rish_shizuku.dex"
chmod 700 "$HOME/.local/share/xperia-rish/rish"
chmod 400 "$HOME/.local/share/xperia-rish/rish_shizuku.dex"
```

任何文件缺失或复制失败都应先停下来处理。将 DEX 放在 Termux 私有目录并去除写权限，是为满足该 rish 启动器对 Android 14+ 不可加载可写 DEX 的检查；不要直接从共享存储执行那份副本。

原脚本在调用时指定：

```text
RISH_APPLICATION_ID=com.termux
RISH_PRESERVE_ENV=0
```

- `RISH_APPLICATION_ID` 指定调用应用为 Termux，因此对于本次看到的 rish 启动器，即使模板保留默认 `PKG`，也会使用此环境变量；无需因此编辑模板。它不代表更改 UID 或绕过 Shizuku 授权。
- `RISH_PRESERVE_ENV=0` 沿用用户验证时的设置，不擅自改成其他值。
- `/system/bin/sh` 用来启动 rish，广播用 `/system/bin/am`，避免把 Termux 的可执行文件路径带入系统命令。

可先用**不切卡**的身份查询验证 rish 通路，以下命令仍在 Termux 中执行：

```bash
RISH_APPLICATION_ID=com.termux RISH_PRESERVE_ENV=0 \
  /system/bin/sh "$HOME/.local/share/xperia-rish/rish" -c '/system/bin/id'
```

通过无线调试/ADB 启动 Shizuku 时预期是 shell 身份（通常 `uid=2000`）。若仍是普通 Termux UID、显示授权/服务错误，或出现你未预期的 root 身份，先核对 Shizuku 启动方式与授权，不继续切卡。

## 4. 安装英文 Widget 脚本

在 Termux 的私有 HOME 中取得本仓库。需要 Git 时可使用 `pkg install git`；首次克隆示例：

```bash
git clone https://github.com/Nimbly8836/Xperia-1VII-Tinkering.git "$HOME/Xperia-1VII-Tinkering"
```

已有仓库则使用现有目录，不重复克隆。以下从仓库根目录执行；实际路径不同时相应调整 `cd`：

```bash
cd "$HOME/Xperia-1VII-Tinkering"
mkdir -p "$HOME/.shortcuts"
chmod 700 "$HOME/.shortcuts"
cp -i scripts/termux-widget/enable-esim.sh "$HOME/.shortcuts/enable-esim.sh"
cp -i scripts/termux-widget/enable-dual-sim.sh "$HOME/.shortcuts/enable-dual-sim.sh"
chmod 700 "$HOME/.shortcuts/enable-esim.sh" "$HOME/.shortcuts/enable-dual-sim.sh"
```

这一步仅安装文件，不切卡。`cp -i` 遇到同名文件会询问，更新前请自行核对。原中文文件不会自动删除；确认英文版本安装正确后，可自行决定是否保留旧快捷入口，避免混淆。

**放在 `~/.shortcuts/`，不要放在 `~/.shortcuts/tasks/`。** 前者是前台终端脚本目录；本脚本会显示结果并等待回车。`tasks/` 是后台任务目录，不适合这个交互暂停流程。不要用指向仓库工作目录的软链接代替复制；插件对脚本的规范路径有限制，应复制文件到正确目录。

## 5. 添加桌面 Widget 并使用

1. 在桌面添加 Termux:Widget 小组件，或按插件说明创建对应快捷方式。
2. 点击 Widget 的刷新按钮，确认显示 `enable-esim.sh` 和 `enable-dual-sim.sh`。
3. 确认 Shizuku 正在运行、已授权 Termux，当前卡槽/MEP 映射符合已验证场景，不在进行重要通话或依赖移动网络的任务。
4. **决定切换后才点击相应脚本。点击即发送一次请求。**
5. 终端显示退出码；到系统 SIM 设置检查卡片状态，再验证需要的联网/通话业务。
6. 返回终端按 Enter 关闭窗口。

终端显示“命令结束”不等于 HAL 已执行成功；脚本保存的是 rish 命令的退出码，并非完整业务验收结果。失败或超时后不要连续点击两个按钮“试回来”，先确认实际卡片状态和 Shizuku 服务状态。

## 常见问题与边界

- **找不到 rish / DEX**：核对私有目录路径及两个文件是否同版本；不要把网盘固件放到这里。
- **Shizuku 未运行或权限拒绝**：按官方方式启动服务、核对 Termux 授权。脚本不会自动配对、启动服务或请求 Root。
- **Widget 不显示文件**：核对 `~/.shortcuts/`、文件/目录权限、Termux 与插件签名来源，刷新 Widget。不要为了调试开启并公开包含私人信息的完整日志。
- **广播返回成功但卡未切换**：返回值不是业务成功证明，停止重复点击并检查系统状态。
- **新版固件、不同机型、双 eSIM/MEP 特殊映射**：这两个简短脚本不做自动门禁，不能直接推广。`.35` 仍未获本项目实刷/切卡兼容性验证。
- **隐私**：不要上传配对码、Shizuku/ADB 私钥、EID、ICCID、激活码或原始电话 dump。

两个脚本只请求 SIM 来源切换，不写固件、不删除套餐、不重启、不自动重试；用户的成功案例不构成其他环境的保证。刷机和切卡的总体风险见[根 README](../README.md)。
