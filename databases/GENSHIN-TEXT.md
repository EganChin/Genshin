# 原神独立离线剧情与公共资料

## 来源与范围

- 原始数据为 `../public-data/genshin-text/` 的独立 Git 稀疏检出，来源 <https://github.com/DimbreathBot/AnimeGameData>；剧情索引为 `genshin-text.sqlite`。数据与其他工作区分别更新，不含账号信息。
- 当前基准提交 `d7f2135c7eb0052e842e0f187f4e5bb88c304737`；索引包含 886,217 条文本、1,176,662 处可解析引用、507 个 CodexQuest 任务回顾、545,085 条对话记录（有重复引用），以及阅读物和字幕。实际版本与文件清单以原始目录 `manifest.json`、Git HEAD 和数据库 metadata 为准。
- 来源包括中文 TextMap、ExcelBinOutput、BinOutput 的任务/对话/任务回顾/邀约/故事/过场/NPC，及中文 Readable 和 Subtitle。第三方数据可能缺失或滞后，纯画面、动作、语气和不在数据中的文本不保证覆盖。

## 剧情查询

```powershell
python -X utf8 tools/genshin_text.py search 世界树 --limit 10
python -X utf8 tools/genshin_text.py search 派蒙 --limit 5
python -X utf8 tools/genshin_text.py quest 1000
python -X utf8 tools/genshin_text.py books 司巫的记录 --limit 1
python -X utf8 tools/genshin_text.py subtitles
python -X utf8 tools/genshin_text.py subtitles Ambor_Readings_CHS.srt
python -X utf8 tools/genshin_text.py source Readable/CHS/Book1074.txt
```

`subtitles` 列出或按文件名读取字幕；`source` 按清单中的相对路径读取原始 JSON、阅读物或字幕，读取前校验文件 SHA-256 和索引提交，JSON 内容保留上游结构。

`search` 返回文本、编号、可确认的说话人与任务、原始文件和 JSON Pointer；阅读物及字幕另返回片段。结果数量受限制，不能据此推断出现次数。`quest` 输出 CodexQuest 原始结构和可解析中文，保留选项及后续编号；并非所有任务都有回顾，不把分支视为唯一剧情顺序。

`books` 按标题、正文或文档编号匹配，沿 `DocumentExcelConfigData` → `LocalizationExcelConfigData` → 明确的中文 Readable 路径读取正文，输出标题、正文和各层来源。当前提交的文档到本地化列表字段为 `PLOJOMIPJGH`，若上游改名则命令会停止或查不到，需重新核验，不按数字相近猜测。该命令覆盖可确认关联的条目；原始文件可能包含未能通过此链路关联的阅读物。已验证《司巫的记录·其一》：文档 121305 → 本地化 201074 → `Readable/CHS/Book1074.txt`。

## 公共配置

```powershell
python -X utf8 tools/genshin_public.py character 砂糖 --level 9
python -X utf8 tools/genshin_public.py weapon 14519 --refine 2
python -X utf8 tools/genshin_public.py artifact 15002
python -X utf8 tools/genshin_public.py table AvatarCurveExcelConfigData --field level --value 90
```

工具直接校验并读取 Git 数据的原始 JSON，保留中文模板和原始系数。技能按 Avatar → SkillDepot → Skill → ProudSkillGroup + level 关联；等级、形态及参数含义需另行核对。原始参数不自动等于伤害倍率，缺失等级不以其他等级代替。工作区没有账号数据，不能进行账号覆盖检查，也不提供战斗模拟。

## 更新、重建与验证

```powershell
python -X utf8 tools/update_genshin_text.py
python -X utf8 tools/update_genshin_text.py --offline --rebuild
python -X utf8 tools/verify_genshin_text.py
```

更新先检查数据仓库是否干净，fetch 并仅快进，按 Git blob 校验来源并更新清单；数据有变化或要求重建时，构建候选索引，验证完整性、长短关键词及出处指针与任务样例，再替换正式索引。出错时保留或恢复旧索引与清单，并尝试恢复旧提交；不能在更新期间并行查询或修改数据仓库。无变化时校验来源，不重复重建。网络失败会重试，历史不能快进则停止；更新不会自动运行。

与原工作区不同，此目录不含账号数据，因此更新不执行账号角色覆盖和已装备武器校验；它们不能从剧情索引的验证结果推断。独立目录验证记录在 `genshin-text-validation.json`；离线完整重建已通过。隔离 Git 测试仓库通过注入候选构建失败验证了旧提交、清单和数据库的恢复；真实远端新版本升级及其他失败时序尚未实测。
