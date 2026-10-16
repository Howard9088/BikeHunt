/* Approved page-view counter. Send only the canonical public project URL. */
(function (root) {
  'use strict';
  const PAGE = 'https://howard9088.github.io/BikeHunt/';
  async function readVisits(fetcher, signal) {
    const response = await fetcher('https://bsz.iirose.cn/api', {
      method: 'POST', headers: {'x-bsz-referer': PAGE},
      credentials: 'omit', referrerPolicy: 'no-referrer', signal
    });
    if (!response.ok) throw new Error('Counter unavailable');
    const data = await response.json();
    if (data.success !== true || !data.data) throw new Error('Counter unavailable');
    const raw = data.data.page_pv;
    if (!(typeof raw === 'number' || (typeof raw === 'string' && /^\d+$/.test(raw))))
      throw new Error('Invalid page count');
    const count = Number(raw);
    if (!Number.isSafeInteger(count) || count < 0) throw new Error('Invalid page count');
    return {pageViews: count, checkedAt: new Date()};
  }
  async function start(doc, location, fetcher) {
    const target = doc.getElementById('visitorStats');
    if (!target || target.dataset.started) return;
    target.dataset.started = 'true';
    if (location.hostname !== 'howard9088.github.io' ||
        !/^\/BikeHunt\/(?:index\.html)?$/.test(location.pathname)) {
      target.textContent = '访问统计仅在线上显示';
      return;
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const stats = await readVisits(fetcher, controller.signal);
      const time = stats.checkedAt.toLocaleTimeString('zh-CN', {hour12: false, hour:'2-digit', minute:'2-digit'});
      target.textContent = '访问 ' + stats.pageViews.toLocaleString('zh-CN') + ' 次 · 更新 ' + time;
      target.title = '本网页累计访问次数（不蒜子兼容服务）；统计于 ' + stats.checkedAt.toLocaleString('zh-CN');
      target.dataset.state = 'ready';
    } catch (_) {
      target.textContent = '访问统计暂不可用';
      target.dataset.state = 'unavailable';
    } finally { clearTimeout(timeout); }
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {readVisits, start};
  if (root.document) start(root.document, root.location, root.fetch.bind(root));
})(typeof window !== 'undefined' ? window : globalThis);
