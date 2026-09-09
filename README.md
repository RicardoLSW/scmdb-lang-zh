# SCMDB 简体中文社区翻译

本仓库维护 SCMDB（<https://scmdb.net>）可直接加载的简体中文 Community Translation 文件，以及生成这些文件所需的、按游戏 build 固定的上游模板快照。

## 当前状态

已发布 LIVE `4.10.0-live.12568521` 的全汉化、双语和半汉化三种产物。默认 `dist/live.json` 指向全汉化版。222 个 token 风险条目已强制回退英文。扩展仓库 16 条已审校 UI 词条与当前 59 个 `scmdb_ui_*` 英文源没有精确交集，因此本轮未迁移译文，全部 SCMDB UI 条目继续保持英文。

公开 PTU 源文件的更新时间为 2025-10-15，对当前 PTU 模板缺失 1,042 个 keyed 条目，因此未发布 `dist/ptu.json`；详见 `reports/ptu-4.10.1-ptu.12578875.json`。

## 目录

- `upstream/SCMDB_LANG/`：获准再分发的 `KrovaxCode/SCMDB_LANG` 固定快照。
- `upstream/manifest.json`：来源仓库、commit、同步时间、文件大小与 SHA-256。
- `ui/reviewed/`：从扩展仓库固定 commit 摘录的已审校 SCMDB UI 来源快照。
- `ui/scmdb_ui_zh-CN.json`：只含精确匹配、语境一致且 token 安全词条的可追溯 sidecar。
- `dist/`：审核通过并提交的版本化语言文件与稳定入口。
- `release/`：版本、来源哈希、来源日期、variant、稳定别名与发布门禁配置。
- `tools/ui_sidecar.py`：按 exact source、context/page family 和 token 集合生成 sidecar 与覆盖矩阵。
- `tools/release.py`：固定上游同步、模板差异、候选生成和发布校验 CLI。
- `build/candidates/`：本地候选输出（Git 忽略，不会自动发布）。

## 重建 SCMDB UI sidecar

```bash
python tools/ui_sidecar.py --template upstream/SCMDB_LANG/lang-template-4.10.0-live.12568521.json --source ui/reviewed/scmdb-zh-extension-2026.09.0.json --sidecar ui/scmdb_ui_zh-CN.json --coverage reports/4.10.0-live.12568521/ui-sidecar-coverage.json
```

生成器只接受 `active` 且 `approved` 的来源条目，并要求英文源逐字一致、页面族和语境一致、`[]`、`{}`、百分号变量、转义及 EM 富文本 token 完整一致。别名、近似英文和语境冲突均保持英文。覆盖矩阵逐项记录 key、英文源、语境、token、回退原因及未命中的已审校来源，作为后续人工审校输入。

当前扩展词典版本 `2026.09.0` 的 16 条来源与 LIVE 模板 59 个 `scmdb_ui_*` 英文源无精确匹配，因此生成 sidecar 的 `keys` 为空；这不是缺失迁移，而是 exact-only 门禁的预期结果。

## 一条命令重建当前 LIVE

把合法取得、允许用于本项目的三个中文 `global.ini` 放在仓库外部。以下是一条逻辑命令；路径可以是绝对路径：

```bash
python tools/release.py build --config release/live.json --source full=/outside/full/global.ini --source both=/outside/both/global.ini --source half=/outside/half/global.ini --check-cors
```

工具先验证固定上游 commit、允许文件、模板文件名、`version`、`keyCount`、重复键、字节数和 SHA-256，再严格校验 sidecar 的语言、未知 key、精确英文源、逐项审校来源及 protected token，最后校验外部 INI 的配置版本、SHA-256、更新时间和缺失率。随后生成：

- `build/candidates/live/dist/<完整-build>/lang-zh-CN-{full,both,half}.json`；
- `build/candidates/live/dist/live*.json` 稳定别名；
- `build/candidates/live/dist/manifest.json`；
- `build/candidates/live/reports/<完整-build>/{full,both,half,validation}.json`。

`mismatchKeys` 中的 token 风险条目会强制回退英文。来源版本缺失或不匹配、来源过旧、缺失率异常、产物 schema/哈希/别名或 Raw CORS 校验失败时，命令返回非零并把候选标记为 `blocked`。报告只记录 key 名、计数、来源元数据和哈希，不记录外部 INI 的原文或本地路径。

候选不会写入仓库的 `dist/`，也不会提交、推送或发布。人工审校通过后，才可显式复制候选并更新已跟踪产物。

SCMDB 可加载的稳定 Raw URL 是：

```text
https://raw.githubusercontent.com/RicardoLSW/scmdb-lang-zh/main/dist/live.json
https://raw.githubusercontent.com/RicardoLSW/scmdb-lang-zh/main/dist/live-both.json
https://raw.githubusercontent.com/RicardoLSW/scmdb-lang-zh/main/dist/live-half.json
```

`live.json` 为默认全汉化版；`live-both.json` 为双语版；`live-half.json` 保持物品名、地名英文。PTU 稳定 URL 尚未发布。

## 同步与差异分析

先把上游 checkout 固定到明确的 40 位 commit，再同步允许文件；`--synced-at` 必须显式给出，使 manifest 可重复：

```bash
python tools/release.py sync-upstream --source-dir ../SCMDB_LANG --commit <40位commit> --synced-at 2026-09-09T00:00:00Z
python tools/release.py validate-upstream --report build/upstream-validation.json
```

同步只复制 `build_lang_template.py`、`README.md`（仓库内命名为 `UPSTREAM_README.md`）和合法的 `lang-template-*.json`，并更新固定 commit、字节数和 SHA-256。其他上游文件不会进入快照。

比较新旧模板并生成只含安全继承项的 sidecar：

```bash
python tools/release.py diff --old upstream/SCMDB_LANG/lang-template-old.json --new upstream/SCMDB_LANG/lang-template-new.json --previous-translation dist/old/lang-zh-CN-full.json --report build/template-diff.json --carryover build/unchanged-carryover.json
```

差异报告分别列出新增、删除、英文源变化和未变化 key。`carryover` 只包含英文源未变化且旧产物结构有效的 key；新增 key 和英文源变化 key 必须重新审校。

同步、生成和校验都不会配置定时任务、自动提交或自动发布，避免未经审校的变化进入用户加载的稳定 URL。

## 权利与边界

- 项目负责人已确认本项目获得当前上游材料的再分发允许；来源与固定版本见 `NOTICE.md` 和 `upstream/manifest.json`。
- Star Citizen 游戏数据及相关权利归 Cloud Imperium Games 等权利人所有。
- 本仓库不提供机器翻译，不接受未经授权的汉化包，不把 SHA-256 当作来源签名。
- 远程 Raw URL 是内容供应链；稳定入口只能指向通过版本和人工审校门禁的产物。
