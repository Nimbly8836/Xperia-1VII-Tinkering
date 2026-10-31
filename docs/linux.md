# Linux 完整工具链

## 支持范围与验证边界

- 准备/校验、原生编译、自测、协议模拟、真实刷写入口及 SIM/eSIM 切换均已适配 Linux。Linux 与 macOS 使用同一个受限 **libusb** 后端，不使用上游 Linux usbfs 刷写入口。
- 首先支持 64 位 Linux；已在本地 **Debian 12 / arm64、Python 3.11、GCC 12、OpenSSL 3** 容器验证。其他发行版/架构不等于已经测试。
- 完整固定 `.265` 原始包已在非 root、禁网、无 USB 挂载、无额外 capabilities 的容器中完成 `prepare → build → simulate`，14 个镜像全部模拟完成。
- **没有执行 Linux 真机刷写。** 容器和 mock 测试不证明实际 USB 时序、设备驱动、开机或数据保留。
- 主机支持与固件支持是两回事。现有真实刷写策略仍限定 `.265` / V36；不能把支持 Linux 理解成已经批准 `.35` / V40 跨代升级。参见[新版研究](firmware-71.2.A.2.35-research.md)。

## Debian / Ubuntu 安装依赖

```bash
sudo apt-get update
sudo apt-get install python3 python3-defusedxml build-essential pkg-config \
  libusb-1.0-0-dev libssl-dev zlib1g-dev libexpat1-dev \
  adb android-sdk-platform-tools-common
```

其他发行版安装等价的 Python 3.10+、C 编译器、pkg-config、libusb、OpenSSL libcrypto、zlib、expat 开发包，以及 ADB。

`python3-defusedxml` 用于新版离线审查和对应测试，与下载器已有的 XML 安全依赖相同；并非新的 USB/刷机权限组件。

Linux 使用 OpenSSL EVP 计算 SHA-256；macOS 继续使用系统 CommonCrypto。`CC` 可指定本机编译器，例如 `CC=clang`，但不要把交叉编译产物当作当前主机验证过的可执行文件。构建收据记录 OS/架构，换主机后必须重新构建。

## 文件系统与空间

Linux 不要求 APFS，也不依赖 reflink。每次 `run` 或 `simulate` 都在私有临时会话中创建**全量独立镜像副本**：

- 源文件以 no-follow 描述符打开，拒绝符号链接和非普通文件。
- 目标独占创建，不覆盖，不用硬链接。
- 复制前预算全部镜像体积加 3 GiB 余量；复制时继续检查余量。
- 校验源文件及路径前后稳定、目标独立 inode、大小与 SHA-256，最后设为只读。
- 原生程序再次校验摘要与纳秒级 mtime/ctime，保留原安全检查。

`.265` 的一次会话另占约 5 GiB。`/tmp` 可能是容量很小的 tmpfs，请把临时目录放在空间充足的本地磁盘上。比如从仓库根目录执行：

```bash
mkdir -p .sessions
chmod 700 .sessions
export TMPDIR="$PWD/.sessions"
```

`.sessions/` 被根白名单忽略，里面可能含设备序列号和授权记录，不要上传。使用较短的仓库/临时目录路径；受限原生程序目前要求镜像工作路径不超过 150 字符。不要为了释放空间删除需要分析的失败会话，也不要运行中清理临时文件。

## 不接手机的验证

先运行不依赖固件的单测。安装原生依赖后可启用原生测试：

```bash
python3 -m unittest discover -s flash-kit -p 'test_*.py' -v
python3 -m unittest discover -s scripts -p 'test_*.py' -v
XPERIA_NATIVE_TESTS=1 python3 -m unittest discover -s flash-kit -p 'test_*.py' -v
```

`test_native.py` 在临时目录使用假镜像表，**不生成生产构建收据**。它把 USB 初始化替换为会立即失败的桩、bulk 传输替换为 mock，检查：

- 模拟模式不初始化或访问 USB；
- OUT 的 PIPE、超时、短写和 I/O 错误均只尝试一次，且不 clear-halt/补发；
- 共享协议检查与安全白名单自测；
- SHA-256、长度和纳秒时间戳检查。

之后按[根 README](../README.md) 放好固定 `.265` 原始 ZIP，再执行：

```bash
python3 flash-kit/flashkit.py audit
python3 flash-kit/flashkit.py prepare  # 已有候选时改用 verify
python3 flash-kit/build_trial.py
python3 flash-kit/trial.py simulate
```

这些命令不访问 USB。不要将测试用假镜像表复制到生产 `build/`，不要手工编辑构建收据。

两端（macOS 与 Debian 12 arm64）均已运行 **101 项测试，无跳过**，包含 XML 审查、原生测试及 Widget 脚本的静态/语法检查；测试不会实际执行 Widget 切卡请求。`.35` 的离线审查命令见[新版指南](firmware-71.2.A.2.35-research.md#4-可重复的离线审查入口)，它不会因审查通过而启用刷写。

## 实际 USB 使用前的权限配置

以下只用于将来明确决定操作手机时。本次移植验证没有执行这些设备操作。

ADB 由发行版平台工具规则管理，手机上须手动授权。Sony **Flash 模式**则是另一个 USB 设备 `0fce:b00b`。桌面 systemd/logind 环境可安装本仓库的限定规则：

```bash
sudo install -m 0644 scripts/70-xperia-flash.rules /etc/udev/rules.d/70-xperia-flash.rules
sudo udevadm control --reload-rules
```

在**没有刷写任务运行**时重新连接设备使规则生效。不使用 `MODE="0666"`，不对整类 USB 设备开放权限，不为整个刷写器加 sudo。

`TAG+="uaccess"` 针对当前本地桌面 seat；SSH/headless 用户可能不会取得 ACL。此时请由管理员为**仅该 VID/PID**设置专用组、`MODE="0660"`，把指定用户加入该组并重新登录。不要通过 root 执行或全局 USB 放权掩盖权限问题。

执行器不会自动脱离内核驱动。若接口无法 claim，应停止并分析占用/权限；不要在状态不明时反复启动其他刷机程序。

## 实际命令与限制

环境、备份、设备版本及固件均满足[详细流程](../flash-kit/TRIAL.md)之后，真实写入入口与 macOS 相同：

```bash
python3 flash-kit/trial.py run --serial YOUR_ADB_SERIAL
```

其数据保护、确认、错误停止与不自动重启规则不变。SIM/eSIM 切换脚本原本就是 Python + ADB，可在 Linux 使用同样命令，仍限定已研究的固件/设备，默认只预览。

**不要在 Docker/WSL/虚拟机里直接照搬做真机刷写。** 当前容器只用于隔离离线测试；USB 转发、设备断连重枚举、权限与驱动行为没有验证。应在原生 Linux 上另行评估设备访问。
