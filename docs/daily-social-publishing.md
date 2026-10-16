# 每日好价发布与访问计数

## 已确认的产品规则

北京时间每天 18:00 汇总最多一篇小红书图文，只包含已核实的新降价或从缺货恢复为有货的商品。首次发现、普通价格刷新、过期报价、库存未知、采集失败和恢复的历史消息不触发发布。原有网页结构、GitHub Pages 托管和采集工作流保持不变。

`PromotionPreparer` 继续只生成本地证据包；`DailyPublisher` 增加独立发布台账，浏览器操作由本地定时任务执行。源账号只在本地 `storage/social/config.json` 保存，不读取或导出浏览器登录凭据。

## 执行步骤

1. 使用已安装的项目 Python，先运行 `scripts/collect_offers.py` 刷新现有源；失败源仍隔离。再运行 `scripts/publish_xhs.py prepare` 复核队列。无新变化时不发布、不上传图片。
2. 18:00–18:59 运行 `scripts/publish_xhs.py reserve`，取得 `job_id` 和本地 `storage/social/candidate.json`、`note.txt`、`cover.png`。最多选三个商品组，保留原币商品价、配色、实际尺码、来源市场及核实时点；运费税费未包含。
3. 用 Chrome 的小红书官方创作平台确认当前账号与本地配置一致，在新建图文中上传封面并填入标题正文。查看实际预览并核对文字，再运行 `scripts/publish_xhs.py begin --job JOB_ID`。只有返回 `attempting` 才点击一次最终发布。出现验证码、登录过期或账号不符时停止并通知用户。
4. 从发布成功页或笔记管理页读取真实笔记 ID 和链接，运行 `scripts/publish_xhs.py receipt --job JOB_ID --note-id NOTE_ID --note-url NOTE_URL`。若结果不明确，执行 `unknown --job JOB_ID`；查看真实笔记状态后才能处理，不能自动重发。

SQLite 在提交前写入状态并占用本日名额，已提交但无回执的任务会阻止后续发布。账号、同日和商品组都有去重约束。失败不能通过清空台账绕过。首次启动只建立基线，不补发旧消息。定时任务依赖本机开机、Codex 运行及 Chrome 登录态；后台浏览器断开时保留队列并报告。

安装本地图片渲染依赖：`python -m pip install -r requirements-social.txt`。封面由公开事实排版生成，不下载商品图片，不上传证据 JSON、原始页面、数据库或配置。`storage/` 已在 `.gitignore` 中且不进入 Pages。

## 底部累计访问次数

在原有底部高度内显示当前网页的累计访问次数与本次统计时间。使用 [不蒜子兼容服务](https://busuanzi.9420.ltd/) 的公开接口 `https://bsz.iirose.cn/api`，通过本地 JS 适配，不加载远程脚本。原版域名在本机不可达，另一镜像请求超时，因此选用已实测返回真实计数且支持 CORS 的兼容服务。

只传固定的公开首页 `https://howard9088.github.io/BikeHunt/`，不传筛选条件、身高体重、页面查询参数、账号、原始来源网址或 Cookie。不使用跨项目的域名总数冒充 BikeHunt 访问量，不把累计访问次数称为独立人数。每次线上页面加载计数一次，不定时轮询加数；本地预览和 Mock 测试不请求计数服务。刷新会产生新的访问，计数从接入时开始，不回填历史访问量。超时或响应异常显示“访问统计暂不可用”。

## 当前新增采集范围

- Lidl–Trek：Santini 官方车队系列，最多 25 件商品，逐变体与商品页核对。
- Alpecin：车队官网链接的 Topfanz 三款骑行袜，动态实际切换尺码，核对表单变体 ID、独立 GTIN、含税显示价和库存数。未税与含税差额不算折扣。
- 红牛：官方日本市场车队分类首页最多 24 件，按商品与当前配色解码公开匿名缓存，核对 JSON-LD 的默认 SKU 与市场价。保留逐尺码独立 SKU 和库存数，预售不作现货。默认 SKU 的 GTIN 不复制到其他尺码。
- Fizik：采用官网实际重定向后的 Sale Shoes 系列地址；当前本机采集 16 件商品、368 条鞋码报价，实际为 JP 市场、EUR 报价，不把旧地址中的 en-us 当成美国市场证据。

范围上限与失败记录均进入采集状态；不能把样本标成全目录已覆盖。EKOI 的实际请求被官方转到日本分销说明；说明中的 SHIFTA 合作站 robots 返回 HTML，权限未核实。Kalas 返回 403，POC 返回 429，均不绕过且不虚构剩余尺码。
