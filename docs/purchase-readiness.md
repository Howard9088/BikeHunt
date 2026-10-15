# 注册前购买条件与转运费用参考

核对日期：2026-10-15。仅公开官方网页及官方搜索索引；没有注册、登录、填入个人资料、绑卡、支付或创建转运账户。

## 展示与边界

- `web/purchase-readiness.json` 保存有来源、日期和适用范围的政策快照；`web/purchase-readiness.js` 只渲染说明，不更新报价、库存、购买资格或费用引擎。
- 摘要出现在商品报价/历史商品页出口的注册图解前、商家操作图解内的注册步骤前，以及 Amazon 四个国家卡片内。
- 严格按 `sourceCode` 匹配；Amazon 进一步按准确的 `salesRegion` 匹配，报价 URL 存在时还必须属于该商店域名。品牌官网政策不会映射到销售该品牌的零售商。
- Visma、MAAP 的商店通用规则注明范围。POC 当前资料来自 Global EN 条款；别的报价市场仅显示带范围的参考，不标成该市场的已核实支付方式。
- 中国发行卡状态与卡组织列表分开。现有研究没有确认当前中国发行卡成功交易。资料里的支付方式不等于逐卡批准，钱包不能保证底层卡获批。
- Amazon DE/JP 支付方式只有历史官方证据，明确标为历史参考、当前待重新核实。Amazon US 支付方式依据官方员工 2025-11-18 回复；直邮和转运未完成核验。
- 日期是阅读公开资料的时间，不是保证规则至今不变的期限。报价规则被标记变更时，摘要降级为待复核。

## 配送与费用

- Visma 官网公布寄中国运费为 EUR 47.95，独立于商品标价币种。没有用 USD 报价推导 USD 运费，没有把运费解释为税费齐全的总价。
- MAAP 官网不向中国配送；没有核实转运许可，提示通过官方确认本地渠道。
- POC Global EN 明确拒绝 re-shippers / package forwarding services。没有推荐转运绕过商家限制。
- 未知运费、税费、清关、银行卡费用不是零；摘要不生成到手总价。

## 转运说明

Amazon 页面底部提供可选的一般知识，不把任何当前商品推荐给转运商。先核实商家和承运许可，再考虑使用。

官方费用计算器（2026-10-15 只读核对）：

- MyUS：https://www.myus.com/pricing/calculate-shipping/
- forward2me：https://www.forward2me.com/pricing/
- tenso.com：https://www.tenso.com/en/estimate （由官方 FAQ https://faq.tenso.com/articles/en_US/FAQ/q147en/?fs=Search&l=en_US&pn=1 确认入口）

费用清单包含商家至仓库运费、实重/体积重、处理/合箱/重包装、燃油等附加费、保险、仓储、退件、税及清关和银行卡费用。MyUS Premium 的试用后 US$9.99/月自动续费醒目标出。没有编造某个包裹最终报价，也没有复用旧 CNY 1000 提示作为现行中国法律。必须真实申报。

所有新外链是允许列表中的官方资料或计算器链接；点击前保留现有免责声明，取消留在本站，同标签页返回恢复浏览。页面不自动访问这些网站，不含账号、卡号、地址或结账表单。

## 验证

- Node：`node scripts/test_purchase_readiness.js`，含商店/市场隔离、URL 篡改、修饰键/中键、取消/继续、禁止转运、历史证据、未知费用与缺数据降级。
- Python：`python -m unittest discover -s tests -p 'test_*.py'`，新增数据与发布资产断言。
- CI 桌面/手机：`python scripts/test_purchase_readiness_ui.py`，所有外站请求使用本地夹具；检查摘要顺序、可读性、滚动/溢出、焦点、返回与只读边界。
- 当前执行器的 Chromium 已知不可用，本次没有重试本地浏览器；桌面/手机视觉验证待 CI 实际执行，不据脚本编译成功声称通过。
