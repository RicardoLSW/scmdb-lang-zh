# 发布产物

- `live.json`：LIVE 默认全汉化版。
- `live-full.json`：与 `live.json` 相同的显式全汉化入口。
- `live-both.json`：物品名、地名中英双语。
- `live-half.json`：物品名、地名保持英文。
- `<build>/`：版本化产物；通过发布 commit 的 Raw URL 固定内容后适合复现和手动回滚，严格归档应同时记录 SHA-256。
- `manifest.json`：schema v2 发布审计索引，记录产物/稳定别名的 SHA-256、字节数、来源 commit，以及按报告版本和 SHA-256 固定的阻断项。

稳定 URL 适合跟随人工审校后的 LIVE 更新；版本化 URL 适合固定 build。切换或回滚必须由用户在 SCMDB Community Translation 设置中手动完成，本仓库不会自动写入远程 URL。清除语言文件应使用 SCMDB 自带的 Clear/Disable translation 控件。

PTU 尚未发布：公开 PTU INI 对当前模板缺失 1,042 个 keyed 条目，不存在可用的 `ptu.json`、`ptu-full.json`、`ptu-both.json` 或 `ptu-half.json`。
