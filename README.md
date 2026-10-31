# 折腾 Xperia 1 VII

记录我的 Xperia 1 VII 折腾过程、实机结果和脚本：**FS72 保留数据跨刷 FS54，以及内置 eSIM / 双实体 SIM 切换**。

> [!WARNING]
> **这是高风险、非官方的实验性刷机工具，不是面向所有 Xperia 的通用刷机方案。**
>
> **虽然我自己的手机刷机成功、数据保留且双向切卡可用，但不代表你的手机也会成功。操作可能导致无法开机、通信功能异常、数据或 eSIM 配置丢失，甚至设备损坏、无法恢复。**
>
> **请自行评估风险并承担全部操作后果；不能接受风险就不要使用。** 本项目按 MIT 许可证“按原样”提供，不保证成功、保留数据或失败后可恢复。先做好独立备份，准备好双重认证和运营商 eSIM 的恢复方式。不要把成功案例、测试通过或“不主动清数据”当作安全保证。

## 能实现什么

| 功能 | 当前结果与边界 |
|---|---|
| 港版 FS72 跨刷 FS54，同时保留原有用户数据 | 我的 `.265` 实机成功，不 Root、不解锁 Bootloader、不主动清用户数据；不保证其他设备成功 |
| 识别并使用内置 eSIM | 我的手机已识别内置 eUICC，套餐已激活并联网，不是依赖外置物理 eSIM 卡 |
| “实体卡 + eSIM ↔ 双实体 SIM”切换 | 我的实机已验证可以自由往返切换，不需要反复刷固件 |
| Termux 脚本快速切换 | 我的实机已验证可用；具体脚本和权限配置尚未收录 |
| macOS / Linux 工具链 | 支持离线准备、编译、模拟及刷写入口；Linux 已做离线验证，尚未做 Linux 真机刷写 |

**不代表三张卡同时工作。** 进入 eSIM 模式时，第二张实体卡暂停读取；切回实体卡模式时，eSIM 可能暂时不可访问。

已经刷好、切卡正常的手机，无需为了使用本仓库再刷一次。完整证据与未验证事项见[实机记录](docs/verified-results.md)。

## 我的实机环境与使用约束

### 成功案例的环境

| 项目 | 本次成功案例 |
|---|---|
| 原始硬件 | 港版 Xperia 1 VII **XQ-FS72**，SKU `c001526` |
| 刷前系统 | 原厂 **`71.1.A.2.265 release-keys`** |
| 刷入系统 | **FS54 EU/UK `71.1.A.2.265`** 的固定原始包 |
| 安全状态 | Bootloader locked、Verified Boot green；不 Root、不解锁 |
| 刷前条件 | DSDS，电量至少 60%；Flash 模式核对 V36 Bootloader、商业根哈希及其他门禁 |
| 原刷机电脑 | macOS + APFS |
| Linux 验证环境 | Debian 12 arm64 容器；仅编译、测试和无 USB 模拟，**不是 Linux 实机成功案例** |

### 适用范围不能自行扩大

- **目前实际刷写入口只支持上述 `.265` 同版本跨刷，不是通用升级工具。** 从 `.248` 升到原厂 `.265` 也不由本工具完成。
- **`71.2.A.2.35` 尚未开放实际写入。** Sony 官方元数据标为 Android 17、boot delivery 为 V40，而旧流程是 Android 16 / V36。两套新版包已下载校验，可做[离线审查](docs/firmware-71.2.A.2.35-research.md)，但不能拿本页步骤从 `.265` 升到 `.35`。
- 不要修改版本、哈希、设备身份、槽位或 Bootloader 检查来“适配”其他机器；没有通用 `force`。
- 我的双向切卡成功，不等于重启保持、OTA、所有运营商、通话短信或 VoLTE/VoWiFi 已全面验证，也不等于本仓库 Python 封装已经实机验收。该封装目前保留命令核对和 mock 测试结论。
- 没有已验证的港版 `.265` 无损恢复流程。SEA 包不是 HK 原机恢复包，旧版本不能默认当降级包，**B 槽不是完整回滚快照**。
- 本项目非 Sony、Qualcomm 或 Google 官方工具，不提供固件、套餐或解锁服务。

## 普通用户怎么用

**先核对上面的设备与版本，读完风险，再操作。以下命令均从仓库根目录执行。**

### 1. 先判断是否需要准备或编译

| 你的情况 | 应该怎么做 |
|---|---|
| 第一次下载这个仓库 | **必须先完成文末的[离线准备与编译](#离线准备编译与验证)**：安装依赖、放好固定固件、生成候选、编译并模拟；仓库不提供现成的刷写二进制 |
| 已在当前电脑准备好，且构建输入/二进制未变化 | 可以直接使用下面的 `trial.py run`，程序会重新校验；**不要求每次刷机前都重新编译** |
| 源码、构建输入变化，或换了系统/CPU 架构 | 重新编译并测试；不能复制旧收据或修改摘要绕过 |
| 已刷好，只想切换 SIM/eSIM | 使用 Python 切换脚本即可，**不需要编译 C 刷写器，也不需要重新刷机** |
| 想升级 `.35` 或使用其他机型/版本 | 停止，本页实际刷写流程不适用 |

**`trial.py run` 不会替你下载固件、生成候选或自动编译。** 因此“直接用脚本刷机”指的是完成首次准备后，通过脚本进入受限流程，不是 clone 后一条命令即可安全刷机。

### 2. 准备完成后，运行刷机脚本

开始时手机应仍符合刷前 HK FS72 `.265` 基线，正常开机、解锁并授权 USB 调试；只连接目标手机，关闭其他刷机工具。Linux 用户先按[指南](docs/linux.md)配置磁盘空间和 USB 权限。

```bash
adb devices
python3 flash-kit/trial.py run --serial YOUR_ADB_SERIAL
```

之后按脚本提示操作：

1. 脚本检查固定源包、候选和构建摘要，创建独立只读镜像副本；此时不写手机。
2. 只读核对 Android 身份和电量。
3. 按提示正常关机，**按住音量减连接 USB** 进入 Sony Flash 模式，不是 Fastboot。
4. 脚本先只读检查目标设备、V36/商业根哈希、A/B 布局、传输能力、电量和 `snapshot-update-status=none`。
5. 全部检查通过后，才要求完整输入下方确认短语；**输入正确后会开始真实写入**。

```text
FS72_TO_FS54_265_A_KEEP_DATA_TRIAL
```

所有镜像完成后才设置 A 槽，不自动重启。看到 `TRIAL_COMPLETE_NO_REBOOT_FUNCTIONAL_RESULT_NOT_VERIFIED` 后，等待程序退出，按提示断开 USB 正常开机，检查原锁屏、重要数据、SIM 和 eSIM。

**写入完成不等于功能验收通过。** 检查失败就停止；写入中断或结果未知时，不要盲目重试、切槽、清数据或换包补刷。只读检查失败与已经部分写入的处理不同，完整流程、电量时效和失败处理见 [TRIAL.md](flash-kit/TRIAL.md)。

### 3. 刷好后切换 SIM / eSIM

切换时手机必须正常运行 Android、USB 调试已授权，版本符合切换脚本门禁。脚本默认只预览，只有加 `--execute` 且手动确认后才会发送一次请求。**切换会中断相关卡的通信；实机成功案例不替代本次状态检查。**

切到 eSIM：

```bash
# 仅预览，不运行任何 ADB 命令
python3 scripts/switch_sim.py esim --serial YOUR_ADB_SERIAL
# 确认需要切换后，单独执行并按提示确认
python3 scripts/switch_sim.py esim --serial YOUR_ADB_SERIAL --execute
```

确认短语是 `SWITCH_TO_ESIM_MAPPING_CHECKED`。之后到系统设置检查 EID / 添加 eSIM，按运营商正规流程添加套餐，并实际验证联网。已经处于 eSIM 模式且正常工作时，不必重复执行。

切回双实体卡：

```bash
python3 scripts/switch_sim.py physical --serial YOUR_ADB_SERIAL
python3 scripts/switch_sim.py physical --serial YOUR_ADB_SERIAL --execute
```

确认短语是 `SWITCH_TO_PHYSICAL_MAPPING_CHECKED`。先核对两张实体卡已插好，以及当前逻辑槽、物理槽和 MEP 端口映射；**双 eSIM 同占一个物理 eUICC 或无法确认映射时，不要盲目执行**。本机只读诊断可查看 `adb -s YOUR_ADB_SERIAL shell dumpsys phone`，但输出含敏感信息，不要原样上传；不能判读就停止。

脚本不删除 eSIM 套餐，不替你下载套餐，也不自动重试、重启或回切。完成后自行检查卡识别、联网和所需业务。`Broadcast completed` 只表示广播调用返回，**不证明切换或业务已经成功**。

### 4. Termux 快速切换

我的实机已验证 Termux 脚本快速切换可用，具体脚本和权限配置待收录。目前不提供猜测的一键命令。

**普通 Termux 应用进程不等同于 ADB shell。** 实际使用无线 ADB、Shizuku/rish、root 还是其他方式，须以原脚本为准；不能直接删去电脑端命令的 `adb shell` 前缀就认为等价。此结果不代表 `.35`、重启保持或 OTA 已验证。

## 原理与写入边界

### 为什么能尝试保留数据跨刷

受限刷写器复用固定 Newflasher 源码的 SIN/USB 传输部分，外加命令白名单、固定源 ZIP/镜像摘要、设备核对和交互确认。使用**原始、未改写的 FS54 `.265` SIN**，不是自行修改系统镜像再绕过签名。

14 个镜像的固定顺序：

```text
bluetooth → dsp → featenabler → modem → pvmfw → spuservice
→ super → dtbo → vendor_boot → init_boot → boot → recovery
→ vbmeta_system → vbmeta
```

- 有槽的目标只写 A，`super` 为共享目标，会更新逻辑分区与 LP 元数据；全部完成后才设置 A 槽。**共享 super 意味着 B 槽不是完整回滚快照。**
- 保留现有 V36 Bootloader；不写 GPT、bootloader delivery、SPC/CustomerID 或身份/密钥 TA。
- 不直接对 `userdata`、`metadata`、`persist`、`modemst1/2`、`misc` 发出 erase/flash。
- 必须说明的例外：协议会写 **TA 会话标志 `2:10100` 的 1/0**；`set_active:a` 会更新启动控制状态；新系统/基带首次启动也可能修改自身数据。

所以“保留数据”是“不主动擦写指定用户/个体分区”的策略，**不是数据必然保留或所有非系统字节不变的保证**。哈希只证明文件与本项目固定样本一致，不等于主机完成 Sony 签名验证；设备自身仍负责启动信任链校验。

### 为什么需要切换 SIM 类型

有 LPA（eSIM 管理组件）和设置菜单，不等于无线层已经把可切换槽接到内置 eUICC。本机成功切换前，Qti 返回：

```text
supported = [PHYSICAL, PHYSICAL_ESIM]
current   = [PHYSICAL, PHYSICAL]
```

请求 eSIM 后，组合槽当前类型变为 `ESIM`，系统出现内置 eUICC 和 32 位 EID。观察到的路径为：

```text
SIM_TYPE_UPDATE_ACTION（定向 com.qti.phone）
  → QtiUiccSwitcher
  → QtiRadioConfigProxy / QtiRadioConfigAidl
  → vendor IQtiRadioConfig.setSimType
  → UIM / 卡源切换
```

`0 = PHYSICAL`、`1 = ESIM` 是此入口的枚举值，不是 NV 地址、硬件寄存器或可直接照抄的 HAL 枚举。接收端寻找支持 physical+eSIM 的槽；脚本不猜 `extra_slot_id`。它切的是 SIM 来源，不是默认数据卡，也不是删除或启停某个 eSIM profile。

以下是脚本封装的广播，**仅供原理审查，实际使用优先选择有确认保护的脚本**：

```bash
adb -s YOUR_ADB_SERIAL shell am broadcast --user 0 --receiver-foreground \
  --receiver-permission android.permission.READ_PRIVILEGED_PHONE_STATE \
  -a com.android.euicc.service.SIM_TYPE_UPDATE_ACTION -p com.qti.phone \
  --ei com.android.euicc.service.extra_sim_type 1
```

`--receiver-permission` 限制接收者应持有的权限，不是给 shell 提权或绕过系统检查。系统拒绝时就停止。不要替换成名称相似的 `com.android.action.enable_esim`，那是另一条 NTN profile 路径。

这个案例不证明未跨刷的原厂 FS72 一定不能直接切换，也不证明跨刷是访问 eUICC 的唯一必要条件。

## 离线准备、编译与验证

**这一节是首次刷机的必需准备，不是只有开发者才需要做的可选工作。** 放在文末是为了先说明功能、适用范围和用户流程；没有完成它，就不能直接执行真实刷写入口。以下准备命令均不访问手机。

### 1. 安装主机依赖

- Python 3.10+、`pkg-config`、`libusb`、Android Platform Tools（`adb`）。
- macOS：Xcode Command Line Tools，APFS 文件系统；镜像副本使用 APFS clone。
- Linux：GCC/Clang、OpenSSL libcrypto、zlib、expat 开发包；独占创建全量镜像副本，不要求 APFS/reflink。完整安装与权限步骤见 [Linux 指南](docs/linux.md)。Windows 暂不支持。
- 磁盘：原始 ZIP 约 4.2 GiB、候选镜像约 5 GiB；Linux 每次会话另复制约 5 GiB，并保留至少 3 GiB 余量。注意 `/tmp` 可能是容量不足的 tmpfs。

macOS 示例：

```bash
xcode-select --install  # 已安装时跳过
brew install python pkg-config libusb
brew install --cask android-platform-tools
```

### 2. 自行取得固定原始 ZIP

本仓库不分发固件，也不包含私人下载资源链接。通过合法、可信来源取得**完全相同的原始 ZIP**，放到：

```text
firmware-downloads/packages/fs54-eu-71.1.A.2.265/
  APP-SW_PDX256_GLOBALEEA-A4_USER_71.1.A.2.265_X-FLASH-ALL-B083_COM.zip
```

固定 SHA-256：

```text
d272727231a31b22402c4564f387ebd91b9958e5ba8485f8925ea2cb9d813465
```

只有 SIN、重新压缩的 ZIP、其他地区或新版包都不能替代。旧版本可能不再提供；**取不到相同包就停止，不修改哈希绕过**。

原 `download_official.py` 依赖未公开的本地 metadata，**不是 clone 后即用的下载器，也不是刷机的必需步骤**，详见[下载说明](firmware-downloads/README.md)。手动取得的正确原始 ZIP 可直接交给下面的校验流程。

### 3. 首次生成候选、编译和模拟

从仓库根目录执行。下面用 `&&` 串联，任何一步失败都不继续：

```bash
python3 -m unittest discover -s flash-kit -p 'test_*.py' -v && \
python3 -m unittest discover -s scripts -p 'test_*.py' -v && \
python3 flash-kit/flashkit.py audit && \
python3 flash-kit/flashkit.py prepare && \
python3 flash-kit/build_trial.py && \
python3 flash-kit/trial.py simulate
```

- `prepare` 只在候选目录不存在时使用，不覆盖或合并已有目录。**已有候选时，把这一项换成 `python3 flash-kit/flashkit.py verify`**，不要直接重复 prepare，也不要随意删掉已有材料。
- 构建会生成 `flash-kit/build/fs72-preserve-trial`、生成源码和 `build-receipt.json`，并运行原生安全自测。**只运行 Python 包装脚本不能替代这个原生程序。**
- `simulate` 使用固定真实镜像做协议模拟，不访问 USB；模拟成功不证明真机一定成功。
- 源码、构建输入或二进制摘要不匹配时，运行入口会拒绝；换系统/CPU 架构也需重新构建。单纯修改 README 不要求重新编译。
- 候选名中的 `NOT-APPROVED` 和 `flash_allowed: false` 表示候选本身不授权刷机。`flashkit.py execute` 始终拒绝；实际入口是另行确认的 `trial.py run`。

**全部通过后，再回到上面的“普通用户怎么用”执行刷机命令。不要把裸 Newflasher 放进候选目录运行。**

### 4. 额外测试与新版离线审查

安装原生依赖后，可运行不需要固件、以 USB 拒绝桩隔离设备访问的原生测试：

```bash
XPERIA_NATIVE_TESTS=1 python3 -m unittest discover -s flash-kit -p 'test_*.py' -v
```

未设置该变量时会明确跳过原生测试；未安装 `defusedxml` 时会明确跳过新版 XML 包解析测试。包含全部依赖的测试方式、新版固定包摘要与 `audit_upgrade.py` 用法见[新版研究](docs/firmware-71.2.A.2.35-research.md)。**离线审查通过不会开放 `.35` 刷写。**

### 5. 文件、隐私与许可证

- [`flash-kit/`](flash-kit/README.md)：准备、构建、受限执行器和测试；[详细刷写与失败处理](flash-kit/TRIAL.md)。
- [`scripts/switch_sim.py`](scripts/switch_sim.py)：Python + ADB 切换脚本，无需 C 编译。
- [`docs/verified-results.md`](docs/verified-results.md)：实机结果、用户反馈与尚未验收的边界。
- 固件、解包文件、构建产物、日志、下载 metadata、原始设备 dump 和会话授权均被忽略，不随仓库提交。不要用 `git add -f` 上传它们。
- 不公开序列号、IMEI、EID、ICCID、手机号、eSIM 激活码、配对码、私钥或带临时参数的下载 URL。

原创代码与文档采用 [MIT](LICENSE)。Newflasher 同为 MIT，保留 Munjeni 的版权声明，见[第三方说明](THIRD_PARTY_NOTICES.md)；Sony/Qualcomm/Google 固件和外部依赖不因本仓库而改为 MIT。
