# hidencloud-QD(测试中。。。4月20日手动运行测试效果)

脚本需要登录信息，你必须在 GitHub 仓库配置 Secrets：

路径：  
`Settings` → `Secrets and variables` → `Actions` → `New repository secret`

添加以下内容：

| Secret 名称 | 说明 |
|------------|------|
| `HIDENCLOUD_COOKIE` | 登录 Cookie（推荐方式） |
| `HIDENCLOUD_EMAIL` | 账号邮箱（可选） |
| `HIDENCLOUD_PASSWORD` | 账号密码（可选） |
| `TG_BOT_TOKEN` | 机器人 Token（可选） |
| `TG_CHAT_ID` | 用户 ID（可选） |
### 🔧 注意：
如果你使用 **Cookie 登录**，可以只填写 `HIDENCLOUD_COOKIE`，并在代码里关闭账号密码登录逻辑。

如果你使用 **邮箱密码登录**，可以不填 Cookie。

0 2 * * *

 **每天 UTC 时间 02:00 自动运行一次**
- 如果你的时区是 **UTC+8**（北京 / 新加坡 / 马来西亚等）
  则执行时间为 **每天早上 10 点**


| 想要的执行时间 | cron 写法 | 说明 |
|----------------|-----------|------|
| 每 6 小时运行一次（最稳） | `0 */6 * * *` | 推荐设置 |
| 每天凌晨 1 点 | `0 1 * * *` | 提前续期 |
| 每天中午 12 点 | `0 12 * * *` | 自定义 |
| 每小时运行一次 | `0 * * * *` | 最高频率 |

