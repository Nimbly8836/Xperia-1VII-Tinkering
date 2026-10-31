# FS54 .265 → .35：离线结论

未连接设备、运行ADB/USB或修改生产代码；未改变REA目标。仅解析ZIP/TAR及小文件，暂存约18.6MB于忽略目录 `firmware-analysis/upgrade-boot/`。整包SHA沿用 `flash-kit/audit_upgrade.py` 固定值，本次未重读整包验证；成员读取校验CRC，未验证Sony签名。

## Bootloader

新版商业SIN SHA256：`260b0ce3c9d143d3627b7b3e363aa5ae5502522729dda7ecbe3a53e15ace0bd8`。

GZIP→TAR仅含 `bootloader.cms`（793B）、`bootloader.000`（14082048B），协议目标是 **bootloader**，不是Android的boot。所谓“sparse chunk”实际上无Android sparse魔数：头为 `0xce1ad63c`，版本1；推定76B头、1760B目录，22项×80B，每项+72/+76为LE偏移/长度，载荷4KiB对齐、均以ELF开头：

`apdp,abl,aop,aop_config,cpucp,cpucp_dtb,devcfg,hyp,keymaster,pdp,pdp_cdb,qupfw,shrm,soccp_dcd,soccp_debug,tz,tzxflattest,uefi,uefisecapp,xbl,xbl_config,xbl_ramdump`。

V36/V40各项位置、长度相同，22项哈希全部变化；新版两地区11成员相同。GPT无bootloader实体分区；手机端复合目标如何分派、原子性未知。

## TA/GPT

boot-config只含TA分区2：`0x084F=2127`（82B）、`0x08FD=2301`（1B，00），对应 `Write-TA:2:2127/2301`；三包894B文件哈希相同。字段语义、现机值及可安全省略/必要性均未知。

根目录四个小TA三包相同：auto-boot→0x0907、osv-restriction→0x091A、reset-kernel-cmd-debug→0x09A9均写00；reset-retail-demo→0x0A1E零长度。工具另写2:10100进/出刷机模式。

五份GPT载荷各24576B，三包逐字节相同，头/表CRC通过：4KiB扇区；LUN0三容量均105项，LUN1/2各5项；边界、GUID、属性未变，CMS不同。只证明包内布局不变，不证明现机布局或super内部兼容。

## 固定上游行为及风险

`flash-kit/upstream/newflasher-59f12e4.c.txt`：2148–2153误把SPACE_ID当版本；5155–5199按安全状态/平台/root hash匹配，支持仅root hash回退，并非FS型号兼容验证；先TA后SIN。

1969–2093：CMS认证→下载数据→查询 `getvar:has-slot:bootloader`→`erase:bootloader[_a/_b]`→`flash:bootloader[_a/_b]`。bootdelivery只调用一次；4891–5035的双槽逻辑仅根目录特定SIN，不能套用于boot目录；最终 `set_active` 当前槽。

可审计的是既有流程：2:10100=1→GPT→根SIN（readdir无固定顺序）→根TA→bootdelivery→set_active→2:10100=0→Sync。无partition_delivery.xml时会遍历全部GPT，不能直接解出三个LUN0变体运行。

NOERASE仅在选择保留数据后跳过userdata/metadata/appslog/diag及retail-demo TA；其余目标仍擦除。**不存在已证实安全的保数据升级顺序**：应先完成备份/恢复、槽位、AVB回滚、Android16→17迁移及V40审查；不能以同名、同root hash或GPT不变推定V36兼容。当前只允许离线准备，禁止执行上述协议命令。
