## KKPA-234 TDD 证据

### 用户旅程

作为 LIVE 发布审计者，我希望使用配置中固定的三个外部 INI 重建当前候选，并让已跟踪报告和 manifest 与候选一致，从而可以在干净 checkout 中重复验证来源、门禁、产物哈希和 PTU blocked 边界。

### RED / GREEN

| 行为 | RED | GREEN |
| --- | --- | --- |
| 已跟踪 LIVE 报告和 manifest 使用当前输出契约 | `test_checked_in_live_release_matches_current_output_contract` 失败：manifest `schemaVersion` 为 1，预期为 2 | v2 manifest 与三份 v2 variant 报告通过交叉核对 |
| PTU blocked 报告由配置哈希固定 | `test_blocked_release_reports_are_hash_pinned` 失败：`load_blocked_releases` 不存在 | 路径、状态、variant、build、schema 和 SHA-256 均通过校验 |
| Windows checkout 的发布文件字节可审计 | artifact 实际 SHA-256 因 CRLF 与 manifest 不同 | `.gitattributes` 固定 JSON 为 LF；版本化产物和稳定别名的 SHA-256/字节数全部通过 |
| blocked 路径跨平台一致且 JSON 只读取一个字节快照 | 非规范路径未在哈希前拒绝；`load_json` 通过文件句柄读取 | 反斜杠、尾随空格/句点和 `..` 被拒绝；JSON 从一次 `read_bytes()` 快照解析 |

### 测试规格

| 保证 | 测试/命令 | 类型 | 结果 |
| --- | --- | --- | --- |
| 配置来源元数据与 full/both/half 报告逐项一致 | `test_checked_in_live_release_matches_current_output_contract` | 集成 | PASS |
| 报告含 `source.version`、`uiSidecar`、`gates` 和 `artifact.variant` | 同上 | 集成 | PASS |
| manifest artifact/alias 的文件 SHA-256 与字节数一致 | 同上 | 集成 | PASS |
| PTU blocked 报告路径和 SHA-256 被固定 | `test_blocked_release_reports_are_hash_pinned` | 单元 | PASS |
| JSON 重复键继续拒绝且解析使用单一字节快照 | `test_load_json_rejects_duplicate_keys`、`test_load_json_reads_one_immutable_byte_snapshot` | 单元 | PASS |
| token 安全回退与 sidecar 门禁不回退 | 完整 `unittest discover` | 回归 | PASS（32 项） |
| 固定上游快照完整 | `python tools/release.py validate-upstream` | 集成 | PASS |
| 外部输入、语言产物与 Raw CORS 门禁 | `python tools/release.py build ... --check-cors` | 端到端构建 | PASS |

### 重建结果

- 输入 SHA-256：full `aa3667b9cb82f17f3144b2e8c64f8fc3496b68ec054982bf642eb9744ac97394`；both `f9042b9fb61926b7d4be2afadbc3f22557879b73fc6abcf663e760207f362e17`；half `a737e8471ab2579e955e430658f02715e31d0adf6016088f7ec04e2d102e1122`。
- 产物 SHA-256：full `4fa35ac844009892a70c7fa1899941ce1cf1f6d70e03a81e7da663a9131e1ceb`；both `c1e9d2b05bdbb4dd067f7295a94d71d5d29624893eaabcafba0986624dddb8ab`；half `8414d9a174839c38f8f6505a845c24a3c3fe28d231d4b3d04f4812ed40c69a4a`。
- 候选 `full.json`、`both.json`、`half.json` 和 `dist/manifest.json` 与已跟踪文件逐字节一致。
- 四个稳定 Raw URL 的 CORS 与内容哈希全部通过。
- PTU 仍无发布产物；blocked 报告 schema v1 的固定 SHA-256 为 `c1dc2d09db8e1818317c09c6f40b41de4c5e7915601642ae284c52233de6d0e3`。

### 覆盖与已知缺口

项目未配置独立 coverage runner，因此没有伪造覆盖率百分比；本次运行全部 32 项单元/集成测试并完成真实三 variant 构建。外部 INI 仅用于本地验证，未加入仓库。
