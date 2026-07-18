# 安全说明

## 凭据状态

当前 Git 跟踪文件已通过 `scripts/secret_scan.py`，但旧提交历史曾包含 API Key、URL 口令和 JWT 私钥。删除工作树文件不能使旧凭据失效。

必须执行：

1. 在各服务提供方吊销并重新生成所有暴露过的凭据。
2. 将新凭据放入企业 Secret Manager、Docker/Kubernetes Secret 或本机 `.env`，不得提交到 Git。
3. 通知协作者暂停推送并备份必要分支。
4. 使用 `git filter-repo` 或 BFG 清洗指定历史对象，经人工复核后 force push。
5. 要求所有协作者重新克隆；检查 GitHub fork、Actions artifact、release 和缓存。

历史重写会改变提交 ID，并影响所有协作者。本仓库不会在普通代码变更中自动执行该破坏性操作。

## 认证约束

- 生产必须设置 `APP_ENV=production`。
- 生产禁止 `AUTH_MODE=development`，并拒绝 SQLite。
- 推荐 `AUTH_MODE=oidc`，校验 issuer、audience、签名、`exp`、`iat`、`sub`、`tenant_id`。
- JWT 私钥只属于 IdP/签发服务；API、Worker 和 MCP 只配置公钥或 JWKS。
- 前端令牌只保存在内存；刷新页面后重新走 IdP 流程。

## 数据边界

- 客户端不能指定 tenant、owner 或服务器文件路径。
- 检索必须提供 tenant 和 user，上游缺失时直接失败。
- ACL 之外仍执行 owner 分支；返回结果再次做租户和 ACL 过滤。
- 上传文件限制数量、大小、扩展名和签名；生产仍应在 ingress 或独立扫描服务接入恶意文件扫描。

## 报告漏洞

报告应包含复现条件、影响范围和建议修复，不要在公共 Issue 提交真实凭据、客户数据或完整攻击载荷。

