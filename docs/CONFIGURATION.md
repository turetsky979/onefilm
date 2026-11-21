# 配置说明

ONEFILM 有两处需要你填写：`config.json`（配置项）和 `baidu_cookie.txt`（百度网盘 Cookie）。两者都被 `.gitignore` 排除，不会入库。

## config.json

从 `config.example.json` 复制而来。字段如下：

| 字段 | 必填 | 说明 |
|---|---|---|
| `openlist_base` | 是 | OpenList 服务地址，如 `http://127.0.0.1:5244` |
| `openlist_token` | 是 | OpenList 管理 Token（登录后可在设置里看到，形如 `openlist-xxx`） |
| `library_baidu_path` | 是 | 你网盘里已存在的素材库目录，转存副本会落到这里，如 `/_电影库` |
| `library_root` | 否 | 该目录在 OpenList 中的映射路径（如 `/1/_电影库`），仅作说明用途 |
| `group_id` | 是 | 百度群 ID。ONEFILM 搜索的是这个群的文件库 |
| `target_dir` | 是 | 本地下载保存目录，需有写权限 |
| `port` | 否 | 面板端口，默认 `8088` |
| `group_sign_salt` | 是 | 群搜索接口的签名盐，见下文 |
| `dirsize_sk` | 是 | 文件夹大小接口的签名 key，见下文 |

一个填好的例子（**值为占位，请勿照抄**）：

```json
{
  "openlist_base": "http://127.0.0.1:5244",
  "openlist_token": "openlist-你的token",
  "library_baidu_path": "/_电影库",
  "library_root": "/1/_电影库",
  "group_id": "你的群ID",
  "target_dir": "/mnt/disk/Movies",
  "port": 8088,
  "group_sign_salt": "你的签名盐",
  "dirsize_sk": "你的dirsize key"
}
```

## baidu_cookie.txt

仅一行：你的百度网盘 Web Cookie。获取步骤见 [GET_COOKIE.md](GET_COOKIE.md)。

ONEFILM 启动时会读取它，并从百度接口换取 `bdstoken` 和 `uk`。Cookie 失效后需重新粘贴并重启服务。

## 签名常量

ONEFILM 调用的是百度网盘 Web 端使用的接口，其中两个接口需要签名：

- **群文件库搜索**（`basembox/group/search`）：签名算法为
  `md5(salt + "_" + group_id + 关键词)`，再 URL 编码后 Base64。
- **文件夹大小**（`sharedir/file/dirsize`）：用 `dirsize_sk` 参与 MD5 签名。

这两个常量来自百度网盘 Web 前端的 JavaScript，**不是**你的账号凭据。它们可能随百度改版而变化，因此需要你在配置里自行填写、便于更新。

### 如何获取

1. 用 Chrome/Edge 打开并登录 [pan.baidu.com](https://pan.baidu.com/)。
2. `F12` 打开开发者工具 → `Sources` → 搜索关键字 `group/search` 或 `dirsize`，找到构造请求签名的代码。
3. 在对应的 JS 里定位拼接签名的字符串常量（通常是一段 32 位十六进制串）。
4. 把群搜索用的常量填入 `group_sign_salt`，目录大小用的填入 `dirsize_sk`。

> 更简单的方式：在浏览器里执行一次对应操作（搜索群文件 / 查看文件夹大小），在 Network 面板查看请求参数 `sign`，结合请求参数逆向出盐值。若你已有可用值，直接填入即可。

如果搜索正常但文件夹大小显示 `0`，多半是 `dirsize_sk` 过期；如果搜索报错，检查 `group_sign_salt` 和 `group_id`。

## 环境变量

所有路径类设置都可以用环境变量覆盖（**优先级高于配置文件**），方便多实例部署或把状态放到内存盘：

| 环境变量 | 含义 | 默认值 |
|---|---|---|
| `ONEFILM_CONF` | 配置文件路径 | `<程序目录>/config.json` |
| `ONEFILM_COOKIE` | Cookie 文件路径 | `<程序目录>/baidu_cookie.txt` |
| `ONEFILM_DATA_DIR` | 运行时数据目录 | `<程序目录>/data` |
| `ONEFILM_INDEX` | 前端页面路径 | `<程序目录>/web/index.html` |
| `ONEFILM_DEBUG_LOG` | 转存诊断日志路径 | `<data>/transfer-debug.log` |
| `ONEFILM_CURL` | curl 可执行文件路径 | `/usr/bin/curl` |
| `ONEFILM_OL_RESTART` | 取直链失败时重启 OpenList 的命令 | 空（不重启） |

例如把状态放到内存盘、使用自定义 curl：

```bash
export ONEFILM_DATA_DIR=/tmp/onefilm
export ONEFILM_CURL=/usr/local/bin/curl
sh scripts/start.sh
```

## 端口与访问

面板监听 `0.0.0.0:<port>`，**设计仅用于局域网**。如需修改端口，改 `config.json` 的 `port` 并重启服务。不要在公网上直接暴露此端口。
