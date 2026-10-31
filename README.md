# Xperia 1 VII：FS72 保留数据跨刷与 SIM/eSIM 切换

港版 **Xperia 1 VII XQ-FS72** 在不解锁 Bootloader、不 Root、不主动清除用户数据的前提下，使用固定的 **FS54 EU/UK `71.1.A.2.265`** 镜像，并通过系统 SIM 类型入口访问内置 eSIM 的实验记录和工具。

> **本机已成功：刷机后正常使用、用户确认数据保留；内置 eUICC 已识别，eSIM 套餐已激活并联网。** 这是一个实机案例，不是所有 FS72、所有固件或所有运营商的兼容性保证。**切回双实体卡、重启保持、OTA、完整通话/短信/VoLTE/VoWiFi 尚未验收。** 详见[验证范围](docs/verified-results.md)。
>
> 已经刷好且 eSIM 正常的手机，无需为了使用本仓库再刷一次或再次切卡。

## 风险与适用范围

- 真实刷写入口是 `flash-kit/trial.py run`，会写手机。`simulate` 才是无 USB 模拟；`flashkit.py` 仅负责离线准备/校验。
- 刷前基线限定为 **HK FS72、SKU `c001526`、`71.1.A.2.265 release-keys`、Bootloader locked、Verified Boot green、DSDS、电量至少 60%**。从 `.248` 升到原厂 `.265` 不在本工具的实现范围内。
- 仅为固定固件和已研究组合设计；**不要更改哈希、版本、槽位或身份检查以适配其他设备**。
- 保留数据的含义是“不主动擦写指定用户/个体分区”，不是“永不丢数据”。中断、签名/版本不兼容、首次启动迁移都可能导致无法启动或无法解密数据。**先做独立备份**，包括照片、应用数据、双重认证与运营商 eSIM 恢复材料。
- 没有经过验证的港版 `.265` 无损恢复流程；SEA 包不是原机 HK 恢复包，旧 `.248` 不能自动当降级回退包。共享 `super` 会改变逻辑分区，**B 槽不是完整回滚快照**。
- 本项目非 Sony、Qualcomm 或 Google 官方工具。不提供固件、运营商套餐或解锁服务。

## 仓库内容

| 路径 | 用途 |
|---|---|
| [`flash-kit/`](flash-kit/README.md) | 固定源包校验、14 镜像准备、macOS 原生受限刷写器及测试 |
| [`scripts/switch_sim.py`](scripts/switch_sim.py) | SIM 类型切换；默认仅打印命令，需 `--execute` 和交互确认 |
| [`firmware-downloads/`](firmware-downloads/README.md) | 原有电脑端分块下载脚本，依赖自行准备的本地 metadata；不是开箱即用下载器 |
| [`docs/verified-results.md`](docs/verified-results.md) | 脱敏后的实机结果与未验证事项 |
| [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) | Newflasher 来源、固定提交、版权与许可证 |

固件 ZIP/SIN、解包镜像、APK/JAR/DEX、下载 metadata、构建产物、日志、设备 dump、临时授权和历史研究材料均留在本地，不提交。根 `.gitignore` 采用公开文件白名单；新增文件需明确审核后放行。

## 原理

### 1. 为什么可以保留数据刷入 FS54 固件？

该流程使用**原始、未改写的 FS54 `.265` SIN**，固定源 ZIP 的 SHA-256、包成员和各镜像内容；基于固定 Newflasher 源码的 SIN/USB 传输实现，在外层加上受限命令与分区白名单。哈希校验只证明文件与本项目审核样本一致，**不等于主机完成 Sony 签名验证**，锁定设备仍由自身启动信任链校验。

写入顺序为：

```text
bluetooth → dsp → featenabler → modem → pvmfw → spuservice
→ super → dtbo → vendor_boot → init_boot → boot → recovery
→ vbmeta_system → vbmeta
```

有槽的目标只允许写 **A**；`super` 为共享目标，包含系统逻辑分区及其元数据。保留现有 Bootloader，检查商业根哈希和 V36 等条件；全部镜像完成后才设置启动槽 A。

不会直接对 `userdata`、`metadata`、`persist`、`modemst1/2`、`misc` 发出擦写命令，也不写 GPT、bootloader delivery、SPC/CustomerID 或身份/密钥 TA。**例外必须说明**：协议会写 TA 会话标志 `2:10100` 的 1/0；`set_active:a` 会更新启动控制状态；新系统/基带启动后也可能更新自身数据。因此不是“整机所有非系统字节完全不变”。

### 2. 为什么刷完还有可能没有 EID？

系统具备 LPA（eSIM 管理组件）和菜单，不等于无线层已经把可切换槽接到内置 eUICC。本机成功切换前 Qti 返回：

```text
supported = [PHYSICAL, PHYSICAL_ESIM]
current   = [PHYSICAL, PHYSICAL]
```

通过现有系统入口请求 eSIM 后，组合槽的当前类型变为 `ESIM`，系统出现内置 eUICC 和 32 位 EID，随后用户完成套餐激活并联网。

观察到的路径为：

```text
SIM_TYPE_UPDATE_ACTION（定向 com.qti.phone）
  → QtiUiccSwitcher
  → QtiRadioConfigProxy / QtiRadioConfigAidl
  → vendor IQtiRadioConfig.setSimType
  → UIM / 卡源切换
```

参数 `0 = PHYSICAL`、`1 = ESIM` 是该广播/Qti Java 层的值，**不是 modem NV 地址、硬件寄存器值或可直接套用的 HAL 枚举**。接收端寻找支持 physical+eSIM 的槽，不应猜 `extra_slot_id`。

这不是切换默认移动数据卡，也不是删除/启停某个 eSIM profile。它切换的是 SIM 来源：本机进入 eSIM 模式后第二张实体卡暂停读取；不代表三张卡可同时工作。MEP/双 eSIM 的逻辑槽映射会增加回切复杂度。

不能由这一个案例断言“原厂 FS72 一定也能直接切换”，也不能证明跨刷是访问 eUICC 的唯一必要条件。

## 操作一：准备与刷机（macOS）

以下命令均从仓库根目录执行。**先读完整节与[详细流程](flash-kit/TRIAL.md)，不要整段盲目粘贴。**

### 1. 环境

- macOS + APFS：执行器使用 `/bin/cp -c` 创建独立 Copy-on-Write 镜像快照，不支持直接照搬到 Linux/Windows 或非 APFS 文件系统。
- Python 3.10+；Xcode Command Line Tools 的 `clang`/`xcrun`。
- `pkg-config`、`libusb`、Android Platform Tools（`adb`）。
- 充足磁盘空间：源 ZIP 约 4.2 GiB，候选镜像约 5 GiB，并须保留额外空间与 APFS 写时复制空间。

```bash
xcode-select --install  # 已安装时跳过
brew install python pkg-config libusb
brew install --cask android-platform-tools
```

### 2. 自行取得固定原始 ZIP

本仓库不分发固件，也不提供私有下载资源链接。需要通过合法、可信来源取得**完全相同的原始 ZIP**：

```text
firmware-downloads/packages/fs54-eu-71.1.A.2.265/
  APP-SW_PDX256_GLOBALEEA-A4_USER_71.1.A.2.265_X-FLASH-ALL-B083_COM.zip
```

其 SHA-256 必须为：

```text
d272727231a31b22402c4564f387ebd91b9958e5ba8485f8925ea2cb9d813465
```

只有解包后的 SIN、重新压缩的 ZIP、其他地区或新版固件均不满足此输入。Sony 旧版本可能不再提供；**取不到相同包就停止，不修改固定哈希绕过**。原分块下载脚本的输入限制见[下载说明](firmware-downloads/README.md)；clone 仓库本身不会获得下载 metadata。

### 3. 离线准备、编译和验证

这些命令不会访问手机：

```bash
python3 -m unittest discover -s flash-kit -p 'test_*.py' -v
python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 flash-kit/flashkit.py audit
python3 flash-kit/flashkit.py prepare
python3 flash-kit/flashkit.py verify
python3 flash-kit/build_trial.py
python3 flash-kit/trial.py simulate
```

`prepare` 不覆盖已有候选目录；再次使用时执行 `verify`，不要混入其他文件。目录名中的 `NOT-APPROVED`、准备器的 `flash_allowed: false` 是“候选本身不授权刷写”的边界，不能通过编辑 JSON 开启。`flashkit.py execute` 始终拒绝；实际刷写另由 `trial.py run` 严格检查并征求确认。

修改构建输入后必须重新构建和测试。无 USB 模拟仍需真实固件和本地构建；仅单元测试无需固件。不要向候选目录放入裸 Newflasher 运行。

### 4. 实际写入（高风险，手动单独执行）

手机应仍是刷前 HK FS72 `.265` 基线，正常开机、解锁并授权 USB 调试；只连接目标手机。

```bash
adb devices
python3 flash-kit/trial.py run --serial YOUR_ADB_SERIAL
```

执行器会：校验输入并建快照 → 只读检查 Android 身份和电量 → 提示正常关机、按住音量减连接 USB 进入 Sony Flash 模式 → 先只读检查设备、V36/根哈希、A/B、传输能力、电量、`snapshot-update-status=none` → 要求手动输入：

```text
FS72_TO_FS54_265_A_KEEP_DATA_TRIAL
```

之后才实际写入。全部完成才设置 A 槽，不自动重启。出现 `TRIAL_COMPLETE_NO_REBOOT_FUNCTIONAL_RESULT_NOT_VERIFIED` 后，待程序退出，按提示断开 USB 正常开机，确认原锁屏和数据可用，再进行 eSIM 验收。

检查失败就停止，无通用 force。部分写入或结果不明时不要自动重试、切槽、清数据或拿其他包“补刷”。只读检查阶段失败与写入中断不同，详见[失败处理](flash-kit/TRIAL.md#失败和特殊续接)。

## 操作二：刷机后切换 SIM / eSIM

**新封装脚本已做 mock 测试，未为发布而再次操作实机。** 历史上实测成功的是相同的 eSIM 广播请求；实体卡回切仅有代码路径证据，不能当作实测成功。

要求正常 Android、USB 调试已授权、明确的 ADB 序列号。脚本会限制型号/版本/SKU、locked/green/DSDS 和 Qti 包存在，但**这些属性不是 HAL 能力或 MEP 映射检查**。先确认当前槽位映射；不适用时停止，不绕过检查。

### 切到 eSIM

```bash
# 仅预览：不运行任何 ADB 命令
python3 scripts/switch_sim.py esim --serial YOUR_ADB_SERIAL

# 读取基线后，仍需在终端输入完整确认短语才会发出一次请求
python3 scripts/switch_sim.py esim --serial YOUR_ADB_SERIAL --execute
```

确认短语：`SWITCH_TO_ESIM_MAPPING_CHECKED`。若已在 eSIM 模式且工作正常，不要重复执行。切换后到系统设置检查 EID/“添加 eSIM”，按运营商正规流程添加套餐，并实际验证联网。脚本不安装应用、不获取或上传 EID/ICCID、不替你下载套餐。

### 切回实体卡（尚未实机验收）

先核对实体卡已插好，以及当前逻辑槽、物理槽和 MEP 端口映射。双 eSIM 同占一个物理 eUICC 或无法确认映射时，**不要盲目执行**。只读诊断可在本机查看 `adb -s YOUR_ADB_SERIAL shell dumpsys phone`，但其输出包含敏感信息，不要原样上传；不能判读就停止。

```bash
python3 scripts/switch_sim.py physical --serial YOUR_ADB_SERIAL
# 确认映射、接受未经实机验收的风险后才执行：
python3 scripts/switch_sim.py physical --serial YOUR_ADB_SERIAL --execute
```

确认短语：`SWITCH_TO_PHYSICAL_MAPPING_CHECKED`。它不是删 eSIM 套餐；eSIM 可能暂时不可访问。完成后自行检查两张实体卡的识别、数据和通话，不把成功发送广播当作切回成功。

### 实际发送的是什么？

脚本封装下列已使用过的系统请求；展示供审查，建议使用有确认保护的脚本，不直接复制裸命令：

```bash
adb -s YOUR_ADB_SERIAL shell am broadcast --user 0 --receiver-foreground \
  --receiver-permission android.permission.READ_PRIVILEGED_PHONE_STATE \
  -a com.android.euicc.service.SIM_TYPE_UPDATE_ACTION -p com.qti.phone \
  --ei com.android.euicc.service.extra_sim_type 1
```

`1` 请求 eSIM，`0` 请求 physical；`--receiver-permission` 限制接收者应持有的权限，**不是给 adb shell 授权、改 UID 或绕过权限检查**。若系统拒绝发送或处理就停止，不尝试提权。不要替换为名称相似的 `com.android.action.enable_esim`，那是另一条 NTN profile 路径。

`Broadcast completed` 仅表示广播调用返回，不证明 HAL 接受、EID 出现或业务可用。超时/错误时状态可能未知，脚本不会自动重试、重启或回切。

## 公开与隐私

提交前审核暂存文件，不要 `git add -f` 上传下载目录、原始 dump 或会话目录。尤其不要公开序列号、IMEI、EID、ICCID、手机号、eSIM 激活码、下载 URL 临时参数和凭据。仓库仅保存脱敏结果摘要；不随仓库发布编译好的刷机二进制。

## 许可证

本项目原创代码与文档采用 [MIT](LICENSE)。固定引用的 Newflasher 源码同为 MIT，保留 Munjeni 版权和完整许可声明，详见[第三方说明](THIRD_PARTY_NOTICES.md)。Sony/Qualcomm/Google 固件及外部依赖不因本仓库而改为 MIT。
