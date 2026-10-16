# 区域赛奖牌参考与 DLUT 离线统计

区域赛页面在比赛名后展示可隐藏的金银铜参考列，采用与 CF Bot 同步的当前发布 Rating 和正式终榜奖牌分界。隐藏选择保存在浏览器本地。

- 手速线：该档末位获牌队的解题数，达到题数仍需比较罚时。
- 稳牌线：所有低于该档奖牌的正式队中最高解题数加一。银铜包含更高奖牌，按本科/专科等独立奖牌分组计算；保证范围为该场固定终榜和相同获奖资格。
- 参考 Rating：将全场题目按当前 Rating 升序排列，取第 k 题，表示完成 k 题所需最高难度的理论最小值。未评级不填零，超过总题数标为不可达。

`catalog/regional_ratings.json` 新增 `medal_safety` 和多组比赛的 `medal_reference_groups`，既有题目 Rating 保持不变。页面直接使用现有 `/api/cpc/me` 返回的发布数据。

## 离线统计

`scripts/build_dlut_medal_report.py` 只生成离线结果，不导入平台。将 DLUT CPC 公开参赛记录按实际日期筛选为 2020-01-01 至 2026-10-16，与固定版本原榜唯一匹配学校、队名、正式/打星资格和日期，再读取赛时最终 AC。输出保留逐题成绩、原榜行 ID、原榜链接和来源异常。包含疫情期间实际报名参赛的线上区域赛，不含 VP 或赛后训练。

队伍升级方案保留已有 AC，从未解题按 Rating 升序补足下一档奖牌所需题数，同时列出新增题中的最高 Rating，以及保留已有 AC 后全部题目的最高 Rating 最小值。手速方案同题数仍需比较罚时；打星队不计算获牌路径。

```sh
python3 scripts/build_dlut_medal_report.py \
  --dlut /path/to/dlut-public-snapshot.json \
  --snapshot /path/to/pinned-board-data \
  --extra-boards /path/to/supplemental-rankland-html \
  --output /path/to/report.json
```

当前输出覆盖主校区 160 条、盘锦校区 20 条参赛记录，全部 180 条赛时 AC 已核验，其中 175 条有当前评级。2020 赛季银川站 2 条及 EC Final 3 条保留 AC、奖牌和来源，缺失的 Rating 与升级难度留空。决赛跨年按实际参赛年份归年，赛季另列；2022 赛季 EC Final 的原榜年份笔误按承办方报道核验为 2023-03-25。
