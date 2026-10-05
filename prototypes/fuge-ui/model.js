(function (root) {
  'use strict';
  function integer(value) {
    return /^\d+$/.test(String(value).trim()) ? Number(value) : NaN;
  }
  function updateInterval(current, side, value, minimum, maximum) {
    const number = integer(value);
    if (!Number.isSafeInteger(number) || number < minimum || number > maximum) return null;
    return side === 'min' ? [number, Math.max(number, current[1])] : [Math.min(number, current[0]), number];
  }
  function selectRange(rows, start, end, limit) {
    start = integer(start);
    end = integer(end);
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 1 || end < start || end > rows.length) {
      return {indexes: [], error: `请输入 1–${rows.length || 1} 内的有效区间，结束序号不能小于起始序号。`};
    }
    const indexes = rows.map((row, index) => index).filter(index => index >= start - 1 && index < end && rows[index].valid);
    if (!indexes.length) return {indexes: [], error: '这个区间没有有效记录，原选择已保留。'};
    if (indexes.length > limit) return {indexes: [], error: `区间内有 ${indexes.length} 条有效记录，超过本批上限 ${limit} 条，原选择已保留。`};
    return {indexes, error: ''};
  }
  function formatElapsed(ms) {
    const seconds = Math.max(0, Math.floor(ms / 1000));
    return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60].map(value => String(value).padStart(2, '0')).join(':');
  }
  class TaskClock {
    constructor(now = () => performance.now()) { this.now = now; this.accumulated = 0; this.since = null; }
    start() { this.accumulated = 0; this.since = this.now(); }
    elapsed() { return this.accumulated + (this.since === null ? 0 : Math.max(0, this.now() - this.since)); }
    pause() { if (this.since !== null) { this.accumulated = this.elapsed(); this.since = null; } }
    resume() { if (this.since === null) this.since = this.now(); }
    stop() { this.pause(); }
  }
  const surnames = ['林', '陈', '许', '沈', '周', '唐', '叶', '夏', '顾', '江'];
  const given = ['晓禾', '予安', '知远', '若宁', '星言', '书言', '可晴', '子墨', '嘉宁', '一诺'];
  function makeFriends(count = 200) {
    return Array.from({length: count}, (_, index) => {
      const invalid = (index + 1) % 31 === 0;
      return {
        id: `friend-${index + 1}`, source: index + 2, name: surnames[index % 10] + given[Math.floor(index / 10) % 10],
        account: invalid ? '' : `wxid_demo_${String(index + 1).padStart(4, '0')}`,
        suffix: '使用全局', greeting: index % 7 === 0 ? '你好，很高兴认识你。' : '',
        valid: !invalid, error: invalid ? '账号为空' : '', selected: false, status: invalid ? '待修正' : '待选择'
      };
    });
  }
  function makeContacts() {
    return Array.from({length: 86}, (_, index) => ({
      id: index + 1, nickname: surnames[index % 10] + given[Math.floor(index / 10) % 10],
      remark: ['产品设计', '课程顾问', '新联系人', '项目协作', ''][index % 5],
      phone: '', wechatId: `wxid_demo_contact_${String(index + 1).padStart(3, '0')}`,
      account: `demo_contact_${String(index + 1).padStart(3, '0')}`,
      description: ['设计交流', '秋季课程咨询', '', '周末活动', '资料分享'][index % 5],
      type: index < 72 ? 'friend' : ['group', 'official', 'system'][index % 3]
    }));
  }
  const api = {integer, updateInterval, selectRange, formatElapsed, TaskClock, makeFriends, makeContacts};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FugePrototypeModel = api;
})(globalThis);
