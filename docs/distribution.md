# 预构建刷机包：使用与打包

**刷机包下载链接待补充。** GitHub 的源码 ZIP 不是预构建刷机包。下面两个包已在本机生成、重新解压并完成离线校验与模拟；没有为本次发布执行真实刷机。

## 当前生成的 v1 包

| 文件 | 电脑要求 | 字节数 |
|---|---|---:|
| `Xperia-1VII-FS72-to-FS54-71.1.A.2.265-macos-arm64-v1.zip` | Apple Silicon，macOS 27.0.1+，APFS | 4,569,744,348 |
| `Xperia-1VII-FS72-to-FS54-71.1.A.2.265-linux-arm64-v1.zip` | ARM64，glibc 2.36+，OpenSSL 3；验证环境为 Debian 12 | 4,569,747,573 |

每份约 4.26 GiB，用户只下载符合自己电脑的一份。不适用于 Intel/AMD x86_64 电脑。

macOS 包 SHA-256：

```text
2c64038b7e36e7e11a7bbc515daa9d976743c9f454a9780db1efa86e3c03d5d3
```

Linux 包 SHA-256：

```text
226d9f891b21362da31f4888156d5bb83bf89a9d11e0b4dd525934dead19b146
```

原始文件留在打包者本机 `dist/` 和 `dist/linux/`，未提交固件到 Git，也未上传网盘。校验时将 ZIP 解压到独立目录，两端均通过 `check`、14 镜像 `simulate` 和错误注入停止测试；使用者路径没有读取原始 ZIP 或源码，也没有调用编译器或 ADB。Linux 测试容器未挂载 USB。

## 使用者需要什么

下载与电脑**系统及 CPU 架构一致**的包，核对摘要后解压：

- macOS：双击 `Start.command`；需要 APFS，以便创建独立镜像副本。
- Linux：在解压目录运行 `bash start.sh`；USB 权限、临时目录空间及依赖见 [Linux 指南](linux.md)。
- 仅电脑端校验：`bash start.sh check`。
- 无 USB 模拟：`bash start.sh simulate`。模拟通过不证明真实设备兼容。

不需要原始固件 ZIP、源码或编译工具。**仍需 Python 3.10+、ADB、libusb 运行库**及目标系统要求的运行依赖；包不内置 Python、ADB 或第三方运行库，不承诺零依赖。不要把另一个系统或架构的预编译程序复制过来使用。

macOS 已安装 Homebrew 时：

```bash
brew install python libusb
brew install --cask android-platform-tools
```

启动器自动选择唯一 ADB 设备，不放宽手机基线：港版 FS72、SKU `c001526`、原厂 `71.1.A.2.265 release-keys`、locked/green、DSDS、电量至少 60%；目标固定 FS54 EU/UK `.265`，不是 `.35` 升级。人工确认和详细写入/失败处理见 [TRIAL.md](../flash-kit/TRIAL.md)。

## 核对下载文件与信任来源

发布者应在**包外**提供 ZIP 的 SHA-256，例如可信发布说明中的摘要及单独的 `.sha256` 文件。使用者先核实发布者和获取渠道，再计算下载 ZIP 的摘要进行逐字比较：

```bash
# macOS：把路径换成实际下载的 ZIP
shasum -a 256 /path/to/bundle.zip
# Linux
sha256sum /path/to/bundle.zip
```

有任何不一致就停止，不编辑清单或摘要来通过检查。

- **源码入口**：固定原始 ZIP、源码、生成源码和本机构建二进制的校验将本地材料关联起来；不等于 Sony 签名验证或兼容性证明。
- **发行包入口**：使用者没有原始 ZIP 或完整构建输入，依赖发布者提供的预编译程序及包内清单。`check` 能发现与清单不符的文件，但清单和程序若一起被替换，包内自校验不能证明来源可信。
- **外部 SHA-256**：在可信渠道取得预期摘要后，可以检查下载内容是否一致。若包和摘要同时来自被篡改的渠道，摘要本身不能认证发布者；它也不是数字签名，更不能保证刷机成功。

## 打包者步骤

只在拥有相应分发权限的前提下分发固件及相关内容。打包应在目标系统与架构上完成，不把一次构建当作所有平台均可用。

1. 按[根 README 源码构建部分](../README.md#源码构建使用预构建包可跳过)安装构建依赖并取得固定原始 ZIP。Linux 发行构建需要 OpenSSL 3，macOS 需要标准 Homebrew libusb。
2. 在仓库根目录执行：

   ```bash
   python3 flash-kit/build_bundle.py --release v1
   ```

   脚本会准备/核对候选、编译、自测、组包，并校验 ZIP 内每个文件。输出位于 `dist/`：发行目录、ZIP 和 `.sha256` 文件。可用 `--output-dir` 指定输出目录；同名发行文件已存在时拒绝覆盖，下一版请使用 `--release v2` 等新版本名。
3. 进入生成的发行目录，运行 `bash start.sh check` 和 `bash start.sh simulate`。再从 ZIP 解压一份到独立目录，重复校验和模拟，确认包不依赖原始 ZIP、源码目录或本机构建缓存。它们不访问 USB；不要为打包默认执行真实刷机。
4. 核对包的平台/架构标签、许可、清单及文件列表；仅记录实际完成的构建、测试和模拟结果。没有真机测试的平台不得宣称已实机验证。
5. 单独计算最终 ZIP 的 SHA-256，与生成的 `.sha256` 比较；发布时同时提供 ZIP、`.sha256` 和可信页面上的外部摘要。**当前下载链接仍待补充，不在此虚构网盘地址。**

## 包内容与隐私

发行包内容限定为：**14 个固定原始 SIN、预编译 native 程序、Python 运行脚本及启动入口、许可和清单**。不含原始固件 ZIP、完整源码或第三方运行库。

发布文件不包含个人数据。打包采用明确文件范围，发布前仍必须检查最终目录与 ZIP，不得把工作目录整体压缩：

- 不加入真实会话、baseline、授权记录、probe/native 日志、测试输出或原始电话 dump。
- 不加入设备序列号、IMEI、EID、ICCID、手机号、eSIM 激活码、配对码、ADB 私钥或个人文件。
- 不加入下载 metadata、账号凭据、私人链接或带临时参数的下载 URL。

保留本项目和 Newflasher 的许可及版权声明，见 [LICENSE](../LICENSE) 和 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。固件和外部依赖不因本项目采用 MIT 而变为 MIT。
