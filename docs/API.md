# API 参考

ONEFILM 后端是一个标准库实现的 HTTP 服务，前端通过这些 JSON 接口与之通信。默认端口 `8088`。所有响应均为 `application/json; charset=utf-8`。

## GET `/api/info`

返回用于前端展示的基本信息。

**响应**

```json
{
  "target_dir": "/mnt/disk/Movies",
  "library_baidu_path": "/_电影库"
}
```

## GET `/api/search?kw=关键词`

调用百度群文件库的实时搜索。

**参数**
- `kw`：搜索关键词。

**响应**

```json
{
  "items": [
    {
      "name": "花样年华",
      "path": "/.../花样年华",
      "isdir": true,
      "size": 123456789,
      "fs_id": "123456",
      "msgId": "msg-xxx",
      "uk": "123456789",
      "source": "某用户",
      "ctime": 1700000000
    }
  ],
  "kw": "花样年华",
  "source": "group",
  "hint": "群文件库实时搜索，共 1 条"
}
```

`msgId` 与 `uk` 是后续转存所需的群文件凭证。

## GET `/api/list?path=&browse_id=`

列目录。

**参数**
- `path`：要列出的网盘路径。
- `browse_id`（可选）：只读浏览会话 ID。传入时走群分享接口列出子项，**不产生临时转存副本**；不传时直接列自己网盘里的目录。

**响应**：`{"items": [ ... ]}`，每项含 `name/path/isdir/size/fs_id`。

## GET `/api/folder_videos?path=`

列出指定文件夹内的所有视频文件（按扩展名过滤）。

**响应**：`{"items": [...]}`。

## POST `/api/dirsize`

批量查询文件夹大小。

**请求体**

```json
{"items": [{"fs_id": "123", "uk": "456"}, ...]}
```

**响应**

```json
{"sizes": {"123": 987654321}}
```

单位：字节。结果在服务端内存中缓存。

## POST `/api/browse`

为某个群文件夹创建只读浏览会话（只列出子项，不转存）。

**请求体**：`{"item": { ...搜索结果中的一项... }}`

**响应**

```json
{
  "browse_id": "20261120230000-abc12",
  "root": { "path": "...", "name": "...", "isdir": true, "fs_id": "...", "msgId": "...", "uk": "..." }
}
```

## POST `/api/browse_close`

关闭浏览会话。

**请求体**：`{"browse_id": "...", "force": false}`

**响应**：`{"ok": true}`

## POST `/api/download`

提交下载任务。**立即返回**（占位任务），真正的转存/取链/下载在后台线程进行。

**请求体**

```json
{
  "items": [
    {"name": "花样年华", "path": "...", "isdir": true, "fs_id": "...", "msgId": "...", "uk": "..."}
  ]
}
```

也兼容 `{"paths": ["..."]}` 形式（用于自己网盘里的路径）。

**响应**

```json
{
  "gids": ["prep-20261120-230000-0"],
  "errors": [],
  "batch": "20261120-230000-a1b2",
  "dir": "/mnt/disk/Movies",
  "preparing": true
}
```

前端随后轮询 `/api/status` 获取真实任务。

## GET `/api/status`

查询所有任务进度。

**响应**

```json
{
  "tasks": [
    {
      "gid": "abc123",
      "name": "花样年华.mp4",
      "status": "downloading",
      "completed": 104857600,
      "total": 1048576000,
      "speed": 5242880,
      "error": 0,
      "err_msg": "",
      "retries": 0,
      "batch": "20261120-230000-a1b2",
      "cleanup": ""
    }
  ]
}
```

`status` 取值：`preparing`（准备中）、空/`downloading`（下载中）、`complete`、`done`、`failed`。`cleanup` 表示临时副本清理状态（`done`/`failed:...`/`kept-failed`）。

## POST `/api/task_delete`

删除单条任务记录。只移除记录并终止对应下载进程，**不删除本地文件，也不删除网盘文件**。

**请求体**：`{"gid": "abc123"}`

**响应**：`{"ok": true, "deleted": true}`

## POST `/api/task_clear_done`

清空所有已完成/失败的任务记录。

**请求体**：空。

**响应**：`{"ok": true, "count": 3}`

## 兼容端点

- `GET /`：返回前端页面 `web/index.html`（带禁止缓存头）。
- `POST /api/login` / `POST /api/logout`：为兼容旧版缓存页面保留，恒返回 `{"ok": true}`。当前版本无登录密码。
