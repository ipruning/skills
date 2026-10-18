# Advanced Queries

只包含能改进检索决策的知识：query 语义、候选与证据、`list` vs `find`、只读 metadata SQL、同标题 identity。

## Query/tokenizer 实务

Sherlog 不把用户输入原样透传给 FTS：

- 非 CJK 文本按词切分并 lowercase；连续 Han/Hiragana/Katakana/Hangul 生成重叠 bigram。
- 多 term 是 AND 语义；用户输入的 `OR`、`NEAR`、`*` 或 quotes 不应被当成 native FTS operator。
- 单个 CJK 字等短输入可走有界 literal 匹配，但不是可扩展的 fuzzy search，也没有全正文无界 fuzzy。

Refine 指导：

- 先用自然关键词；过窄时删掉冗余 term；
- 过宽时增加稳定 identifier/error phrase（如版本号、接口名、cwd）；
- 中英混合 query 可以用中文短词 + English identifier；
- 单字 CJK 至少补成两字词；
- 零结果按 `zeroResults` / coverage policy 处理，不要盲目原样重复。

## Candidate 与 evidence

`find` 返回 candidate：message body、session title、summary、compact、reasoning summary 都可能命中。session-profile 命中只是 recall signal，**不是** message evidence。

- `matchSource="session"`、`matchSeq=null` 时仍执行完整 `evidenceRead.command`；
- `read-range --query` 无 message anchor 会返回 typed `anchor_not_found`，按 nextAction 回退 `read-page`；
- 不要先拉全库候选再自行过滤，也不要把 session score 当成 message anchor。

## `list` vs `find`

已知 project/time、关键词弱时先 `list`：

```bash
shlog list --cwd <cwd-fragment> --since <iso> --json
```

需要内容主题时 `find`：

```bash
shlog find "specific phrase" --cwd <absolute-cwd> --json
```

`list --cwd` 是 case-insensitive substring；`find --cwd` 构造 exact cwd selector。两者 coverage 语义不同。

## Read-only SQLite metadata projection（可选）

`list`/`stats` 已覆盖常见 metadata 需求。需要更细的只读投影时用 `sessions` compatibility view（物理 writer table 不要改）。DB path 从 `stats --json` 取得：

```bash
DB_PATH="$(shlog stats --json | jq -r '.dbPath')"
sqlite3 -readonly "$DB_PATH" \
  "SELECT session_key, started_at, message_count, cwd, title
   FROM sessions
   WHERE message_count > 0
   ORDER BY started_at ASC
   LIMIT 20;"
```

metadata 不是内容证据；拿到 candidate 后用 `read-range` / `read-page`。

## Same-title variants

Codex resume/fork 可能出现 title 相似但 identity 不同的 session；当前不会按 title family collapse：

- 不要先按 title 去重；
- 看 `sourceId/sessionRef`、cwd、time、matchCount；
- 用 evidence read 决定是否同一决策链。
