# 我的手机从 `.265` 升级到 `.35`

**这是实验性升级，会更新 V40 Bootloader。可能丢失数据或无法开机，后果自负。** 本机的只读检查、固件校验和电脑端模拟已完成，但尚未实际执行这次升级。先备份重要数据和 eSIM 恢复资料。

## 适用手机

先前已经跨刷的港版 FS72 硬件，当前显示 **XQ-FS54 / `71.1.A.2.265`**，SKU `c001526`，未解锁、green、双卡模式，当前 A 槽，电量至少 **60%**。不是给原厂 FS72 `.265` 跨刷用的入口。

## 怎么操作

本机已完成编译。准备实际升级时：

1. 手机保持正常开机，使用 USB 数据线连接电脑，授权 USB 调试；不要一开始就进入 Flash 模式。
2. 从仓库根目录，在自己的交互终端运行：

   ```bash
   python3 flash-kit/upgrade_trial.py run
   ```

3. 程序重新校验文件和手机；按提示正常关机，按住音量减连接 USB。
4. 只读检查通过后，确定接受风险，完整输入：

   ```text
   FS54_265_TO_35_V40_A_KEEP_DATA_TRIAL
   ```

5. 确认后才开始写入。不要拔线、中断或同时运行其他刷机工具。等待程序完成并退出，再按提示正常开机。
6. 检查系统版本、重要数据、实体卡和 eSIM。

**这不是旧 `.265` 发行包的 `Start.command`。旧包不能升级到 `.35`。** 如果只想做电脑端检查，用 `check`；如果只想模拟，用 `simulate`，二者都不访问手机。

失败或结果不明时不要重复刷、切槽、重启或确认清数据，先保留日志分析。旧 `.265` 和 B 槽都不保证能回退。

## 实际写入范围

固定 14 个 FS54 `.35` 系统/无线固件镜像完成后，**最后**发送原厂 V40 复合 Bootloader 包到 `bootloader_a`，全部成功才设置启动槽 A。

- 不向 userdata、metadata、persist、modemst1/2、misc 发送擦写；不写 GPT 或 SPC/CustomerID。
- 两项 boot-config 必须与固定参考一致，但不写这两项；主机仍只写会话标志 TA `2:10100` 的 1/0。
- Bootloader 复合包由设备端处理，不能把主机命令白名单解释成所有其他分区字节均不变。
- 进入写入前重新核对 V36、商业根哈希、A 槽、快照空闲、Bootloader 分槽能力和 boot-config。正常 Android 的 VBMeta 摘要也必须匹配旧 `.265`。
- 本次 Android 电量/身份交接必须在 10 分钟内有效；升级入口不接受历史电量覆盖。不自动重试或重启。

原始 Bootloader SIN 是 GZIP 封装，传输器需要里面的 TAR。工具只解开这一层压缩，**CMS 与载荷不改动**，分别固定原始 GZIP 和解压后 TAR 的大小/摘要，不重新打包签名。

## 维护者：构建与验证

```bash
# 已有候选时验证；没有时先运行 prepare_upgrade.py
python3 flash-kit/prepare_upgrade.py --verify
python3 flash-kit/build_upgrade.py
python3 flash-kit/upgrade_trial.py check
python3 flash-kit/upgrade_trial.py simulate
```

独立构建输出为 `flash-kit/build-upgrade/`，不覆盖旧 `.265` 程序。源码或构建输入变化后重新编译。实际输入重新与固定 `.35` 原始 ZIP 核对，不信任可编辑清单替代原始包。

已在 macOS 使用真实 15 个文件完成正常模拟，以及 Bootloader 槽位错误、boot-config 不匹配、Bootloader 写入失败、提交阶段取消、快照合并中、DATA 握手错误和 super 槽位错误共 8 个场景。故障按预期停止，未自动切槽或重启；boot-config/GPT/受保护数据分区未出现写入命令。Linux 已编译并测试同一升级配置的原生保护逻辑，尚未做 Linux 真机升级。

证据与实机只读结果见[准备记录](upgrade-preparation.md)。成功模拟不是实机升级成功的保证。
