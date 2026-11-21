# 获取百度网盘 Cookie

ONEFILM 需要你的百度网盘 Web Cookie 来调用搜索、转存、列目录等接口。请按下面步骤获取。

## 步骤

### 1. 登录网页版

用 Chrome 或 Edge 打开 [https://pan.baidu.com/](https://pan.baidu.com/) 并登录你的账号。

### 2. 打开开发者工具

按 `F12`（或 `Ctrl+Shift+I`）打开开发者工具，切到 **Network（网络）** 面板。

### 3. 触发一个网络请求

刷新页面，或随便点开一个文件夹，让页面发出请求。在请求列表里找任意一个发往 `pan.baidu.com` 的请求（例如 `api/list`）。

### 4. 复制 Cookie

- 点开该请求 → **Headers（标头）** → 找到 **Request Headers** 里的 `Cookie` 一项。
- 把它的**完整值**复制下来（通常很长，包含 `BDUSS=...`、`STOKEN=...`、`BAIDUID=...` 等字段）。

### 5. 写入文件

```bash
cd onefilm
vi baidu_cookie.txt
```

把刚才复制的完整 Cookie 粘贴成一行，保存。

> 只需要 Cookie 的原始值本身，不要加 `Cookie:` 前缀，也不要带引号。

### 6. 重启 ONEFILM

```bash
/etc/init.d/onefilm restart     # OpenWrt
# 或
systemctl restart onefilm       # systemd
```

启动后 ONEFILM 会自动用该 Cookie 换取 `bdstoken` 和 `uk`。打开面板搜索一次，若能返回结果说明 Cookie 有效。

## Cookie 失效

百度 Cookie 有有效期。若某天搜索返回登录相关错误（如 errno 非 0），多半是 Cookie 过期，重复上述步骤更新 `baidu_cookie.txt` 并重启即可。

## 安全提示

- `baidu_cookie.txt` 等同于你账号的登录凭据，**不要**分享、不要提交到 Git、不要发给他人。
- 该文件已加入 `.gitignore`，正常 `git add .` 不会把它纳入版本控制。提交前可用 `git status` 再确认一遍。
- 如果你怀疑 Cookie 曾泄露，请到百度网盘安全中心退出所有设备并重新登录，使旧 Cookie 失效。
