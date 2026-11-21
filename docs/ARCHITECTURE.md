# 架构与实现

## 概览

ONEFILM 是一个单进程 Python Web 服务 + 一个单文件前端。它本身不实现下载协议，而是编排"百度网盘接口 → OpenList → curl"这条链路。

```
浏览器 ──HTTP──> movie_panel.py ──百度Web API──> 百度网盘(群文件库 + 个人网盘)
                       │
                       ├──OpenList API──> 直链
                       │
                       └──curl 子进程──> 本地磁盘
```

## 核心模块（movie_panel.py）

### 配置与路径

- 所有路径默认相对程序目录，可用环境变量覆盖（见 [CONFIGURATION.md](CONFIGURATION.md#环境变量)）。
- 启动时读取 `config.json`，并要求 `group_id`、`group_sign_salt`、`dirsize_sk` 均已填写。

### 百度接口封装

| 函数 | 接口 | 用途 |
|---|---|---|
| `ensure_token()` | `gettemplatevariable` | 用 Cookie 换取 `bdstoken`/`uk` |
| `bd_group_search()` | `basembox/group/search` | 群文件库实时搜索 |
| `group_transfer()` | `mbox/msg/transfer` | 把群文件转存到自己网盘 |
| `browse_list()` | `mbox/msg/shareinfo` | 只读列出群文件夹子项 |
| `bd_list_all()` | `api/list` | 列自己网盘目录（分页） |
| `folder_sizes()` | `sharedir/file/dirsize` | 批量查文件夹大小（带缓存） |
| `bd_delete()` | `api/filemanager` | 删除临时转存副本 |

签名：
- 群搜索 `group_sign(term)`：`base64(urlencode(md5(salt + "_" + gid + term)))`。
- 目录大小 `dirsize_sign()`：按百度约定的字段拼接后 MD5，用 `dirsize_sk`。

### 转存落库定位

百度把群文件转存进目标目录时，**不一定直接出现在目标目录顶层**，常会保留原来源的上一级结构。例如：

```
源：  /1117/影史最佳100部动画电影片单/2003 东京教父...
转存到 /_电影库 后可能变成：
      /_电影库/影史最佳100部动画电影片单/2003 东京教父...
```

为此实现了：

- `stage_candidate_parents(item)`：根据源路径推导可能的落库父目录集合。
- `snapshot_parents()`：转存前先快照这些目录的子项。
- `wait_new_stage()`：轮询顶层与各候选父目录，用差分 + 名称匹配找到新出现的副本；兼容百度自动加的 `(1)/(2)` 重名后缀。
- `norm_stage_name()` / `stage_name_hit()`：名称归一化与匹配。
- `probe_nested()`：超时后做最后一次递归探测，便于诊断。

这套逻辑是"整文件夹下载能正确落库"的关键。

### 下载引擎

- `prepare_batch_async()`：后台线程完成转存、列文件、取直链，再原子地用真实任务替换占位任务。HTTP 请求因此不被长耗时操作阻塞（"提交中…"不再卡住）。
- `collect_files(node)`：递归收集文件夹里所有文件（深度上限 12、数量上限 5000），生成相对输出路径，从而保留视频+字幕+封面的目录结构。
- `start_curl(gid, meta)`：调用 `curl -s -L -k -A pan.baidu.com -C - --retry 3 -o <dest> <url>`。用 `-C -` 实现断点续传；`pan.baidu.com` UA 对百度直链更稳定。
- `watchdog()`：每 2 秒巡检任务——更新进度与速度、进程退出后自动续传（最多 20 次）、整批完成后清理临时副本、清理过期浏览会话。
- `cleanup_batches()`：一批任务全部完成后删除网盘临时副本；若有失败项则保留副本以免丢数据。

### HTTP 服务

- 基于 `http.server.ThreadingHTTPServer`，单文件前端由 `/` 提供。
- `/api/download` 先返回占位任务再异步处理，保证响应迅速。
- 面板无登录密码（`_require_auth()` 恒真），设计用于局域网。

## 前端（web/index.html）

- 原生 HTML/CSS/JS，无构建步骤、无第三方库。
- 搜索结果可勾选；文件夹可"展开"进入只读浏览（`browse_id`），浏览不落盘。
- 启动时调 `/api/info` 获取目标目录与素材库路径，避免写死本机路径。
- 任务列表每 2 秒轮询 `/api/status`，进度条用 CSS 过渡平滑显示。
- 支持单条删除与批量清空已完成记录（配 toast 提示）。

## 设计取舍

- **为什么不用 aria2**：大文件写盘曾失败；curl 流式写入 + 断点续传更稳。
- **为什么不建索引**：群文件库数据量大且变动频繁，直接调用官方实时搜索接口，零维护成本。
- **为什么浏览不转存**：展开文件夹只看结构，若每次都转存会产生大量临时副本；只在真正下载时才转存。
- **为什么状态放 data/**：与代码分离，便于把状态放到内存盘、便于备份/清理。

## 扩展点

- 支持更多网盘：在 `ol_link()` 之外抽象出"取直链"适配器。
- 增加下载并发控制：当前按批次顺序处理，可引入并发度配置。
- 接入任务状态指示灯：本项目可与外部状态指示器联动（通过写状态文件），按需扩展。
