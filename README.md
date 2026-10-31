# 折腾 Xperia 1 VII

> **高风险，后果自负。** 我自己的手机已刷机成功、保留数据，并能切换 eSIM / 双实体卡，但不保证你的手机也能成功。刷机可能造成无法开机、数据丢失或设备损坏。请先备份重要数据，准备好账号和 eSIM 的恢复方式；不能接受风险就不要操作。

## 需要什么

- **手机**：港版 Xperia 1 VII **XQ-FS72**，原厂 **`71.1.A.2.265`**，未解锁、未 Root，保持双卡模式，电量至少 **60%**。程序会自动核对手机是否符合要求。
- **目标**：固定的 **FS54 EU/UK `71.1.A.2.265`**。这不是 `.35` 升级方案，也不适用于任意机型或版本；不符合就停止，不要修改检查条件。
- **电脑**：当前已构建的包分别用于 **Mac Apple Silicon（macOS 27.0.1+，APFS）** 和 **Linux ARM64（Debian 12）**。Intel/AMD 电脑暂无预构建包，Windows 暂不支持。准备好数据线和足够磁盘空间；Linux 另需约 5 GiB 副本空间和至少 3 GiB 余量，见 [Linux 指南](docs/linux.md)。
- **运行环境**：Python **3.10+**、ADB、libusb 运行库；刷机包必须对应电脑的**系统和 CPU 架构**。包不内置 Python、ADB 或第三方运行库，不是零依赖。

## 刷机：按顺序操作

### 1. 安装依赖，下载刷机包

macOS 已安装 Homebrew 时，在终端执行：

```bash
brew install python libusb
brew install --cask android-platform-tools
```

Linux 按 [Linux 指南](docs/linux.md)安装运行依赖、配置 USB 权限及临时目录空间。使用预构建包不需要编译工具。

**刷机包下载链接待补充。** 不要把 GitHub 的源码 ZIP 当成预构建刷机包；链接补齐前不能通过本节取得包。

取得发布者提供、对应你电脑系统和架构的包后，先用发布者在包外提供的 SHA-256 核对 ZIP，再解压。具体方法见[发行包说明](docs/distribution.md)。**不需要原始固件 ZIP、不需要源码、不需要编译。**

### 2. 启动

1. 手机正常开机，解锁屏幕，打开 USB 调试并授权自己的电脑。
2. 只连接这一台目标手机，关闭其他刷机工具。
3. **macOS：双击解压目录中的 `Start.command`。** **Linux：在解压目录打开终端，执行 `bash start.sh`。**
4. 如果提示未授权，在手机上允许 USB 调试；如果提示型号或版本不符合要求，就停止，不要强刷。

### 3. 跟随提示刷写

1. 程序先核对文件、手机身份和电量。
2. 提示后正常关机，**按住音量减连接 USB**，进入 Sony Flash 模式（不是 Fastboot）。
3. 等待设备检查通过。
4. 确定承担风险后，完整输入下面的确认短语。**确认后会真实写入：**

```text
FS72_TO_FS54_265_A_KEEP_DATA_TRIAL
```

5. 看到“写入序列完成”后，等待程序退出，再按提示断开 USB、正常开机。程序不会自动重启手机。
6. 检查原锁屏、重要数据、SIM 和 eSIM；“写入完成”不等于所有功能正常。

**写入中断或结果未知时，不要盲目重试、切槽、清数据或补刷。** 保存私有日志，先分析已完成步骤。电量时效、写入边界和失败处理见 [TRIAL.md](flash-kit/TRIAL.md)。

## 刷好后切换 SIM / eSIM

已经刷好的手机不需要再刷一次，按下面的方法切换即可。

- 手机桌面快捷切换：按 [Termux:Widget 脚本与配置说明](docs/termux-widget.md)安装 Shizuku/rish 和两个脚本。
- 点击 `enable-esim.sh`：实体卡 + 内置 eSIM；点击 `enable-dual-sim.sh`：双实体卡。
- 切换后到 SIM 设置检查卡片状态。eSIM 模式下，第二张实体卡暂停使用，不是三卡同时在线。

电脑端可使用源码中的 `scripts/switch_sim.py`，无需编译；默认只预览，加 `--execute` 后仍需手动确认。例如从仓库根目录执行：

```bash
python3 scripts/switch_sim.py esim --serial YOUR_ADB_SERIAL
python3 scripts/switch_sim.py esim --serial YOUR_ADB_SERIAL --execute
# 切回双实体卡：将 esim 换成 physical
```

切换时通信会短暂中断，不要在通话或重要网络任务中操作。

## 原理与边界

刷机工具使用 14 个原始 FS54 `.265` 镜像，不解锁、不 Root，不主动清除用户数据；但系统更新和刷写失败仍可能导致数据丢失。它保留原 Bootloader，不是完整备份或恢复工具。具体写入范围见 [TRIAL.md](flash-kit/TRIAL.md)，实机结果见[验证记录](docs/verified-results.md)。

SIM 脚本通过系统接口切换实体卡与内置 eSIM，不删除套餐。已跨刷手机的 `.265 → .35` 有独立的[实验性升级入口](docs/upgrade-run.md)，会更新 Bootloader，尚未实机升级；不能使用本页的 `.265` 包代替。

## 源码构建（使用预构建包可跳过）

以下命令从仓库根目录执行，仅供自行构建者；发行包打包步骤见 [distribution.md](docs/distribution.md)。

### 1. 安装构建依赖

macOS 需要 Xcode Command Line Tools、Python 3.10+、`pkg-config`、`libusb`；实际连接手机还需 ADB：

```bash
xcode-select --install  # 已安装则跳过
brew install python pkg-config libusb
brew install --cask android-platform-tools
```

Linux 构建依赖与权限见 [Linux 指南](docs/linux.md)。换系统或 CPU 架构需重新构建。

### 2. 自行取得固定原始 ZIP

通过合法、可信来源取得完全相同的原始 ZIP，放到：

```text
firmware-downloads/packages/fs54-eu-71.1.A.2.265/
  APP-SW_PDX256_GLOBALEEA-A4_USER_71.1.A.2.265_X-FLASH-ALL-B083_COM.zip
```

固定 SHA-256：

```text
d272727231a31b22402c4564f387ebd91b9958e5ba8485f8925ea2cb9d813465
```

其他地区、版本、单独 SIN 或重新压缩的 ZIP 不能替代。取不到就停止，不改哈希。仓库下载脚本依赖未公开的本地 metadata，不是即用下载器，见[下载说明](firmware-downloads/README.md)。

### 3. 校验、编译、模拟

```bash
python3 -m unittest discover -s flash-kit -p 'test_*.py' -v && \
python3 -m unittest discover -s scripts -p 'test_*.py' -v && \
python3 flash-kit/flashkit.py audit && \
python3 flash-kit/flashkit.py prepare && \
python3 flash-kit/build_trial.py && \
python3 flash-kit/trial.py simulate
```

已有候选时将 `prepare` 换成 `verify`，不覆盖旧材料。源码、输入或二进制变化后重新构建，不编辑收据绕过。源码入口为 `python3 flash-kit/trial.py run --serial YOUR_ADB_SERIAL`；运行前仍须阅读上面的刷机流程及 [TRIAL.md](flash-kit/TRIAL.md)。不要直接运行裸 Newflasher。

## 隐私与许可

不公开设备日志、序列号、IMEI、EID、ICCID、激活码、配对码或私钥。发行包只收录固定固件镜像、预编译程序、运行脚本、许可和清单，不收录个人数据，详见[发行说明](docs/distribution.md)。

原创代码与文档采用 [MIT](LICENSE)；Newflasher 版权见[第三方说明](THIRD_PARTY_NOTICES.md)。固件和外部依赖不因本仓库而改为 MIT；分发前须自行确认相应授权。
