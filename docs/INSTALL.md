# 安装指南

ONEFILM 只需 Python 3 和 curl，可以在普通 Linux 主机、NAS、软路由（OpenWrt/iStoreOS）上运行。下面给出两种部署方式。

## 通用准备（所有平台）

### 1. 获取代码

```bash
git clone <your-repo-url> onefilm
cd onefilm
```

### 2. 准备配置文件

```bash
cp config.example.json config.json
```

编辑 `config.json`，至少填写：

- `openlist_base`、`openlist_token`：OpenList 地址和管理员 Token
- `group_id`：你的百度群 ID
- `target_dir`：本地下载保存目录（该目录需有写权限）
- `group_sign_salt`、`dirsize_sk`：签名常量（获取方式见 [CONFIGURATION.md](CONFIGURATION.md#签名常量)）

字段完整说明见 [CONFIGURATION.md](CONFIGURATION.md)。

### 3. 准备百度网盘 Cookie

```bash
cp baidu_cookie.example.txt baidu_cookie.txt
```

把你的百度网盘 Cookie 粘贴进去（获取方式见 [GET_COOKIE.md](GET_COOKIE.md)）。

> `config.json` 和 `baidu_cookie.txt` 都含敏感信息，已被 `.gitignore` 忽略，**不会**被提交到仓库。

### 4. 准备 OpenList

ONEFILM 本身不解析百度网盘直链，而是借助 [OpenList](https://github.com/OpenListTeam/OpenList)（AList 的活跃分支）：

1. 部署并启动 OpenList。
2. 在 OpenList 中添加"百度网盘"存储，使用与 `baidu_cookie.txt` 相同的账号。
3. 确认 OpenList 的 `/api/fs/link` 能拿到直链。
4. 把 OpenList 地址和 Token 填入 `config.json`。

## 方式 A：通用 Linux / NAS / WSL

```bash
# 确认依赖
python3 --version          # 3.8+
which curl                 # 需支持 -C -

# 前台启动（调试用）
sh scripts/start.sh

# 后台启动
nohup sh scripts/start.sh > onefilm.log 2>&1 &

# 打开面板
# http://<设备IP>:8088
```

### systemd 托管（可选）

创建 `/etc/systemd/system/onefilm.service`：

```ini
[Unit]
Description=ONEFILM
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/onefilm
Environment=ONEFILM_CONF=/opt/onefilm/config.json
Environment=ONEFILM_COOKIE=/opt/onefilm/baidu_cookie.txt
Environment=ONEFILM_DATA_DIR=/opt/onefilm/data
Environment=ONEFILM_INDEX=/opt/onefilm/web/index.html
ExecStart=/usr/bin/python3 /opt/onefilm/movie_panel.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

然后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now onefilm
```

## 方式 B：OpenWrt / iStoreOS（软路由）

> 以下假设安装在 `/opt/onefilm`，请确保该目录所在分区有足够空间存放**下载目标目录**（`target_dir` 通常指向挂载的移动硬盘）。

```bash
# 1. 上传代码到 /opt/onefilm（用 scp / git clone 均可）
scp -r onefilm root@<路由器IP>:/opt/onefilm

# 2. 在路由器上配置
cd /opt/onefilm
cp config.example.json config.json
vi config.json
cp baidu_cookie.example.txt baidu_cookie.txt
vi baidu_cookie.txt

# 3. 安装启动脚本
cp /opt/onefilm/init.d/onefilm /etc/init.d/onefilm
chmod +x /etc/init.d/onefilm

# 4. 按实际路径修改脚本内的 APP_DIR（默认 /opt/onefilm）
vi /etc/init.d/onefilm

# 5. 开机自启并启动
/etc/init.d/onefilm enable
/etc/init.d/onefilm start

# 6. 查看状态
/etc/init.d/onefilm status
logread | grep -i onefilm
```

面板地址：`http://<路由器IP>:8088`。

### 关于 OpenList 自动重启

首次取直链失败时，ONEFILM 会尝试重启 OpenList 刷新缓存。默认未启用；如需开启，在配置脚本里设置环境变量：

```sh
export ONEFILM_OL_RESTART="/etc/init.d/openlist restart"
```

或在 init.d 脚本的 `procd_set_param env` 中追加该项。

## 数据目录说明

运行时状态（任务记录、浏览会话、调试日志、curl 日志）默认放在程序目录下的 `data/`，可用 `ONEFILM_DATA_DIR` 指向内存盘（如 `/tmp/onefilm`）以减少闪存写入：

```sh
export ONEFILM_DATA_DIR=/tmp/onefilm
```

## 升级

```bash
cd onefilm
git pull
# 保留你自己的 config.json 和 baidu_cookie.txt，它们不会被覆盖
/etc/init.d/onefilm restart     # 或 systemctl restart onefilm
```

## 卸载

```bash
/etc/init.d/onefilm disable
rm /etc/init.d/onefilm
rm -rf /opt/onefilm
```

（本地已下载的文件不会随程序删除。）
