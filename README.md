# ONEFILM

> 网盘一键下载至本地服务器 —— 直接调用百度网盘**群文件库**自带实时搜索，把电影（含字幕、封面等附属文件）批量转存并下载到本机/NAS/软路由，不建索引、不拉全量、不分享链接。

ONEFILM 是一个跑在你自己设备上的轻量 Web 面板。它面向"群文件库"这类大型共享片源场景：输入关键词即可调用百度网盘群文件库的实时搜索接口，勾选单个文件或整个文件夹，点一下就完成"转存 → 取直链 → curl 下载 → 清理临时副本"的全流程。

**界面一览**（文字示意，实际为深色圆角卡片 + 任务状态灯）：

```
  ONEFILM                              网盘一键下载至本地服务器
  ──────────────────────────────────────────────────────────────
  搜索  [ 东京教父                                    ]  [ 搜索 ]
  ──────────────────────────────────────────────────────────────
  搜索结果
    [+] [DIR]  2003 东京教父 Tokyo Godfathers      9.4 GB   [下载]
        |-- [FILE] Tokyo.Godfathers.2003.mkv       9.4 GB
        `-- [FILE] Tokyo.Godfathers.zh.srt          68 KB
    [+] [DIR]  2001 千与千寻 Spirited Away         7.2 GB   [下载]
  ──────────────────────────────────────────────────────────────
  下载进度                                            [清空已完成]
    [*] 东京教父  [############------]  58%   8.2 MB/s      [x]
    [v] 千与千寻  [##################] 100%   已完成        [x]

  说明：[+] 展开文件夹（只读、不转存）  [x] 删除该条记录
        [*] 进行中  [v] 已完成
```

有真实截图时，可按 [docs/screenshot-placeholder.md](docs/screenshot-placeholder.md) 替换为图片。

## 特性

- **群文件库实时搜索**：直连百度 `basembox/group/search` 接口，搜什么出什么，无需抓取、无需索引、无需维护文件清单。
- **整文件夹下载**：可展开文件夹查看子内容，勾选后递归下载里面的所有文件（视频、字幕、封面等一律保留）。
- **文件夹大小**：列表实时显示文件夹体积（走百度 `sharedir/file/dirsize`）。
- **浏览不落盘**：展开文件夹走只读会话，不产生任何临时转存副本；确定下载时才转存。
- **稳定下载**：用 `curl -C -` 断点续传替代易出问题的下载器，大文件友好；进度 2 秒刷新。
- **自动清理**：任务完成后自动删除百度网盘里的临时转存副本，不污染你的网盘。
- **进度可管理**：单条删除、批量清空已完成记录（只删记录，不动本地文件和网盘文件）。
- **零第三方依赖**：后端只用 Python 标准库 + 系统 `curl`；前端是单文件原生 HTML/JS。
- **LAN 部署**：设计运行在局域网内（软路由 / NAS / 小主机），无需公网暴露。

## 架构与流程

```
┌──────────┐   搜索/勾选    ┌──────────────┐   转存    ┌────────────┐
│ 浏览器    │ ───────────▶  │ ONEFILM      │ ────────▶ │ 百度网盘    │
│ 面板      │ ◀───────────  │ (Python HTTP)│           │ (群文件库)  │
└──────────┘   进度/状态    └──────┬───────┘           └─────┬──────┘
                                  │ 取直链                    │
                                  ▼                           │ 临时副本
                           ┌──────────────┐                   │
                           │ OpenList     │ ◀────────────────-┘
                           │ (AList 兼容) │
                           └──────┬───────┘
                                  │ curl -C -
                                  ▼
                           ┌──────────────┐
                           │ 本地磁盘/NAS │
                           └──────────────┘
```

1. 搜索：调用群文件库实时搜索，返回文件/文件夹及转存所需凭证。
2. 转存：把选中项转存到你网盘中已存在的素材库目录（如 `/_电影库`）。
3. 定位：兼容百度转存时保留的嵌套上级目录，准确找到落库副本。
4. 下载：OpenList 拿到直链，`curl` 断点续传下载到本地目标目录。
5. 清理：整批完成后删除网盘中的临时转存副本。

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 快速开始

### 前置条件

- Python 3.8+（OpenWrt 上是 `python3`）
- `curl`（支持 `-C -` 断点续传）
- 一个百度网盘账号 + 一个你能访问的**群文件库**（需要群 ID）
- 已部署 [OpenList](https://github.com/OpenListTeam/OpenList)（或其 AList 分支），挂载了你的百度网盘

### 安装（通用 Linux / 软路由 / NAS）

```bash
git clone https://github.com/turetsky979/onefilm.git onefilm
cd onefilm

# 1. 配置
cp config.example.json config.json
vi config.json          # 填入你自己的值，见「配置」一节

# 2. 写入百度网盘 Cookie
cp baidu_cookie.example.txt baidu_cookie.txt
vi baidu_cookie.txt     # 粘贴你的百度网盘 Cookie（见 docs/GET_COOKIE.md）

# 3. 启动
sh scripts/start.sh
```

打开 `http://<设备IP>:8088` 即可使用。

### 安装为 OpenWrt / iStoreOS 服务

```bash
cp -r onefilm /opt/onefilm
cp /opt/onefilm/init.d/onefilm /etc/init.d/onefilm
chmod +x /etc/init.d/onefilm
# 按你的实际安装路径修改 /etc/init.d/onefilm 里的 APP_DIR
/etc/init.d/onefilm enable
/etc/init.d/onefilm start
```

完整步骤见 [docs/INSTALL.md](docs/INSTALL.md)。

## 配置

`config.json` 字段说明（**此文件含敏感信息，已被 `.gitignore` 忽略，切勿提交**）：

| 字段 | 说明 | 示例 |
|---|---|---|
| `openlist_base` | OpenList 服务地址 | `http://127.0.0.1:5244` |
| `openlist_token` | OpenList 管理员 Token | `openlist-xxxx` |
| `library_baidu_path` | 网盘中已存在的素材库目录 | `/_电影库` |
| `library_root` | 该目录在 OpenList 中的挂载路径 | `/1/_电影库` |
| `group_id` | 百度群 ID（群文件库归属） | 你的群 ID |
| `target_dir` | 本地下载保存目录 | `/mnt/disk/Movies` |
| `port` | 面板监听端口 | `8088` |
| `group_sign_salt` | 群搜索接口签名盐 | 见文档 |
| `dirsize_sk` | 文件夹大小接口签名 key | 见文档 |

Cookie 单独放 `baidu_cookie.txt`。获取方法与签名常量的提取见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md) 和 [docs/GET_COOKIE.md](docs/GET_COOKIE.md)。

所有路径类配置也可用环境变量覆盖（优先级高于配置文件），详见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md#环境变量)。

## API

面板通过一组 JSON 接口与后端通信：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/info` | 返回目标目录、素材库路径（供前端展示） |
| GET | `/api/search?kw=` | 群文件库实时搜索 |
| GET | `/api/list?path=&browse_id=` | 列目录（本地网盘或只读浏览会话） |
| POST | `/api/dirsize` | 批量查询文件夹大小 |
| POST | `/api/browse` | 创建只读浏览会话（不转存） |
| POST | `/api/browse_close` | 关闭浏览会话 |
| GET | `/api/folder_videos?path=` | 列出文件夹内视频文件 |
| POST | `/api/download` | 提交下载任务（异步） |
| GET | `/api/status` | 查询任务进度 |
| POST | `/api/task_delete` | 删除单条任务记录 |
| POST | `/api/task_clear_done` | 清空已完成记录 |

详见 [docs/API.md](docs/API.md)。

## 目录结构

```
onefilm/
├── movie_panel.py            # 后端服务（标准库实现）
├── config.example.json       # 配置模板（复制为 config.json）
├── baidu_cookie.example.txt  # Cookie 模板（复制为 baidu_cookie.txt）
├── web/
│   └── index.html            # 单文件前端面板
├── init.d/onefilm            # OpenWrt/iStoreOS procd 启动脚本
├── scripts/start.sh          # 通用 Linux 启动脚本
├── docs/                     # 详细文档
└── .gitignore                # 确保凭据永不入库
```

## 安全与隐私

- 面板默认监听 `0.0.0.0:8088`，**请仅在局域网内使用**，不要直接暴露到公网。
- `config.json`、`baidu_cookie.txt` 含你的账号凭据，已被 `.gitignore` 排除；提交前请再次确认 `git status` 中没有它们。
- 本工具调用的是百度网盘**非公开 Web 接口**，接口/签名规则可能随官方改版而变化；若某天搜索或文件夹大小失效，通常是签名常量需要更新（见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md#签名常量)）。
- 请遵守相关服务条款，仅下载你有权获取的内容。

## 已知限制

- 依赖百度网盘 Web 端接口与签名算法，官方调整后需同步更新常量。
- 需要 OpenList 能正常挂载并刷新百度网盘目录，否则取直链可能失败。
- 单批下载的文件数量与体积受网盘转存/接口频率限制，超大批量建议分批。

## 许可证

见 [LICENSE](LICENSE)（默认 MIT，可按需修改）。

---

<details>
<summary>为什么不用 aria2？</summary>

早期版本使用 aria2 下载，但在大文件场景下出现写盘失败。当前版本改用 `curl -s -L -C - -A pan.baidu.com`（流式写入 + 断点续传 + 指定 UA），实测对大文件稳定。

</details>
