# 受限刷写流程与失败处理

本机已有刷机成功、用户数据保留和内置 eSIM 联网的反馈，详见[验证范围](../docs/verified-results.md)。本工具依旧是实验性代码，单台成功不替代备份、设备兼容性检查与本次刷后验收。

完整环境安装、固定 ZIP 文件名/SHA、准备/构建步骤在[根 README](../README.md)，Linux 另见 [Linux 指南](../docs/linux.md)。本文仍仅描述 `.265` / V36 同版本跨刷，不是 `.265` → `.35` 升级方案；命令从仓库根目录执行。

## 标准流程

手机必须以正常 Android 启动，解锁并授权 USB 调试。刷前要求港版 FS72 `71.1.A.2.265 release-keys`、SKU `c001526`、Bootloader locked、Verified Boot green、DSDS、电量至少 60%。

```bash
python3 flash-kit/trial.py run --serial YOUR_ADB_SERIAL
```

1. 检查固定源包、候选、源码、生成源码和二进制摘要。
2. 在私有临时会话目录中创建独立只读输入副本：macOS 使用 APFS clone，Linux 使用全量复制并校验摘要/空间/源文件稳定性。均不共享硬链接，不修改源固件。
3. 只读核对当前 Android 身份和电量，记录真实读取时间。
4. 按提示正常关机，按住音量减插入 USB，进入 Sony Flash 模式，不是 Fastboot；原生程序按 `0fce:b00b` 和明确序列号检查唯一目标。
5. 先只读检查商业根哈希、V36 Bootloader、A/B 布局、传输能力、电量和 OTA 快照。
6. **只有 `snapshot-update-status=none` 才允许写共享 super**；未知/无法读取/合并中均停止。
7. 检查通过后，要求完整输入 `FS72_TO_FS54_265_A_KEEP_DATA_TRIAL`。未经确认不开始分区写入。
8. 写入完成、同步、结束会话标志后设置 A 槽，再同步；不自动重启。
9. 输出 `TRIAL_COMPLETE_NO_REBOOT_FUNCTIONAL_RESULT_NOT_VERIFIED` 只说明写入序列完成。程序退出后按提示正常开机，检查原锁屏、数据、SIM 和 eSIM。

### 电量读取兼容

Flash 模式可能精确返回 `FAILBattery not supported`。标准流程仅在这一种响应下，允许使用**同一设备、本次 run 在 Android 中取得、不超过 10 分钟、60–100%**的电量。主控和原生程序均检查时间，首次写入前再次检查。其他 FAIL、超时、空响应、异常值、过期或设备不匹配不允许回退。

因此从 Android 电量读取到进入 Flash 模式、确认写入须及时完成。独立 `trial.py probe` 不加载旧 Android 基线，可能因电量查询不支持而停止。这不是建议删除电量检查。

## 实际写入边界

14 个固定 SHA 的原始 FS54 EU/UK `.265` SIN：

```text
bluetooth → dsp → featenabler → modem → pvmfw → spuservice
→ super → dtbo → vendor_boot → init_boot → boot → recovery
→ vbmeta_system → vbmeta
```

- 除共享 `super` 外，目标必须报告支持 A/B，只允许 `*_a`。所有 `*_b` 和未知目标被拒绝。
- `super` 会更新逻辑分区和 LP 元数据，B 槽不是完整回滚快照。
- 不对 `userdata`、`metadata`、`persist`、`modemst1/2`、`misc` 发出 erase/flash，不写 GPT、Bootloader delivery 或身份/密钥 TA。
- 唯一允许的 TA 写是会话标志 `2:10100` 的 1/0。成功后的 `set_active:a` 更新启动控制记录；首次启动也可能有系统/NV 数据迁移。
- 不修改 SPC/Product Code、CustomerID，不 Root、不解锁、不恢复出厂、不自动重启。
- 输入包的固定哈希/容器检查不是主机端 Sony 签名验证，也不是跨型号兼容性证明。

## 失败和特殊续接

### 只读检查未通过

标准 run 会记录未请求手机写入。确认日志只到只读阶段后，可按程序提示断开 USB、正常开机，重新评估原因。不要改门禁、伪造基线或替换镜像强刷。

### 已经开始写入或结果未知

可能已经部分刷写、保留会话标志或更新启动记录。不要盲目重试、切槽、重启、补刷或确认恢复出厂；保存私有日志，先分析实际已完成步骤。中断只能请求在边界停止，不能撤销正在进行或已经发出的写入。

### `continue_trial.py` 的特殊用途

保留该脚本供审查历史流程，它**仅**接受原 `fs72-trial-live-*` 会话中已明确记录的“只读 probe 停止、未请求写入”结果，核查原基线、目录归属、证据文件和日志。不能恢复部分写入；会话已有授权、native 写入日志或续接标记都会被拒绝。它会重新 probe，并再次要求人工输入完整刷写确认短语。

默认仍要求电量不超过 10 分钟。脚本另有 **`--accept-recorded-battery`** 选项：显式接受过期历史读数，而不是证明当前电量；这是风险更高的人工例外，**标准流程不使用，也不推荐拿它解决普通超时**。本项目不隐瞒这个选项，也不把它称为“仍有实时电量保证”。仅用 `--help` 查看接口不会访问手机。

不要为了复用一次授权而复制/编辑会话 JSON 或删除锁标记。

## 模拟与测试

无需固件、无需手机：

```bash
python3 -m unittest discover -s flash-kit -p 'test_*.py' -v
```

已有固定固件、完成本机构建后，无 USB 协议模拟：

```bash
python3 flash-kit/trial.py simulate
python3 flash-kit/trial.py simulate --fault data-fail-prefix
python3 flash-kit/trial.py simulate --fault super-slot-failure
python3 flash-kit/trial.py simulate --fault snapshot-merging
```

错误注入应返回失败并停止，不要将预期非零退出误当需要“修复门禁”。模拟不证明真实启动兼容性或失败可恢复。

## 日志与隐私

私有会话位于操作系统临时目录的 `fs72-trial-live-*`，包含镜像快照、baseline、授权记录、probe/native 日志和结果。它们可能包含设备序列号；后续电话 dump 可能包含 EID/ICCID。不要直接上传，公开时只提供人工审核脱敏后的最小必要片段。
