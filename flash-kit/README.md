# FS72 HK `.265` → FS54 EU/UK `.265` 受限刷写工具

**单机结果已更新：用户确认刷机成功、数据保留、内置 eSIM 激活联网，并已验证“实体卡 + eSIM ↔ 双实体 SIM”往返和 Termux 脚本快速切换。** 这不代表任意设备兼容，也不代表 OTA 或失败恢复已经验证；Termux 脚本与配置说明见 [Widget 指南](../docs/termux-widget.md)。

先阅读根目录 [README](../README.md) 的适用范围、依赖、固件来源、操作和风险；详细写入边界见 [TRIAL.md](TRIAL.md)。

支持 macOS/APFS 和 Linux。Linux 的依赖、临时副本空间、udev 权限与验证范围见 [Linux 指南](../docs/linux.md)。Linux 实机尚未验证；`.35` 使用独立的[实验性升级入口](../docs/upgrade-run.md)，不能直接替换此处的固件输入。

## 发行包与源码两条入口

- **使用预构建发行包**：下载链接待补充。解压对应主机系统和架构的包，macOS 双击 `Start.command`，Linux 在解压目录执行 `bash start.sh`；启动器只选择唯一 ADB 设备，仍核对原有基线并要求人工确认。不需要原始 ZIP、源码或编译，但需要 Python 3.10+、ADB 和 libusb 运行库。`bash start.sh check` 仅电脑端校验，`bash start.sh simulate` 为无 USB 模拟。安装与操作见[根 README](../README.md)，摘要核对及打包见[发行说明](../docs/distribution.md)。GitHub 源码 ZIP 不是发行包。
- **自行从源码构建**：按下面步骤准备固定原始 ZIP、生成候选并编译，再使用 `trial.py run --serial …`。

## 源码入口区别

| 文件 | 作用 |
|---|---|
| `flashkit.py` | `.265` 离线 audit/prepare/verify；可选只读 ADB preflight。其 execute 始终拒绝 |
| `audit_upgrade.py` | `.265` → `.35` 原始包与 boot delivery 离线审查；其 execute 始终拒绝，不读取手机 |
| `prepare_upgrade.py` / `build_upgrade.py` | 固定 `.35` 材料核对、解开 Bootloader 的 GZIP 外层并独立编译，不访问手机 |
| `upgrade_preflight.py run` | 升级准备的只读设备检查，不会续刷 |
| `upgrade_trial.py run` | **独立的真实 `.35` 升级入口**，最后更新 V40 Bootloader A，需新基线和独立确认；尚未实机升级 |
| `build_trial.py` | 校验固定 Newflasher 源码、转换并编译受限原生程序；不访问 USB |
| `trial_policy.c.in` / `trial_main.c.in` | 命令白名单、模拟实现及受限执行流程 |
| `trial.py simulate` | 读取真实固定固件做协议模拟；不访问 USB |
| `trial.py probe` | Flash 模式只读检查；不写分区或 TA |
| `trial.py run` | **真实写入**：Android 基线 → Flash 只读检查 → 人工确认 → 14 镜像 |
| `continue_trial.py` | 特殊只读失败会话的单次续接；不是部分刷写恢复工具 |
| `upstream/newflasher-59f12e4.c.txt` | 固定上游 MIT 源码，保留原始版权和完整 SHA |
| `test_*.py` | 不访问手机的合成数据/mock 单元测试 |

以下为源码入口，所有示例从仓库根目录执行。仅当固定原始 ZIP 已放到根 README 指定路径后：

```bash
python3 flash-kit/flashkit.py audit
python3 flash-kit/flashkit.py prepare  # 仅首次；已有候选时用 verify
python3 flash-kit/flashkit.py verify
python3 flash-kit/build_trial.py
python3 -m unittest discover -s flash-kit -p 'test_*.py' -v
python3 flash-kit/trial.py simulate
```

实际刷机必须单独阅读说明并手动启动：

```bash
python3 flash-kit/trial.py run --serial YOUR_ADB_SERIAL
```

源码仓库不附带候选目录、构建收据、原生可执行文件、测试输出或真实会话；源码使用者需本地生成。预构建发行包另含固定镜像、预编译程序及运行所需脚本/清单，不要求使用者重新编译。源码入口摘要不匹配时重新构建并测试，发行包校验失败时停止并核对来源；均不得修改摘要绕过。

历史准备器仍保留 `.248` 只读基线、未批准的候选标记和 BLOCKED 文案，以免把离线候选误当刷机授权；实际 `trial.py run` 使用 `.265` 基线并独立确认。它们不是当前实机结果报告。构建收据中的 `real_device_flashing_tested: false` 表示构建过程没有实机测试，功能结果另见[实机摘要](../docs/verified-results.md)。

**不要把裸 Newflasher 放入候选目录运行。不要在已刷好且正常工作的手机上重新试刷。**
