# 商家注册真实截图维护

## 当前首批与边界

- 真实图片：Visma 英文公开账户页三张，页面核对日期 2026-10-15。原图不改像素，网页叠加编号框，图下显示完整中文解释。
- 这些页面未选择国家、未显示币种，使用独立的 `public_account` 范围。不能称为 US 商店账户截图，也不能证明任何地区的注册、登录或结账成功。
- Visma 当前报价的 `sales_region` 为 `US 市场报价（USD）`，这一精确市场图解仍显示待核实。公开账户图解是另一个明确标注的可选部分，不替代该市场证据。
- Amazon 美国、英国、德国、日本站分别登记。本次云端各站未能打开页面，没有可用注册截图；不猜测 HTTP 状态、不用其他站截图补齐。
- Decathlon CMA CGM 车队商城账户页尚待核实。`account.decathlon.com` 的零售英国账户不是已证明相通的车队账户，截图未纳入发布。
- 不登录、不提交注册、不填写任何个人资料或勾选条款，不用合成示意图充当真实商家页面。

## 配置与文件

- 配置：`web/registration-guides.json`，顶层 `schemaVersion: 1`、`revision`、`entries`。
- 原图：`web/assets/registration/`。每次更换图片使用新的带日期／版本文件名。
- 浏览器：`web/registration-guides.js` 校验来源和字段，只读取本站 JSON 与本站图片，不自动请求商家网站。
- 构建：`app/registration_guides.py` 校验配置，只复制 `verified` 条目引用的真实图片与 JSON。未引用的文件、停用的旧图不复制。

每条 entry 包含：

| 字段 | 含义 |
|---|---|
| sourceCode | 精确的报价 `source_code`，例如 `visma` 或 `amazon_uk` |
| scope | `market` 或 `public_account` |
| salesRegion | `market` 必须精确匹配报价 `sales_region`；`public_account` 必须是 null |
| marketLabel | 人可读适用范围，不能用界面语言推断市场 |
| revision | 此商家／范围的图解版本，页面变化后更新 |
| status | `verified`、`unverified` 或 `needs_review` |
| reviewReason | 非 verified 状态必填；说明真实限制，不猜失败原因 |
| checkedAt | 可选的资料核对日期或带时区时间 |
| frames | 截图数组；verified 至少一张，其他状态可以为空 |

每张 frame 包含 `id`、`asset`、`sourceUrl`、`verifiedAt`、`viewport: {width, height}`、`caption`、`alt`、`screenshotKind: "real"` 与 `annotations`。每条标注包含中文 `label`、`description` 和 `x/y/width/height`，四个数值都是相对于完整截图的百分比，矩形不能越界。页面有滚动时，坐标仍按所保存的那张图计算。

日期可以是确知的 YYYY-MM-DD；确有精确时间时才写带时区 ISO 时间。不可补造秒数，不可使用未来日期。日期记录观察时间，不代表页面保证有效到某天；不设置猜测的到期时间。

## 精确市场与安全

- 配置键是 `[sourceCode, scope, salesRegion]`。不按语言、货币、国家名子串、URL 前缀或其他商家的图解猜测匹配。
- Amazon 搜索卡的固定市场身份分别为 `amazon_us / 美国站`、`amazon_uk / 英国站`、`amazon_de / 德国站`、`amazon_jp / 日本站`。
- Shopify 当前采集到的市场可能与来源登记的默认地区不同。复制当前报价实际 `sales_region`，不能只读 `data/sources.json` 的默认值。
- public_account 图片只放进独立的“公开账户页图解（销售市场未核实）”部分。精确市场区继续保留缺失状态。
- `asset` 只接受 `assets/registration/` 下单层小写英文字母、数字、短横线、下划线文件名，格式限 PNG/JPG/JPEG/WebP。外链、SVG、查询参数、路径穿越、越界软链接均拒绝。
- `sourceUrl` 必须是代码中该商家的明确 HTTPS 主机，不带用户信息、端口、查询参数或片段。当前仅支持稳定的公开来源 URL；若实际页面只能通过带鉴权参数的 URL 访问，不应伪造／擅自删参数作为来源，应先审核新的来源记录方式。
- 新主机要先确认是此商家的相关账户服务，再同时修改 Python 和浏览器的主机白名单。相同品牌名不证明账户互通。

## 更换、停用与验证

1. 在不提交表单的情况下，查看公开页面并截取真实图，检查没有姓名、邮箱、订单、账户状态等个人资料。
2. 记录实际页面、市场或公开账户范围、日期、视口，并确认中文标注确实指向截图中的位置。
3. 使用新版本文件名替换对应配置，更新条目及顶层 revision。不要让旧标注继续贴在新的布局上。
4. 页面已变化但新图未核实时，将 status 改成 `needs_review`，写 reviewReason。旧 frames 可保留作为维护元数据，旧图片不会发布或显示；也可清空 frames／删除条目。
5. 运行下面的普通验证。全部图片停用／删除仍应允许正常安全发布，不能因“必须有截图”阻止撤下误导信息。

```sh
PYTHONPATH=/workspace/shared/bikehunt-deps python -m unittest discover -s tests -p 'test_*.py'
node scripts/test_registration_guides.js
python scripts/verify_registration_guides.py
PYTHONPATH=/workspace/shared/bikehunt-deps python scripts/build_pages.py
python scripts/verify_registration_guides.py --root _site
```

只有此次“首次真实截图上线”验收额外运行 `python scripts/verify_registration_guides.py --require-screenshots`。该参数不在持续部署门槛中，避免以后安全撤图被阻挡。

有可用浏览器环境时再运行 `python scripts/test_registration_guides_ui.py` 与既有 `scripts/test_merchant_guides_ui.py`。新 UI 回归使用明确的测试数据与本地测试图片，覆盖桌面、390px 手机、320px 小屏、键盘展开／收起、原地帮助、Back/Close、停用／加载失败撤图和 Amazon 四站隔离；它不声称访问过真实商家或完成注册。真实图片仍需另行人工像素核对。
