# FS72 港版硬件跨刷 FS54 后：官方非擦除升级路径核查

核查日期：2026-10-31。场景：用户报告当前为 FS54 EU/UK `71.1.A.2.265`（Android 16），目标 `71.2.A.2.35`（官方元数据 Android 17）。**未读取手机，未调用 ADB/USB，未执行更新、修复或刷写；仅 GET 公开网页及下述限定的小型 ESS 元数据，并读取本地既有包/元数据，不提交 IMEI/序列号、不下载固件、不公开资源链接/令牌。** 不分析 Bootloader/GPT。

## 1. 结论与决策

- **官方明确提供本机 OTA 路径**：Xperia 1 VII（XQ-FS54/XQ-FS72）帮助指南写明 `设置 → 系统 → 系统更新`，通过 Software update 应用无线更新。[1][2] 这是正常系统更新路径，不是软件修复；但该页面**没有承诺任何状态下绝不丢数据，也没有公布 `.265 → .35` 的逐设备适用矩阵**。
- **这部跨刷手机是否实际获得可用 `.35` OTA，仍未知**。官方发布了 Android 17 帮助内容，[4] 本地官方服务响应也有 `.35`，但两者都不等于该手机已获推送。不能把型号/地区查询返回的发布包当成设备 OTA 资格确认。
- **没有核实到适用于此场景的官方电脑端“保数据更新”入口**。本机型官方指南列出的 Xperia Companion 用途是 **Software repair（软件修复）**，明确说会重新安装软件并删除个人数据。[3] 因而不能以“Companion 能装新版”为由把修复列作保数据方案。部分 Sony 支持页本轮 403，不能据此断言全球所有电脑更新服务均不存在，也不引用未读到的停服日期作结论。
- **原始 `update.xml` 和 `CR_SOFTWARE_UPDATE` 都不能证明本次升级保数据**。尤其本地两份新版 `*-software.xml` 实际选中的是 **`SOFTWARE_UPDATE_CONTENT_ERASE`**；匹配列表同时存在 `CR_SOFTWARE_UPDATE`。后续小元数据核查已确认：两地区各自的 CR 与擦除服务指向同一 APP_SW 内容来源，且对应各自已下载的 `.35` 包；**同包不等于同执行流程，更不等于保数据保证**。详见第 3 节。
- **目前不能认定“必须定制 Flash-mode 升级”**：应先核实设备是否有官方 OTA、以及 Sony 是否支持此混合身份。若可用，优先官方正常更新流程；若没有，不表示定制刷写已成为安全或获官方认可的替代方案。没有官方无损路径时，“暂缓升级”仍是保留数据约束下的有效选择。

## 2. 官方页面究竟支持什么

| 路径 | 一手证据 | 适用边界 |
|---|---|---|
| 无线系统更新 | [1] 写明无线安装是最简单的方法，需足够存储空间；[2] 给出设置入口，推荐 Wi-Fi，移动网络可下载的更新取决于运营商 | 证实机型具有官方更新功能；没有证明该跨刷组合的 `.35` 推送、源版本校验、迁移成功或零数据损失 |
| Xperia Companion 软件修复 | [3] 原文：`your device’s software will be reinstalled, and your personal data will be deleted in the process` | **擦除性重装，不满足本任务保数据要求**；知道 Google 账户信息是修复后的登录要求，不是数据保留机制 |
| Android 17 支持内容 | [4] Xperia 1 VII 指南直接链接 Android 17 变更指南 | 证实官方已编写该系统版本内容；不证明具体地区/设备已获某一 build 的 OTA |
| ESS 完整 APP_SW 分发 | 本地服务响应有型号、地区、版本、发行状态、资源列表等字段 | 能证明所查询软件服务及完整刷写包存在；不是面向当前手机的 OTA 安装许可或保数据服务条款 |

这里的“正常非擦除更新候选”与“无损保证”严格区分：官方更新说明未要求先做出厂重置，但本文不把这种正常更新语境升级成跨刷保数据承诺。即便后续确认 OTA 可用，也应先做独立备份并核实应用、认证器和 eSIM 的恢复条件；备份不等于全部应用状态都可还原。

## 3. 本地原始证据：名称不能替代执行语义

### 3.1 三份 APP_SW 的 `update.xml`

只读取原始 ZIP 中这个小成员，没有解包或分析 `boot.zip`、`partition.zip`。三份清单除 `FINGERPRINT` 外结构和值相同：

- `NOERASE`：`userdata_X-FLASH-ALL-B083.sin`、`metadata_X-FLASH-ALL-B083.sin`、`appslog_X-FLASH-ALL-B083.sin`、`diag_X-FLASH-ALL-B083.sin`、`reset-retail-demo-active-sts.ta`。
- `FACTORY_ONLY`：`persist_X-FLASH-ALL-B083.sin`。
- 另有 `SYSTEMPARTITIONIMAGE`、`BOOT`、`WKEY=0`、`FINGERPRINT`；这些字段本身不是面向用户的升级契约。
- 指纹分别声明 FS54/Android 16/`.265`、FS54/Android 17/`.35`、FS72/Android 17/`.35`。它们是包构建标识，不是对当前手机身份的读取。

**能说的**：包带有按镜像标注的“不擦除”线索，值得研究客户端如何解释。**不能说的**：任意工具会遵守这些标注；所有模式都不擦除；其他命令不会重置数据；不写 userdata/metadata 就足以保持可解密、可启动和应用迁移成功。本文未获得 Sony 对这些 XML 标签的公开规范，也未验证实际客户端消费流程；尤其不能据此覆盖软件修复明确的删除数据警告。

`update.xml` 原始成员 SHA-256（含原始编码/换行；不是重新序列化 XML 的摘要）：

| 本地包目录（位于 `firmware-downloads/packages/`） | 字节数 | SHA-256 |
|---|---:|---|
| `fs54-eu-71.1.A.2.265` | 598 | `9618b4c3cdd0dfdcaa79e639c1482c5e81f1d3a4a9b66e2e8071edd863b64f42` |
| `fs54-eu-71.2.A.2.35` | 597 | `0bfa6d2f7d4fbaf707c11e19228ab7e44fbb87d764df059f21362249d81cc1ad` |
| `fs72-hk-71.2.A.2.35` | 593 | `971646d8704f0df3cb6f93277f9f1cad995bf2fde8bcd7dacbfd5bdc1e2a3f59` |

原始 ZIP 精确名称、完整包摘要和此前校验范围见[既有固件报告](firmware-71.2.A.2.35-research.md)。本轮另外复核 FS54 `.35` 整包 SHA-256 为 `aeab7cab467dff1e3fc71b6becc87532d54789df79a6b7b3289cdf86ab707056`，与既有报告一致。

### 3.2 ESS 元数据的两个服务类型

以下仅摘录允许公开的产品/版本字段；没有输出 `href`、服务 ID、资源 ID、token 或设备唯一标识。

| 本地证据 | 观察 |
|---|---|
| `firmware-downloads/metadata/fs54-eu-software.xml` | 旧 `.265` 选中服务的 `logic-type=CR_SOFTWARE_UPDATE`，Android 16 |
| `firmware-downloads/metadata/research-71.2.A.2.35-20261031/{fs54-eu,fs72-hk}-match.xml` | 两地区各有 `.35` 的 `CR_SOFTWARE_UPDATE` **及** `SOFTWARE_UPDATE_CONTENT_ERASE` 条目；均为 Android 17、`RELEASED`、`TARGET`；`.265` 为 `INTERMEDIATE` |
| 同目录 `{fs54-eu,fs72-hk}-software.xml` | 两份已保存新版详情均是 **`SOFTWARE_UPDATE_CONTENT_ERASE`**；资源键为 `APP_SW`、`E_LABEL`、`CUSTOMER_ID`，安全状态字段为 `COMMERCIAL` |

解释限制：

1. `CR_SOFTWARE_UPDATE` 是 `logic-type` 字段值，**不是本轮已验证的保数据按钮或 OTA 协议**；未找到其缩写/行为的官方公开定义，不自行展开 `CR`。
2. `TARGET/INTERMEDIATE` 是版本分类字段；列表不是带源版本、完整前置条件、擦除策略和设备授权的迁移图，不能直接推导 `.265 → .35` 可无损升级。
3. 原先保存的 `*-software.xml` 不含 `.35` 的 CR 详情；后续已按原匹配 XML 的精确链接补取并完成比较，见第 3.3 节。两种服务共享各地区的 APP_SW 内容，但不能据此补上未观测的客户端执行语义。
4. 一个明确标为 `CONTENT_ERASE` 的已存服务所对应包仍含 `NOERASE` 标签，已经足以说明：**“包中有 NOERASE，所以整个服务不擦除”不是有效推理**。最终行为取决于客户端、服务模式及设备状态，不能只看文件名。

可复核方法：用 `zipfile.ZipFile(...).read('update.xml')` 读取上述三包的小成员并对原始字节做 SHA-256；用 XML 解析器仅选取 `logic-type/software-version/android-version/release-state/android-version-update-type` 等白名单字段检查本地响应。不要直接打印整个响应或重新访问其中的私有资源 URL。

### 3.3 补充核查：CR 与擦除服务是否共享 APP_SW

本次补充先执行 `ax agent-context`，再由 `ax` **仅 GET 4 个 XML 响应**：从两份原 `*-match.xml` 各自唯一的 `software-version=71.2.A.2.35`、`logic-type=CR_SOFTWARE_UPDATE` 条目读取原始 `rel=self` 精确链接（不猜测或改写服务地址），获取详情后，只跟随其中 `file-key=APP_SW` 的 `rel=file-chunk-info` 链接。每次响应设置 **1,999,999 字节硬上限**，实际全部小于 10 KB；未访问任何 `track-link`、分块下载链接或其他资源，未下载固件、未访问手机。

新原始响应仅保存在 Git 忽略的 `firmware-downloads/metadata/research-71.2.A.2.35-20261031/` 下，未覆盖旧文件：

| 地区 | 新 CR 详情 | 字节数 | 新 APP_SW 分块清单 | 字节数 |
|---|---|---:|---|---:|
| FS54 EU/UK | `fs54-eu-cr-software.xml` | 3,860 | `fs54-eu-cr-chunks.xml` | 9,713 |
| FS72 HK | `fs72-hk-cr-software.xml` | 4,136 | `fs72-hk-cr-chunks.xml` | 9,713 |

两份新详情均确认 `CR_SOFTWARE_UPDATE`、`.35`、Android `17`、`RELEASED`、`TARGET`，型号分别为 `XQ-FS54`、`XQ-FS72`，服务标识与各自原匹配条目一致、与擦除服务不同。以下比较均为**同地区 CR 对同地区擦除服务**，不是说 EU 与 HK 包互相相同：

| 比较项 | FS54 EU/UK | FS72 HK |
|---|---|---|
| APP_SW 名称 | `APP-SW_PDX256_GLOBALEEA-A4_USER_71.2.A.2.35_X-FLASH-ALL-B083_COM.zip`，一致 | `APP-SW_PDX256_GLOBAL-C2_USER_71.2.A.2.35_X-FLASH-ALL-B083_COM.zip`，一致 |
| `plain-size` | 4,665,814,296 字节，一致 | 4,665,768,932 字节，一致 |
| 资源内容身份 | `content-id`、`file-id` 均一致；资源清单链接路径一致 | `content-id`、`file-id` 均一致；资源清单链接路径一致 |
| 其他 APP_SW 字段 | `file-version`、`release-state`、`gzipped` 均一致 | `file-version`、`release-state`、`gzipped` 均一致 |
| 分块内容身份 | 清单根元素 `content-id` 一致 | 清单根元素 `content-id` 一致 |
| 45 块逐项比较 | 编号顺序 `0…44`、URL 协议/主机/路径、每块声明长度全部一致 | 编号顺序 `0…44`、URL 协议/主机/路径、每块声明长度全部一致 |
| 分块长度核对 | 前 44 块各 104,857,600 字节；末块 52,079,896 字节；总和等于 `plain-size` | 前 44 块各 104,857,600 字节；末块 52,034,532 字节；总和等于 `plain-size` |

比较未输出任何 URL、token、服务或资源标识值；路径比较在本地进行，没有为比较而请求这些路径。本次新旧分块清单连同查询部分在内的**原始 XML 字节也完全一致**，不是仅凭文件名或去掉鉴权参数后判定相同。

**与已下载包的对应关系**：两地区 CR 详情的 APP_SW 名称和大小分别匹配 `flash-kit/audit_upgrade.py` 中固定的 `.35` 条目；对应本地文件存在，文件大小亦匹配。结合与原擦除服务相同的资源内容身份及 45 块路径/长度，可确认 CR 服务的 **APP_SW 就是各地区已下载包对应的同一内容来源**，并没有发现另一份 CR 专用 APP_SW。这里仅对应 APP_SW，不宣称整个服务的所有附属资源或执行行为完全一致。

沿用既有整包 SHA-256（本次补充未重新下载、未重新哈希多 GB 包，也未运行审计程序）：

| 地区 | `audit_upgrade.py` 中既有完整包 SHA-256 |
|---|---|
| FS54 EU/UK | `aeab7cab467dff1e3fc71b6becc87532d54789df79a6b7b3289cdf86ab707056` |
| FS72 HK | `70f5513f7dd3c6fbb3a341962b430fc1831a7a46019e2e3fa7438242ee7fd992` |

**仍不能证明**：本轮元数据比较不是对远端固件字节的重新下载校验，也不是 Sony 签名验证；不能说明客户端如何选择镜像、解释 `NOERASE`、发送擦除/重置命令或执行迁移。更不能由 `CR_SOFTWARE_UPDATE` 名称或同包事实推出跨刷设备的 OTA 资格、`.265 → .35` 迁移兼容性、数据可解密/可启动、应用状态保留或零数据损失。不同服务可以使用相同输入包却采用不同执行策略；本轮没有验证任一服务在当前手机上的实际行为。

## 4. 仍缺什么，以及混合身份的边界

本次未与设备交互；以下只是后续最小信息清单，不是执行指令或本轮授权：

- **当前系统实际报告**的型号、完整 build、Android 版本，以及系统更新页面显示“无更新”还是某个具体版本、是否有错误/擦除提示。可由用户提供已遮蔽标识的文字或截图；不要发送 IMEI、序列号或账户信息。
- 当前生效的软件定制/地区身份是否仍有 HK 信息、既往跨刷是否改过相关身份组件。知道“硬件 FS72、系统显示 FS54”不足以复原服务端匹配输入。
- 当前系统是否 root、修改过系统镜像、解锁或处于不完整更新状态；这些可能影响校验，本文不检查具体启动链内容，也不声称已知 Sony 本机型的全部拒绝规则。
- OTA 当时的目标版本、可见前置条件、网络/运营商及推送时间；一次“没有更新”不能单独区分分批发布、身份不匹配和设备校验失败。
- **Sony 对这个准确组合的支持答复**：FS72 HK 硬件 + FS54 EU/UK `.265`，是否支持正常非擦除 OTA 到 `.35`，以及是否要求先恢复原地区。若答复只提供“软件修复”，应记录为不满足保数据需求，而不是当成无损路径。

指南标题覆盖 XQ-FS54 和 XQ-FS72，**不意味着覆盖把两种身份混在同一设备的状态**。既有元数据按地区查询成功，也没有完成当前手机级别的资格核验。即使手机显示更新可下载，也只能增加“已提供该更新”的证据，不能自行变成 Sony 对跨刷兼容性的书面保证。本文不采用论坛单例作为官方保证。

## 5. 证据来源与访问限制

公开页面均以 GET 获取，使用 `ax agent-context` 后由 `ax --md` 读取；以下四项本轮成功读取正文：

1. Sony Xperia 1 VII Help Guide，**Before updating your device**，页号 `TP1002221721`：<https://helpguide.sony.net/mobile/xperia-1m7/v1/en/contents/before_update_device.html>
2. 同指南，**Updating your device wirelessly**，页号 `TP1002221274`：<https://helpguide.sony.net/mobile/xperia-1m7/v1/en/contents/update_device_wirelessly.html>
3. 同指南，**Repairing the device software using Xperia Companion**，页号 `TP1002221668`：<https://helpguide.sony.net/mobile/xperia-1m7/v1/en/contents/repair_sw_xperia_companion.html>
4. 同指南，**Changes after updating the software to Android 17**，页号 `TP1002582776`：<https://helpguide.sony.net/mobile/xperia-1m7/v1/en/contents/changes_update_software_android_17.html>；其链接的 [Android 17 指南](https://helpguide.sony.net/mobile/xperia-a17/v1/en/index.html)本轮亦可读取。

Sony UK 软件/下载支持页及多地区支持文章（例如 <https://www.sony.co.uk/electronics/support/articles/00236877>）本轮返回 403，**不作为已核实正文来源**。没有用搜索摘要、第三方软件下载页或旧机型 Companion 教程填补缺口。原匹配列表、擦除服务详情及其分块清单是本地已留存的一手响应；第 3.3 节另按原匹配链接 GET 了两地区 CR 详情与 APP_SW 分块清单，共 4 个小响应。除此之外未重新查询其他 ESS 接口，没有验证手机 OTA 资格。
