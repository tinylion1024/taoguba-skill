# tgb-cli

基于 Rust 的淘股吧公开文章采集 CLI。工程可独立构建，内置大V作者目录，
支持热门榜、单篇文章、作者博客、精选文章、运行审计和结构化导出。

## 构建

需要 Rust 1.85 或更高版本：

```bash
cargo build --release
```

二进制位于 `target/release/tgb`。也可以从上级仓库安装：

```bash
cargo install --path tgb-cli
```

## 使用

```bash
# 热门文章及正文
tgb hot \
  --from "2026-07-25 00:00" \
  --to "2026-07-27 23:59" \
  --pages 5 \
  --fetch-body

# 单篇文章
tgb article 2rjdXpk0pCK

# 指定作者
tgb author 134434 --pages 3 --fetch-body --resume

# 内置作者目录中的精选/置顶文章
tgb vip --pages 2 --fetch-body --resume

# 查看运行及错误
tgb run list
tgb run show 1

# 导出语料
tgb export --run 1 --only-success --format jsonl --output data/run-1.jsonl
```

默认数据库为当前工作目录下的 `data/tgb.db`。可以在子命令前通过
`--database`、`--delay-ms`、`--max-attempts` 和 `--timeout-secs`
覆盖全局设置。采集命令支持 `--raw-dir` 保存原始 HTML。

大V目录同时保存在 `references/tgb_blog_authors.json` 并编译进二进制；
即使从其他工作目录运行，`tgb vip` 也能使用内置目录。要使用自己的名单，
传入 `tgb vip --authors /path/to/authors.json`。
