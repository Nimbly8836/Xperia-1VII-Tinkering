# FS54 `.265` → `71.2.A.2.35`：离线适配状态

核查日期：2026-10-31。用户指定的路径是**已跨刷的 FS72 硬件、当前 FS54 `.265` → FS54 `.35`**，不是原厂 FS72 `.35` 的同版本跨刷。本轮获准下载两套新版固件到电脑，**没有获准或执行手机刷写，也没有连接 ADB/USB**。

## 当前结论

- **已完成**：官方版本查询、两套完整原始 ZIP 下载及独立校验、新旧包/boot delivery 内容比较、固定摘要的离线审查脚本。
- **尚未完成**：`.265` → `.35` 的实际刷写策略与验证。`audit_upgrade.py execute` 明确拒绝；原 `trial.py` 仍锁定 `.265` / V36，SIM 切换脚本也未盲目放行 `.35`。
- **关键差异**：Sony 官方元数据将 `.265` 标为 Android **16**、`.35` 标为 Android **17**；包内 boot delivery 从 **V36 变为 V40**。不能只改版本号、哈希或把 Bootloader 检查放宽成“至少 V36”。
- Linux 工具链移植已完成离线验证，但**主机兼容不等于新版固件兼容**。详见 [Linux 指南](linux.md)。

## 1. 已固定的原始输入

目录均位于 `firmware-downloads/packages/`，文件不提交 Git。

| 目录 | 原始 ZIP 字节数 | 来源 |
|---|---:|---|
| `fs54-eu-71.1.A.2.265` | 4,543,231,670 | 本项目既有固定 FS54 EU/UK 包 |
| `fs54-eu-71.2.A.2.35` | 4,665,814,296 | Sony FS54 Customized EU/UK 服务 |
| `fs72-hk-71.2.A.2.35` | 4,665,768,932 | Sony FS72 Customized HK 服务 |

新版两份原始 APP_SW ZIP 合计 9,331,583,228 字节，约 8.69 GiB。HK 对照包不是 SEA 样本；地区归属依据官方服务响应，不仅是文件名。

### FS54 EU/UK `.35`

```text
APP-SW_PDX256_GLOBALEEA-A4_USER_71.2.A.2.35_X-FLASH-ALL-B083_COM.zip
SHA-256: aeab7cab467dff1e3fc71b6becc87532d54789df79a6b7b3289cdf86ab707056
```

### FS72 HK `.35`

```text
APP-SW_PDX256_GLOBAL-C2_USER_71.2.A.2.35_X-FLASH-ALL-B083_COM.zip
SHA-256: 70f5513f7dd3c6fbb3a341962b430fc1831a7a46019e2e3fa7438242ee7fd992
```

旧 FS54 `.265` 的文件名和固定摘要见[根 README](../README.md)。**这些完整包 SHA-256 是本地计算并复核的，不冒充 Sony 公布的预期摘要，也不是签名验证。**

## 2. 获取与完整性证据

查询链为 Sony 产品目录 → 型号/地区匹配 → 精确版本软件服务 → APP_SW 分块清单 → HTTPS filestorage。两地区 `.35` 均报告 `RELEASED`、Android `17`；旧 `.265` 报告 Android `16`。匹配服务中的标签不构成 Sony 对跨型号保数据升级的承诺。

最初以有限 HTTP Range 获取 ZIP64 中央目录和 boot delivery；随后按用户明确授权完整下载两套 APP_SW：

- 每套 45 个分块；前 44 块各 104,857,600 字节，最后一块分别 52,079,896 / 52,034,532 字节。总和与官方 `plain-size` 一致。
- 下载器核对分块长度和本地 SHA；完成后核对整包长度、SHA-256 与全成员 ZIP CRC。
- 另用系统 `shasum -a 256` 和 `unzip -t` 复核，两包各 31 成员，检查通过。
- 主流程再次使用 `audit_upgrade.py` 对三份原始包做固定 SHA 校验，流式读取并计算每个成员摘要，同时校验 ZIP CRC；检查期间核对源描述符与路径稳定性。
- 全部资源链接、令牌、响应原件、下载辅助文件与运行结果只留本机忽略目录，不公开。本文不包含设备唯一标识。

Sony UK/HK 支持软件网页本轮返回 403，因此没有从网页独立核实发布日期、OTA 推送范围和官方升级前置条件。API 可访问不等于某部手机一定已获 OTA。

## 3. 完整包比较的实测结果

### Boot delivery

| 项目 | 旧 FS54 `.265` | 新 FS54 / FS72 `.35` |
|---|---|---|
| PRODUCT / SPACE_ID | `pdx256` / `8750-0001` | 相同 |
| VERSION | `8750-0001-X-BOOT-SM8750-LA1.0-V-36` | `8750-0001-X-BOOT-SM8750-LA1.0-V-40` |
| 商业版匹配配置 | `COMMERCIAL_0028C0E1` | 相同 |
| 商业根哈希匹配条件 | 与现有 `.265` 工具常量一致 | 相同 |
| boot config TA | `PDX256_XBootConfig_MiscTA.ta`，894 字节 | 内容 SHA-256 与旧包相同 |

旧商业 Bootloader SIN 的 SHA-256：

```text
8506996f844ae6e7715e2c468a906d588ecbcbcb963bc6ddadbc2e0472ff24ae
```

新商业 Bootloader SIN（两地区一致）的 SHA-256：

```text
260b0ce3c9d143d3627b7b3e363aa5ae5502522729dda7ecbe3a53e15ace0bd8
```

两份新 `boot_delivery.xml` 内容完全相同，SHA-256：

```text
55876b4708483f22b775ccd5fb32fb34bc515d5c68df0f87e4e5d9c7f0139b75
```

**完整下载修正了初步研究的未知项**：新版 FS54/HK 的外层 `boot.zip` SHA/CRC 不同，但解包后 **11 个成员的内容 SHA-256 全部相同**，包括三个 Bootloader SIN、配套 hash ZIP、TA 和 XML。因此可以确认这两份包的 boot 成员内容相同；不能据外层 ZIP 不同就说 Bootloader 内容不同。

相同商业根条件和相同 TA 是有用证据，但**不是把 V40 加入写入白名单的授权，也不证明直接升级、保留 V36 或降级一定安全**。

### 主包内容

- 三份 APP_SW 均有 31 个根成员，包含旧流程使用的同名 14 个候选 SIN，也包含 userdata/metadata/persist/modemst/misc、GPT 包、Bootloader 包及 TA。
- 旧 FS54 `.265` 与新 FS54 `.35`：4 个顶层 TA 文件内容一致，其余 27 个成员摘要不同。
- 新 FS72 HK 与新 FS54：6 个根成员一致，其余 25 个成员摘要不同。
- **SIN 容器摘要不同不等于已证明内部所有载荷不同**。本轮没有逐一展开全部 SIN/super、比较每个稀疏块/逻辑分区或证明 AVB 链可启动。不要由文件名相同推导兼容，也不要由容器不同推导具体组件差异。

官方 `.35` 软件服务的回滚元数据包含 `vbmeta=1790812800`、`nfc-fw=257`。这些是服务字段，不是从手机读取的 rollback index，也不能用来保证可降回 `.265`。

## 4. 可重复的离线审查入口

只操作电脑文件。脚本复用下载器已有的 `defusedxml==0.7.1` 依赖；无网络请求、不解包到可刷目录、不生成写入授权。

```bash
# 已有该虚拟环境时不用重复创建
python3 -m venv firmware-downloads/.venv
firmware-downloads/.venv/bin/python -m pip install defusedxml==0.7.1

python3 flash-kit/audit_upgrade.py status
firmware-downloads/.venv/bin/python flash-kit/audit_upgrade.py audit \
  > flash-kit/upgrade-audit.json
```

默认读取第 1 节的三个包目录；也可用 `audit --packages /path/to/packages` 指定它们的共同父目录。**不能通过命令行覆盖预期 SHA/版本**，重新打包或混用输入会拒绝。审查会读取约 13 GiB 压缩包并解压流式校验成员，需要时间，但不会额外落地全部镜像。

输出包含包与成员摘要、boot delivery 配置、逐项比较、`flash_allowed: false` 和阻止实际升级的原因。生成的 JSON 被 Git 忽略。

```bash
# 这是拒绝门禁测试，不会访问手机或读取固件；预期退出码 78
python3 flash-kit/audit_upgrade.py execute
```

`audit` 成功的退出码仅代表文件审查完成。**目前没有 `.35` 的 run/force/自动升级入口。** `status/execute` 不依赖 XML 库；只有实际解析包需要它。

包含 XML 审查和原生桩的全套离线测试：

```bash
XPERIA_NATIVE_TESTS=1 firmware-downloads/.venv/bin/python -m unittest discover -s flash-kit -p 'test_*.py' -v
firmware-downloads/.venv/bin/python -m unittest discover -s scripts -p 'test_*.py' -v
```

未安装 XML 依赖时，普通 Python 测试会明确跳过 XML 包解析测试；未设置 `XPERIA_NATIVE_TESTS=1` 时跳过需要 C 工具链的原生测试，不把跳过当成验证通过。

## 5. 尚需完成的升级工作

1. **当前手机基线**：目前仅依赖用户描述的“已跨刷 FS54 `.265`”。需另行授权只读核查实际型号、版本、启动槽、Bootloader、锁定/AVB 状态和快照；这轮未读取手机。
2. **Bootloader 策略**：验证 V36 是否支持新启动链；若必须更新 V40，需要单独设计/审查 signed boot delivery、配置匹配、槽位、隐式 TA 操作及中断恢复。不能把 V36→V40 文本替换或使用裸 Newflasher 当实现。
3. **系统/基带与数据**：完成 SIN 内容、AVB/rollback、super 动态分区、基带依赖及 Android 跨代加密/数据迁移核查，再确定实际必要镜像集合与顺序。
4. **恢复与测试**：HK 新包已经取得，但没有因此验证无损恢复；旧 B 槽不是完整快照，降级不能默认安全。须保留独立数据备份与 eSIM 恢复方式，设计失败停止/恢复流程。
5. **新 SIM 入口**：新版 Qti/LPA 行为未核查或实测，不能只给切换脚本加一个版本号就宣称兼容。

本轮不把缺失证据解释成“肯定不能升级”，也不把一个案例的旧版成功解释成“新版可安全升级”。**当前交付是 Linux 移植 + 新版可重复离线审查，不是已完成 `.35` 实刷适配。**

## 6. 来源（公开入口）

- [Sony ESS 产品目录](https://app.swup.update.sony.net/ess-distribution/public/api/product/v2)：实时取得 PDX-256 型号/硬件关系。
- [Sony ESS 匹配入口](https://app.swup.update.sony.net/ess-distribution/public/api/device-service/match/v2)：按对应型号/地区查询；版本、Android 和发行状态来自该响应。
- Sony 同域 `/ess-distribution/public/api/device-service/software-service/gen2/`、`/ess-distribution/public/api/file/`、`/filestorage/`：沿匹配结果提供的链接获取清单与资源。完整 URL 含临时参数，不公开。
- 固件字节证据：第 1 节精确 ZIP 名、大小、完整 SHA，以及第 3 节内层成员摘要；可由本仓库脚本离线复核。
- [Sony UK 软件支持页](https://www.sony.co.uk/electronics/support/mobile-phones-tablets-mobile-phones/xperia-1-vii-256gb/software)、[Sony HK 软件支持页](https://www.sony.com.hk/en/electronics/support/mobile-phones-tablets-mobile-phones/xperia-1-vii-256gb/software)：本轮 403，不作为发布正文证据。
- [固定 Newflasher downloader.c](https://github.com/munjeni/newflasher/blob/59f12e437d29f0385eb27dcebba5158aa3f97b45/downloader.c)：仅作协议线索，未执行其关闭 TLS 校验/递归下载的原始实现。
