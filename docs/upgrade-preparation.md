# 我的手机升级到 `.35`：准备进度

目标：港版 FS72 硬件、已经跨刷的 FS54 `.265` → FS54 `71.2.A.2.35`，尽量保留数据。

**电脑端固件已经整理，检查工具已经准备；还不能开始实际升级。下一步是 USB 连接下的刷机模式只读检查。** 本轮没有刷写、切槽、清数据或重启手机。

## 当前需要用户做的事

1. 把手机充到 **60% 以上**。
2. 使用 **USB 数据线**连接电脑，先保持 Android 正常开机，授权 USB 调试。
3. 确认准备好后，再进行下面的只读检查。不要提前进入 Flash 模式，以免无法读取本次电量和系统信息。

本轮最后一次读取时，手机只有无线 ADB 连接、没有在充电，电量为 41%。这不是永久状态；实际检查前会重新读取。程序已修正为选择 USB 连接，避免将无线 ADB 的 mDNS 名称误当成 Flash 模式硬件序列号。

## 已完成

### 当前系统核对

只读确认 XQ-FS54、`71.1.A.2.265 release-keys`、Android 16、SKU `c001526`、locked/green、DSDS、启动槽 A。

手机报告的 `ro.boot.vbmeta.digest` 与从固定旧 FS54 `.265` 包计算的完整 VBMeta 摘要一致：

```text
6fc0e861da50bbc338dbe5a00afb5a1147ee8d2092db397c80a58348c28a3c3a
```

Android 没有提供可用的 Bootloader 版本属性；update-engine 查询也未能取得状态，**不能因此认定快照空闲**。这些仍须在 Flash 模式核对。

### 镜像和启动校验

三份固定原始包（旧 FS54 `.265`、新 FS54 `.35`、新 FS72 HK `.35`）均已重建启动镜像和 super 逻辑分区。

使用 AOSP avbtool，指定**旧 `.265` 的公钥**，核对主 VBMeta、boot/recovery/vbmeta_system 链及其 hash/hashtree 描述符，三套验证全部通过：

| 项目 | 旧 FS54 `.265` | 新 FS54 `.35` |
|---|---|---|
| 主/链公钥 | RSA4096，作为比较基准 | 与旧公钥字节一致，签名验证通过 |
| AVB flags | 0 | 0，没有关闭验证 |
| 主及三个链的 rollback index | `1788220800` | `1790812800`，均向前增加 |
| boot/recovery/vbmeta_system 的链位置 | 3 / 1 / 2 | 相同 |
| super 声明容量 | 19,327,352,832 字节 | 相同 |
| 有内容的逻辑分区总量 | 7,839,678,464 字节 | 7,964,303,360 字节 |

新 FS54 `.35` 的完整 VBMeta 摘要：

```text
e64fb66ce59e7d0441f0003603c5fb3fda309d4fe8482dab356969c26723d9bd
```

super 的几何结构一致，6 份元数据副本各自校验通过。新布局仍只填充 A 侧逻辑分区，B 侧为空，**B 槽不能当完整回退备份**。新布局使用的空间在原容量内；这与[GPT 逐字节未变](upgrade-boot-findings.md)相互印证，不需要据此增加 GPT 写入。

本次验证证明镜像及签名链内部一致、与旧公钥匹配，**不等于手机上的 Bootloader 更新和数据迁移已经成功**。它也不是对 Sony SIN 外层 CMS 或 Bootloader 复合载荷的完整离线认证。

### 官方来源与切卡组件

- `.35` 的 CR 更新服务与擦除服务，分别指向同一地区的同一 APP_SW 内容来源，详见[官方路径核查](upgrade-official-path.md)。包是否保留数据仍取决于实际执行流程。
- 新旧 GPT 布局相同，新版商业 Bootloader 为 V40，属于含多个底层组件的复合包。boot-config 参考文件不变，但手机当前配置尚未读取，详见[Bootloader 核查](upgrade-boot-findings.md)。
- Google LPA 文件完全相同，Qti 实现有变化，但同一切卡广播及 0/1 分支仍存在，详见[切卡入口核查](upgrade-esim-findings.md)。未在 `.35` 实机运行切卡脚本。

## 已整理的升级材料

本机目录：

```text
flash-kit/candidate-upgrade-fs54-71.2.A.2.35-NOT-APPROVED/
```

包含 14 个原始 `.35` 系统/无线固件 SIN 和 1 个原始商业 V40 Bootloader SIN，共 15 个只读文件，已逐个核对摘要与容器目标。没有复制 GPT、TA、userdata、metadata、persist 或 modemst 文件，也没有放入可直接运行的刷机程序。

**这是待审核材料，不是可直接刷的升级包。** 不要把裸 Newflasher 放入目录运行；目录内 `manifest.json` 明确为 `flash_allowed: false`。

重新准备材料的命令（只操作电脑，已有目录时拒绝覆盖）：

```bash
python3 flash-kit/prepare_upgrade.py
```

## 下一步：刷机模式只读检查

检查工具复用现有传输实现，但新增的升级检查模式只允许读取；即使错误切换到写入阶段，也拒绝 erase、flash、Write-TA、download、切槽和重启命令。

它会核对正常 Android 的型号/版本/锁定状态、旧 `.265` VBMeta 摘要及本次电量，然后提示用户手动进入 Flash 模式，读取：

- Bootloader、商业根哈希、A/B、快照状态等原有检查项；
- `has-slot:bootloader`，记录 `yes` 或 `no`，不把任一结果当成写入授权；
- Boot-config 的两个指定单元 `2:2127`、`2:2301`，只与固定参考比较，不写入、不输出原始内容。

从源码准备并模拟（不访问手机）：

```bash
python3 flash-kit/build_trial.py
python3 flash-kit/upgrade_preflight.py simulate
```

手机充电并通过 USB 连接后，在本机交互终端执行：

```bash
python3 flash-kit/upgrade_preflight.py run
```

先保持 Android 开机，按程序提示再关机进入 Flash 模式。本次电量只在 10 分钟内有效，没有历史电量或 force 开关。检查完成后可按提示断开 USB、正常开机。

**这个入口只有检查，没有 `.35` 写入功能。** 取得实际 Bootloader 路由与配置结果后，还需据此完成升级写入策略、失败处理和单独的实际写入确认。不能把模拟中的 `yes` 当成手机已经返回的结果。

## 方法与复核边界

- AVB 工具来自 AOSP 固定提交 [`761178607206f4cb2af79ed9eec52d8cbd814adb`](https://android.googlesource.com/platform/external/avb/+/761178607206f4cb2af79ed9eec52d8cbd814adb/avbtool.py)，工具文件 SHA-256 为 `e5a664a38db623da00f080219bc0ee60a640a9dc4a872803616fae4938ac749b`。其版本为 1.3.0，所核查镜像声明的最低 libavb 为 1.0。
- 使用 `verify_image --key <旧公钥PEM> --expected_chain_partition ... --follow_chain_partitions`，未允许零化 hashtree。用 `calculate_vbmeta_digest --hash_algorithm sha256` 与手机属性比较。
- SIN sparse/LZ4 解码和 LP 元数据检查在电脑完成。分析镜像中的 DONT_CARE 区按零洞处理，不推导真实设备擦除后的字节。原始包摘要先校验，解码产物再由独立 AOSP 工具验证。
- 本地分析脚本、镜像、逐项报告和日志保留在忽略目录 `firmware-analysis/upgrade-*`；原始设备检查记录保存在私有临时目录，不提交设备序列号或原始 TA 内容。
