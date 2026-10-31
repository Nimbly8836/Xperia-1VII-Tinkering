# 固件输入与历史分块下载器

本目录只提交 `download_official.py` 和说明；**下载包、metadata、虚拟环境、第三方工具及日志全部忽略**。下载器只操作电脑文件，不访问手机。

## 刷机所需的最小输入

仅需固定的 FS54 EU/UK `71.1.A.2.265` 原始 APP_SW ZIP；文件名、路径和 SHA-256 见[根 README](../README.md#2-自行取得固定原始-zip)。不需要为刷机下载 FS72 SEA 分析样本、CustomerID 或 E_LABEL；受限刷写器也不直接刷这些包。

请自行通过合法、可信来源取得完全相同的原始 ZIP。重新打包的 ZIP 和只有解包 SIN 的工具输出不能替代固定源包。Sony 服务可能不再提供旧 `.265`；本项目不保证历史下载可用，也不会自动改用新版本。

## `download_official.py` 的限制

这是原研究环境的分块下载/续传脚本，**不是 clone 后即用的固件发现工具**。它需要先在本机准备：

```text
metadata/selection.json
metadata/<每个文件对应的 chunks_metadata XML>
```

这些文件包含资源 URL/临时查询参数，不公开提交。当前源码没有自动查询 Sony 产品目录并生成这些输入的 bootstrap 入口。因此，没有 metadata 时即使不加 `--download` 也会因缺少输入失败；请不要把它当成根 README 的必需步骤。

历史流程从 Sony 的产品目录 `https://app.swup.update.sony.net/ess-distribution/public/api/product/v2` 发现型号/硬件 ID，再查询对应地区的软件服务、资源和分块清单。公开接口、版本可用性和具体参数可能变化；需要自行重新核对，不能复制过期临时链接或混合地区包。

### 本地输入结构

`selection.json` 包含顶层 `version` 和 `packages` 数组。当前下载器严格要求：

| key | model | customization | version |
|---|---|---|---|
| `fs72-sea` | `XQ-FS72` | `XQ-FS72_Customized_SEA` | `71.1.A.2.265` |
| `fs54-eu` | `XQ-FS54` | `XQ-FS54_Customized_EU_UK` | `71.1.A.2.265` |

每个 package 的 `files` 必须包含 `APP_SW`、`CUSTOMER_ID`、`E_LABEL` 各一份，字段为 `name`（ZIP 文件名）、`kind`、`size`（字节数）、`chunks_metadata`（同目录 XML 文件名）。XML 根节点是 `file-chunks`，每个 `file-chunk` 有连续 `number`、`size`、`link href`。资源必须使用 HTTPS Sony filestorage 域名/路径，脚本会校验顺序与总长度。

此处是字段说明，不是可下载的资源清单。FS72 SEA 是研究对照，**不是 HK 原机恢复包**。

### 已自行准备有效 metadata 时

Python 3.10+，另需 `ax` CLI。请自行确认所安装的 CLI 实现是否支持脚本里的参数；脚本依赖 `ax URL -f -m ... --max-bytes ... -o ...` 以及 JSON 响应中的 `url`/`status`。也需要 `defusedxml==0.7.1`。

```bash
python3 -m venv firmware-downloads/.venv
firmware-downloads/.venv/bin/python -m pip install defusedxml==0.7.1

# 只显示/校验计划，仍需要 metadata
firmware-downloads/.venv/bin/python firmware-downloads/download_official.py

# 明确下载：两套包共六个 ZIP，约 8.47 GiB，另留磁盘余量
firmware-downloads/.venv/bin/python firmware-downloads/download_official.py --download
```

脚本不自动解包，使用进度记录复核已下载分块，仅允许单实例；完成后复核总长度、SHA-256 和 ZIP CRC。`.partial` 不是完成品。已有 ZIP 缺少该下载器的完成收据时，它会拒绝接管；手动取得的固定源包直接交给 `flashkit.py audit`，无需伪造下载收据。

**本地 SHA-256 / CRC 用于一致性检测，不是 Sony 签名验证，也不意味着跨刷安全。**
