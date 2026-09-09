# SCMDB 简体中文社区翻译

本仓库维护 SCMDB（<https://scmdb.net>）可直接加载的简体中文 Community Translation 文件，以及生成这些文件所需的、按游戏 build 固定的上游模板快照。

## 当前状态

已发布 LIVE `4.10.0-live.12568521` 的全汉化、双语和半汉化三种产物。默认 `dist/live.json` 指向全汉化版。222 个 token 风险条目已强制回退英文，59 个尚无中文 sidecar 的 SCMDB UI 条目保持英文。

公开 PTU 源文件的更新时间为 2025-10-15，对当前 PTU 模板缺失 1,042 个 keyed 条目，因此未发布 `dist/ptu.json`；详见 `reports/ptu-4.10.1-ptu.12578875.json`。

## 目录

- `upstream/SCMDB_LANG/`：获准再分发的 `KrovaxCode/SCMDB_LANG` 固定快照。
- `upstream/manifest.json`：来源仓库、commit、同步时间、文件大小与 SHA-256。
- `ui/scmdb_ui_zh-CN.json`：SCMDB 自身 `scmdb_ui_*` 文案的人工翻译 sidecar。
- `dist/`：审核通过后发布的版本化语言文件；当前为空。

## 生成翻译

把合法取得、允许用于本项目的中文 `global.ini` 放在仓库外部，再运行固定快照中的工具：

```bash
python upstream/SCMDB_LANG/build_lang_template.py   --profile ptu   --translate /path/to/global_zh-CN.ini   --translate-ui ui/scmdb_ui_zh-CN.json
```

工具会把文件生成在 `upstream/SCMDB_LANG/`。发布前应：

1. 核对输出 `version` 与目标 SCMDB build 完全一致；
2. 审查 `missing`、`mismatch`、`placeholderFallback`、`uiUntranslated`；
3. 把通过审查的文件移动到 `dist/<完整-build>/lang-zh-CN.json`；
4. 同时更新稳定入口 `dist/live.json` 或 `dist/ptu.json`；
5. 更新 `dist/manifest.json`，记录上游 commit、文件 SHA-256、覆盖统计和审校状态。

SCMDB 可加载的稳定 Raw URL 将是：

```text
https://raw.githubusercontent.com/RicardoLSW/scmdb-lang-zh/main/dist/live.json
https://raw.githubusercontent.com/RicardoLSW/scmdb-lang-zh/main/dist/live-both.json
https://raw.githubusercontent.com/RicardoLSW/scmdb-lang-zh/main/dist/live-half.json
```

`live.json` 为默认全汉化版；`live-both.json` 为双语版；`live-half.json` 保持物品名、地名英文。PTU 稳定 URL 尚未发布。

## 同步上游

1. 拉取 <https://github.com/KrovaxCode/SCMDB_LANG> 最新版本并记录 commit。
2. 只复制 `build_lang_template.py`、`README.md` 和 `lang-template-*.json`。
3. 验证模板文件名、`version`、`keyCount` 和 `keys` 一致。
4. 更新 `upstream/manifest.json` 的 SHA-256 与字节数。
5. 对比新旧模板：新增 key 进入待翻译；删除 key 不再发布；英文源变化的 key 必须重新审校；未变化 key 才可继承既有译文。
6. 重新生成并执行占位符、覆盖率与人工 UI 文案检查后，再更新 `dist/`。

同步和发布目前均为人工操作，不配置定时任务或自动发布，避免未经审校的上游变化直接进入用户加载的稳定 URL。

## 权利与边界

- 项目负责人已确认本项目获得当前上游材料的再分发允许；来源与固定版本见 `NOTICE.md` 和 `upstream/manifest.json`。
- Star Citizen 游戏数据及相关权利归 Cloud Imperium Games 等权利人所有。
- 本仓库不提供机器翻译，不接受未经授权的汉化包，不把 SHA-256 当作来源签名。
- 远程 Raw URL 是内容供应链；稳定入口只能指向通过版本和人工审校门禁的产物。
