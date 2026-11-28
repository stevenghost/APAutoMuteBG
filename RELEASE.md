# 发布流程与 Token 说明

> 本文件只记录流程和公开的模板链接，**不包含任何 token 明文**。

## PAT 生成链接（需要重新生成 token 时点这里）

### Fine-grained（推荐，权限最小）

```
https://github.com/settings/personal-access-tokens/new?name=APAutoMuteBG+release&description=Push+code+and+publish+releases&target_name=stevenghost&expires_in=7&contents=write
```

打开后需要手动完成的一步：**Repository access → Only select repositories → 勾选 `APAutoMuteBG`**（GitHub 的模板 URL 不支持预填仓库）。

需要的权限：**Contents: Read and write**（代码推送 + Release 发布都够用，Metadata 会自动带上只读）。

### Classic（备选，权限更大）

```
https://github.com/settings/tokens/new?description=APAutoMuteBG+release&scopes=repo
```

## Token 存放位置（仅本机，已被 .gitignore 忽略）

```
tools/AutoMuteBG/gh_token.txt
```

- 不要提交、不要打包进 Release 压缩包；
- 用完不需要立刻删，等它过期即可；
- 过期后 API 会返回 401，届时重新用上面的链接生成一个，覆盖该文件。

## 发布新版本步骤

```powershell
cd F:\java\DSH\tools\AutoMuteBG
.\build.ps1                 # PyInstaller 构建 + 自签名
```

1. 把 `dist\background_muter\` 打成 zip（**排除** `config.yaml`、`logs\`、`process_name.txt`，用 `resource\default_config.yaml` 代替）；
2. 通过 GitHub API 创建 Release 并上传附件：
   - `POST https://api.github.com/repos/stevenghost/APAutoMuteBG/releases`
   - `POST https://uploads.github.com/repos/stevenghost/APAutoMuteBG/releases/{id}/assets?name=...`
   - Header：`Authorization: Bearer <token>`、`Accept: application/vnd.github+json`；
3. 版本号规则：`v<major>.<minor>.<patch>`，每次发布 patch +1（例如 v1.0.1 → v1.0.2）。

> 注意：本机 PowerShell 的 `Invoke-RestMethod` 直连 api.github.com 会因 schannel 报 SSL 错误；Git 推送需要 `-c http.sslBackend=openssl`。API 调用可用 Python（urllib）完成，参考 `tools/temp/make_release.py`。

## 已发布版本

| 版本 | 日期 | 说明 |
| --- | --- | --- |
| v1.0.1 | 2026-11-27 | 首次发布：后台静音 + 蓝原剧情跳过 |
| v1.0.2 | 2026-11-28 | 内存优化、F12 暂停、托盘开关、遮罩改进 |

