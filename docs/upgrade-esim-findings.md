# FS54 .265 → .35：SIM_TYPE_UPDATE_ACTION 离线核查

## 结论

**同一广播入口和 0/1 分支仍存在，但 Qti 实现不是原样复制。** Google LPA APK 完全相同；QtiTelephony APK、extphonelib JAR 及其 DEX 均改变。静态可见的目标包仍为 `com.qti.phone`，action 为 `com.android.euicc.service.SIM_TYPE_UPDATE_ACTION`，整数 extra 为 `com.android.euicc.service.extra_sim_type`。两版处理函数仍对 0/1 分别写入 `QtiSimType(0)` / `QtiSimType(1)`。

本次只读比较固定 FS54 `71.1.A.2.265` 与 `71.2.A.2.35` 的 system_ext/product ext4 文件；未联网、未访问 ADB/USB/手机、未操作共享 REA target。AVB 完整链验证由主任务完成，本报告不重复声称自行验证。

## 文件身份（SHA-256，公开固件组件）

| 文件（镜像内路径） | .265 | .35 |
|---|---|---|
| system_ext `/priv-app/QtiTelephony/QtiTelephony.apk` | `ca2863ea07fc02c39e2a172b2a9900b626987f7d3905bc3c79902e71ecf660b6` | `bb7170f07f39ac9791f6cf52a8d186b83fafbf5a257f763fa87972e1c1de1107` |
| system_ext `/framework/extphonelib.jar` | `17f55a48f408621b8008991a50a67c9bf1db8bb0446cf909af083bee35ffcd25` | `18d740972c4f95ff3dcd9d8ae3328bcb13d2b018cfd3df8f4ffa586d85495f67` |
| product `/priv-app/EuiccGoogle/EuiccGoogle.apk` | `702b7aab184177c08f98f462773f8bc13db21d91bb15200f5941a819c78d96b5` | 同左（16,115,428 字节） |

DEX SHA-256：

| 成员 | .265 | .35 |
|---|---|---|
| QtiTelephony classes.dex | `2ea93ed94696443bb9789510c44784be29a9a9eacec4a060d3c1efd605d08037` | `be81217b963781b1ce33fdd5030fdcac1088d9a1ab329f2cd6f5487d061100bd` |
| extphonelib classes.dex | `c95313b0eaaa3c8b8f68c91d0eb1a5c3e9db57f97b24ed86180ca381b5fd550e` | `c77e96d0704d9ce0d35cd69beb28b70cce1bd8713e52bb7410198fcf24cee26d` |
| LPA classes.dex | `349067c1913b00e660903720c0d9ca100b56afa1338eb4e09de6a667c0b6ed4c` | 同左 |
| LPA classes2.dex | `7aa8561806a7a9383028d3e336419f73f9c89f357394eea9bf48cc1284f1c70b` | 同左 |

.265 三个组件 SHA 与既有 `runtime-switch/selected-files.json`、`payload/lpa-apk-hashes.json` 一致。

## 聚焦静态证据

证据根目录为 `firmware-analysis/upgrade-esim/`，含 `265/`、`35/`；`*.focused.txt` 保留原始 dexdump 地址，`*.normalized.txt` 去掉绝对代码地址及池索引，便于比较，不代表 DEX 字节相同。

- **入口与槽位：** .265 `QtiUiccSwitcher$1.onReceive`，.35 改为 `$2.onReceive`。两者读取上述 action、`extra_sim_type` 和 `com.android.euicc.service.extra_slot_id`（默认 -1），类型非 -1 时投递消息 4。`.35/QtiTelephony.apk.focused.txt:11808` 起可复核。
- **0/1 与槽位选择未见语义改变：** 两版 `processSetSimTypeRequest(II)` 都先调用 `geteSimTypeSupportedSlotId()`，按支持类型数组从头寻找第一个值为 3 或 6 的槽；未找到则返回。0/1 分支只修改这个自动选出的槽，输入 slotId 用于日志，而非数组索引。不能把 extra_slot_id 当成任意槽强制选择器。见两版 `switch-path.txt` 以及 `.35/QtiTelephony.apk.focused.txt:13564`。本次已保留 QtiSimType 类转储，但未完成全部枚举常量逐项复核；0/1 写入和 3/6 选择条件由实际处理指令直接确认。
- **接收权限：** 两版构造函数均把 action 加入动态 IntentFilter，用 `registerReceiver(receiver, filter, 2)` 注册（RECEIVER_EXPORTED），该重载没有 sender-permission 参数；所查接收/处理方法中未见新增调用者权限检查。不能据此保证新版系统整体广播政策或执行结果。
- **内部实现确有变化：** .35 构造函数改用注入 Looper、`IQtiRadioConfigConnectionInterface` 和 `QtiRadioProvider`；旧版自行创建 HandlerThread、使用 `QtiRadioConfigProxy`。处理函数从 `QtiRadioConfigProxy.setSimType(types)` 改成接口 `setSimType(null, types)`。新代码还增加 `com.android.action.disable_esim` 接收器和相关状态。不能将“入口保留”写成“整个切换链完全相同”。
- **包/权限配置并非完全不变：** manifest 包名仍为 `com.qti.phone`；versionCode 36→37、targetSdk 35→36。`READ_PRIVILEGED_PHONE_STATE`、`MODIFY_PHONE_STATE`、`WRITE_EMBEDDED_SUBSCRIPTIONS` 均保留，但 manifest 和 `telephony_system-ext_privapp-permissions-qti.xml` 新增其他权限，例如 READ_PRECISE_PHONE_STATE、WRITE_APN_SETTINGS、REBOOT 等。两版 manifest 文本和权限 XML 均保留，可直接 diff；本次未扫描系统全局权限配置。
- **LPA：** APK、全部 DEX 和 manifest 完全相同，因此没有重复反汇编。既有 `firmware-analysis/lpa-switch/switch-methods.txt:663–671` 的发送分支构造相同 action，写入 extra_sim_type，调用 `sendBroadcast(intent, "android.permission.READ_PRIVILEGED_PHONE_STATE")`。这里的权限限制接收方，不是 Qti receiver 对发送者的权限要求。这个发送分支没有 `setPackage`，不要误称 LPA 自身发送定向包广播；`com.qti.phone` 是本次确认保留的接收包。LPA 另有 activateSimType 路径，不能由 APK 相同推定运行时必走广播分支。

## 复核方法与边界

使用本地已有 `xperia-image-tools:bookworm`，Docker 参数 `--pull=never --network=none`；仅将 `firmware-analysis/upgrade-images` 以 readonly bind 提供给容器，将新建输出目录提供写入。`/sbin/debugfs -R 'dump /指定文件 /out/版本/文件' 镜像` 默认只读，未加 `-w`，未挂载分区或设备。只导出了上述三个组件及 Qti 权限 XML；product 仅列出 EuiccGoogle 目录并导出其 APK，未全量解包。

Python zipfile/hashlib 比较文件和 ZIP 内 DEX；变更 DEX 使用已安装 Android build-tools 37.0.0 `dexdump -d` 流式过滤保留相关类，manifest 使用同版本 aapt2。保留产物约 50 MB 二进制、少于 6 MB 文本（未做最终精确统计），低于 100 MB/20 MB 限额。

**这是静态兼容性证据，不是 .35 实机成功记录。** 未验证新系统启动后的 receiver 初始化、权限实授、HAL/基带返回、eUICC profile 状态、运营商注册或数据业务。不能保证 .35 实际联网，亦不能由旧版成功记录代替新版实测。
