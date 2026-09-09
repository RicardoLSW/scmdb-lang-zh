# 审计报告

每个已发布 LIVE variant 使用审计 schema v2，记录来源 URL/SHA-256/版本/更新时间、上游 commit、builder 原始统计、发布统计、sidecar 覆盖、门禁结果和带 variant 的产物 SHA-256。`safetyFallbackKeys` 中的条目因 token 风险被强制回退英文。配置文件 schema 版本与报告 schema 版本彼此独立。

PTU 报告是未生成产物的历史 blocked 记录，继续使用其原有 schema v1；`release/live.json` 以仓库相对路径和 SHA-256 固定该记录，v2 manifest 同时记录报告版本与哈希，避免把 blocked 历史误当作可发布 variant 报告。

`<build>/ui-sidecar-coverage.json` 逐项记录当前模板全部 `scmdb_ui_*` key 的英文源、页面语境、protected token、迁移状态与英文回退原因，并列出没有精确模板源的已审校扩展词条。该文件是后续人工补齐 SCMDB UI 翻译的机器可读输入。

`tools/release.py build` 还会在本地候选目录生成 `validation.json`，机器可读地汇总上游快照、sidecar 来源与覆盖、外部 INI 门禁、产物 schema/哈希、稳定别名及 Raw CORS 检查。所有报告只列 key 名、英文模板文本、审校来源和统计，不包含原始 INI 译文或本地输入路径。
