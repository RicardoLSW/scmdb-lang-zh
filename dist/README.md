# 发布产物

- `live.json`：LIVE 默认全汉化版。
- `live-full.json`：与 `live.json` 相同的显式全汉化入口。
- `live-both.json`：物品名、地名中英双语。
- `live-half.json`：物品名、地名保持英文。
- `<build>/`：不可变的版本化产物。
- `manifest.json`：schema v2 发布审计索引，记录产物/稳定别名的 SHA-256、字节数、来源 commit，以及按报告版本和 SHA-256 固定的阻断项。

PTU 尚未发布：公开 PTU INI 对当前模板缺失 1,042 个 keyed 条目。
