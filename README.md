# 原神资料工作区

这是独立的《原神》剧情与公共资料工作区，不依赖原工作区，不含账号快照。

- `databases/genshin-text.sqlite` 是中文剧情和文本索引；`public-data/genshin-text/` 是独立 Git 数据源。查询、更新和限制见 [剧情库说明](databases/GENSHIN-TEXT.md)。
- 角色、技能、武器和圣遗物等公共配置来自同一 Git 数据源，使用 `tools/genshin_public.py` 查询。没有账号数据和战斗模拟结果。
- 剧情问答的证据对应方式见 [回答示例](databases/PLOT-ANSWER-EXAMPLE.md)。示例中的故事是虚构的，不代替本次查询。

在此目录的 PowerShell 中执行：

```powershell
python -X utf8 tools/genshin_text.py search 世界树 --limit 10
python -X utf8 tools/genshin_text.py quest 1000
python -X utf8 tools/genshin_text.py books 司巫的记录 --limit 1
python -X utf8 tools/update_genshin_text.py
```

需要 Git 和带 SQLite FTS5 trigram 的 Python。此工作区的数据与原工作区是独立副本，后续更新不会自动同步。
