# 审计报告

每个已发布 variant 都记录来源 URL/SHA-256/版本/更新时间、上游 commit、builder 原始统计、发布统计、门禁结果和产物 SHA-256。`safetyFallbackKeys` 中的条目因 token 风险被强制回退英文。

`tools/release.py build` 还会在本地候选目录生成 `validation.json`，机器可读地汇总上游快照、来源门禁、产物 schema/哈希、稳定别名及 Raw CORS 检查。所有报告只列 key 名和统计，不包含原始 INI 文本或本地输入路径。
