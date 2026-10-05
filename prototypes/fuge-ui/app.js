(() => {
  'use strict';
  const M = window.FugePrototypeModel;
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[character]));
  const icon = name => `<i data-lucide="${name}" aria-hidden="true"></i>`;
  const icons = () => window.lucide.createIcons({attrs: {'aria-hidden': 'true', 'stroke-width': 1.8}});
  const defaults = {theme: 'light', collapsed: false, messageInterval: [2,3], friendInterval: [15,30], batchLimit: 100, fuzzy: false, greeting: '你好，我是五阿哥，方便认识一下吗？', suffix: '新联系人', unknownPolicy: 'continue', safeRetries: true, recoveryPolicy: 'confirm', loginTimeout: 90, glass: true, opacity: 80};
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('fuge-ui-preview-v1') || '{}'); } catch (_) { /* Browser storage is optional. */ }
  const prefs = {...defaults, ...saved};
  if (!['light', 'dark'].includes(prefs.theme)) prefs.theme = 'light';
  if (!Number.isInteger(prefs.batchLimit) || prefs.batchLimit < 1 || prefs.batchLimit > 1000) prefs.batchLimit = 100;
  for (const key of ['messageInterval', 'friendInterval']) {
    if (!Array.isArray(prefs[key]) || prefs[key].length !== 2 || prefs[key].some(value => !Number.isInteger(value) || value < 1 || value > 300) || prefs[key][0] > prefs[key][1]) prefs[key] = [...defaults[key]];
  }
  let workspace = 'message';
  let settingsSection = 'message';
  let friends = M.makeFriends();
  let currentFriend = -1;
  let invalidOnly = false;
  let contacts = M.makeContacts();
  let contactSort = {field: 'nickname', direction: 1};
  let currentContact = null;
  let previewIndex = 0;
  let contactRead = null;
  let task = null;
  let confirmation = null;
  let contextTarget = null;
  let clipboardFallback = '';
  let menuActions = [];
  let tooltipTimer = null;
  const histories = new WeakMap();
  const suffixes = ['新联系人', '同学', '老师', '先生', '女士', '朋友', '无'];
  const attachments = [
    {name: '福格品牌标识.png', size: 18240, type: 'image/png', url: 'assets/fuge-logo.png', owned: false},
    {name: '秋季课程资料.pdf', size: 2476605, type: 'application/pdf', url: '', owned: false}
  ];

  function persist() {
    try { localStorage.setItem('fuge-ui-preview-v1', JSON.stringify(prefs)); $('#settings-feedback').textContent = '设置已保存到此浏览器'; }
    catch (_) { $('#settings-feedback').textContent = '浏览器存储不可用，设置仅在本次保留'; }
  }
  function busy() { return Boolean(task?.active || contactRead); }
  function toast(message, error = false) {
    const item = document.createElement('div');
    item.className = `toast${error ? ' error' : ''}`;
    item.innerHTML = `${icon(error ? 'circle-alert' : 'circle-check')}<span>${esc(message)}</span>`;
    $('#toast-region').append(item);
    icons();
    setTimeout(() => item.remove(), 4200);
  }
  function openDialog(id) { closeMenus(); hideTooltip(); const dialog = document.getElementById(id); if (!dialog.open) dialog.showModal(); }
  function closeDialog(id) {
    if (id === 'settings-dialog' && !busy()) commitSettingsInputs();
    closeMenus();
    document.getElementById(id).close();
  }
  function confirm(title, text, callback) {
    $('#confirm-title').textContent = title;
    $('#confirm-text').textContent = text;
    confirmation = callback;
    openDialog('confirm-dialog');
  }
  function sizeLabel(size) {
    return size >= 1048576 ? `${(size / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(size / 1024))} KB`;
  }
  function recipients() { return $('#recipients').value.split(/\r?\n/).map(value => value.trim()).filter(Boolean); }
  function applySidebar() {
    $('.app').dataset.sidebar = prefs.collapsed ? 'collapsed' : 'expanded';
    $('#sidebar-toggle').setAttribute('aria-label', prefs.collapsed ? '展开侧栏' : '折叠侧栏');
    $('#sidebar-toggle').dataset.tooltip = prefs.collapsed ? '展开侧栏' : '折叠侧栏';
    $('#sidebar-toggle').innerHTML = icon(prefs.collapsed ? 'panel-left-open' : 'panel-left-close');
    icons();
  }
  function setTheme(theme) {
    prefs.theme = theme;
    document.documentElement.dataset.theme = theme;
    $('#toggle-theme').innerHTML = `${icon(theme === 'light' ? 'moon' : 'sun')}<span class="nav-label">${theme === 'light' ? '深色外观' : '浅色外观'}</span>`;
    $$('[data-theme-choice]').forEach(button => {button.classList.toggle('active', button.dataset.themeChoice === theme); button.setAttribute('aria-pressed', String(button.dataset.themeChoice === theme));});
    icons(); persist();
  }
  function renderWorkspace() {
    $$('.workspace').forEach(section => {section.hidden = true;});
    const showMonitor = task && task.kind === workspace && !task.showEditor;
    $(showMonitor ? '#task-monitor' : `#${workspace}-workspace`).hidden = false;
    $$('[data-workspace]').forEach(button => {
      button.classList.toggle('active', button.dataset.workspace === workspace);
      if (button.dataset.workspace === workspace) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    closeMenus(); hideTooltip();
    if (workspace === 'friends' && !showMonitor && currentFriend >= 0) requestAnimationFrame(() => $(`#friend-table tr[data-index="${currentFriend}"]`)?.scrollIntoView({block:'nearest', inline:'nearest'}));
  }
  function updateLocks() {
    const locked = busy();
    ['#recipients', '#message-template', '#insert-name', '#add-attachment', '#attachment-drop', '#import-friends', '#clear-friends', '#select-range', '#clear-selection', '#range-start', '#range-end', '#select-visible', '#global-greeting', '#global-suffix', '#suffix-options', '#empty-import'].forEach(selector => {$(selector).disabled = locked;});
    $$('#friend-table input[type="checkbox"], [data-placeholder], [data-step], [data-remove-attachment]').forEach(element => {element.disabled = locked;});
    $$('[data-settings-panel]:not([data-settings-panel="appearance"]) input, [data-settings-panel]:not([data-settings-panel="appearance"]) textarea, [data-settings-panel]:not([data-settings-panel="appearance"]) select').forEach(element => {element.disabled = locked;});
    $('#reset-settings').disabled = locked;
    $('#settings-lock-note').hidden = !locked;
    $('#start-message').disabled = locked || !recipients().length || (!$('#message-template').value.trim() && !attachments.length);
    $('#start-friends').disabled = locked || !friends.some(row => row.selected && row.valid);
    $('#read-contacts').disabled = locked;
    $('#contact-account').disabled = locked;
    $('#export-contacts').disabled = locked || !filteredContacts().length;
    $('#clear-contacts').disabled = locked;
  }
  function renderMessage() {
    const names = recipients();
    previewIndex = Math.min(Math.max(0, previewIndex), Math.max(0, names.length - 1));
    const name = names[previewIndex] || '等待选择好友';
    $('#recipient-count').textContent = `${names.length} 人`;
    $('#preview-name').textContent = name;
    $('#preview-avatar').textContent = name[0];
    $('#preview-position').textContent = names.length ? `${previewIndex + 1} / ${names.length}` : '0 / 0';
    $('#preview-previous').disabled = previewIndex === 0;
    $('#preview-next').disabled = previewIndex >= names.length - 1;
    $('#message-mode').textContent = prefs.fuzzy ? '模糊搜索 · 首个结果' : '精确搜索';
    $('#message-footer-detail').textContent = `${names.length} 位收件人 · 间隔 ${prefs.messageInterval.join('–')} 秒`;
    $('#start-message-count').textContent = names.length;
    const message = $('#message-template').value.replaceAll('{name}', names[previewIndex] || '');
    let content = message ? `<div class="chat-row"><div class="message-bubble">${esc(message)}</div><img src="assets/fuge-logo.png" alt="我"></div>` : '';
    content += attachments.map((attachment, index) => {
      const image = attachment.type.startsWith('image/');
      return `<div class="chat-row"><div class="chat-attachment">${image ? `<button id="preview-attachment-${index}" class="image-thumb" data-preview-attachment="${index}" aria-label="放大 ${esc(attachment.name)}"><img src="${esc(attachment.url)}" alt="${esc(attachment.name)}" loading="lazy"></button><div class="image-caption">${esc(attachment.name)}</div>` : `<button id="preview-attachment-${index}" class="chat-file" data-preview-attachment="${index}">${icon('file-text')}<div class="file-description"><strong>${esc(attachment.name)}</strong><span>${sizeLabel(attachment.size)} · ${esc(attachment.name.split('.').pop().toUpperCase())}</span></div></button>`}</div><img src="assets/fuge-logo.png" alt="我"></div>`;
    }).join('');
    $('#preview-messages').innerHTML = content || `<div class="empty-state"><i data-lucide="message-square"></i><strong>暂无消息</strong></div>`;
    $('#attachment-list').innerHTML = attachments.map((attachment, index) => `<div class="attachment-item"><div class="file-icon">${attachment.type.startsWith('image/') ? `<img src="${esc(attachment.url)}" alt="">` : icon('file-text')}</div><div class="file-description"><strong>${esc(attachment.name)}</strong><span>${sizeLabel(attachment.size)}</span></div><button class="icon-button small" data-remove-attachment="${index}" aria-label="移除 ${esc(attachment.name)}" data-tooltip="移除附件">${icon('x')}</button></div>`).join('');
    icons(); updateLocks();
  }
  function addFiles(files) {
    if (busy()) return;
    for (const file of files) {
      if (attachments.some(item => item.name === file.name && item.size === file.size)) continue;
      const image = ['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/bmp'].includes(file.type);
      attachments.push({name: file.name, size: file.size, type: image ? file.type : 'application/octet-stream', url: image ? URL.createObjectURL(file) : '', owned: image});
    }
    $('#attachment-picker').value = '';
    renderMessage();
  }
  function previewAttachment(index) {
    const attachment = attachments[index];
    if (!attachment) return;
    if (attachment.type.startsWith('image/')) {
      $('#image-title').textContent = attachment.name;
      $('#large-image').src = attachment.url;
      $('#large-image').alt = attachment.name;
      openDialog('image-dialog');
    } else toast(`已选择 ${attachment.name} · ${sizeLabel(attachment.size)}`);
  }
  function friendRemark(row) {
    const suffix = row.suffix === '使用全局' ? prefs.suffix : row.suffix;
    return row.name + (suffix && suffix !== '无' ? suffix : '');
  }
  function friendGreeting(row) {
    return (row.greeting || prefs.greeting).replaceAll('{姓名}', row.name).replaceAll('{后缀}', row.suffix === '使用全局' ? prefs.suffix : row.suffix).replaceAll('{称呼}', friendRemark(row));
  }
  function validateFriends() {
    const seen = new Set();
    friends.forEach(row => {
      const normalized = row.account.trim().toLowerCase();
      row.error = !normalized ? '账号为空' : seen.has(normalized) ? '账号重复' : !/^[a-zA-Z0-9_-]{3,}$/.test(normalized) ? '账号格式异常' : '';
      row.valid = !row.error;
      if (row.valid) seen.add(normalized); else row.selected = false;
    });
  }
  function renderFriends() {
    const tbody = $('#friend-table tbody');
    const selected = friends.filter(row => row.selected).length;
    const valid = friends.filter(row => row.valid).length;
    tbody.innerHTML = friends.map((row, index) => {
      if (invalidOnly && row.valid) return '';
      return `<tr data-index="${index}" class="${row.selected ? 'selected ' : ''}${index === currentFriend ? 'current ' : ''}${!row.valid ? 'invalid ' : ''}${row.risk ? 'risk' : ''}" tabindex="${index === Math.max(0,currentFriend) ? 0 : -1}"><td><input type="checkbox" data-friend-check="${index}" aria-label="选择第 ${index + 1} 条 ${esc(row.name)}" ${row.selected ? 'checked' : ''} ${!row.valid || busy() ? 'disabled' : ''}></td><td class="row-number">${String(index + 1).padStart(2,'0')}</td><td data-field="name" data-tooltip="${esc(row.name)}"><span class="cell-text">${esc(row.name || '—')}</span></td><td data-field="account" class="account-text" data-tooltip="${esc(row.account || row.error)}"><span class="cell-text ${!row.valid ? 'cell-placeholder' : ''}">${esc(row.account || '账号为空')}</span></td><td data-field="suffix"><span class="cell-text">${esc(row.suffix)}</span></td><td data-field="greeting" data-tooltip="${esc(friendGreeting(row))}"><span class="cell-text ${!row.greeting ? 'cell-placeholder' : ''}">${esc(row.greeting || '使用全局打招呼语')}</span></td><td data-tooltip="${esc(friendRemark(row))}"><span class="cell-text">${esc(friendRemark(row))}</span></td><td><span class="status-badge ${row.risk ? 'warning' : !row.valid ? 'danger' : row.status === '已完成' ? 'success' : ''}">${esc(row.risk ? '频繁限制' : !row.valid ? '待修正' : row.selected ? (row.status === '待选择' ? '已选择' : row.status) : row.status === '已完成' ? row.status : '未选择')}</span></td></tr>`;
    }).join('');
    $('#friend-total').textContent = friends.length;
    $('#friend-valid').textContent = valid;
    $('#friend-invalid').textContent = friends.length - valid;
    $('#friend-selection-count').textContent = `已选择 ${selected} / ${prefs.batchLimit}`;
    $('#friend-footer-detail').textContent = `每批最多 ${prefs.batchLimit} 人 · 间隔 ${prefs.friendInterval.join('–')} 秒`;
    $('#start-friends-count').textContent = selected;
    $('#friend-empty').hidden = friends.length > 0;
    $('#select-visible').checked = selected > 0 && selected === Math.min(valid, prefs.batchLimit);
    $('#select-visible').indeterminate = selected > 0 && !$('#select-visible').checked;
    const row = friends[currentFriend];
    $('#friend-current').innerHTML = `${icon(row?.risk ? 'shield-alert' : 'scan-line')}<span>${row ? `第 ${currentFriend + 1} 条 · ${esc(row.name)}${row.risk ? ' · 频繁限制' : ''}` : '未定位记录'}</span>`;
    icons(); updateLocks();
  }
  function selectFriendRow(index) {
    currentFriend = index;
    $$('#friend-table tbody tr').forEach(row => {
      const current = Number(row.dataset.index) === index;
      row.classList.toggle('current', current);
      row.tabIndex = current ? 0 : -1;
    });
    const row = friends[index];
    $('#friend-current').innerHTML = `${icon(row?.risk ? 'shield-alert' : 'scan-line')}<span>${row ? `第 ${index + 1} 条 · ${esc(row.name)}${row.risk ? ' · 频繁限制' : ''}` : '未定位记录'}</span>`;
    icons();
  }
  function beginCellEdit(cell) {
    if (busy() || !cell.dataset.field || cell.classList.contains('editing')) return;
    const index = Number(cell.closest('tr').dataset.index);
    const field = cell.dataset.field;
    const row = friends[index];
    if (!row) return;
    selectFriendRow(index);
    cell.classList.add('editing');
    cell.removeAttribute('data-tooltip');
    cell.innerHTML = `<input class="text-edit cell-editor" aria-label="编辑第 ${index + 1} 条${esc(field)}" value="${esc(row[field])}"${field === 'suffix' ? ' list="row-suffix-options"' : ''}>`;
    if (field === 'suffix' && !$('#row-suffix-options')) {
      const list = document.createElement('datalist'); list.id = 'row-suffix-options';
      list.innerHTML = ['使用全局', ...suffixes].map(value => `<option value="${esc(value)}"></option>`).join(''); document.body.append(list);
    }
    const input = cell.firstElementChild;
    input.focus(); input.select();
    let finished = false;
    const finish = save => {
      if (finished) return;
      finished = true;
      if (save) row[field] = input.value.trim();
      validateFriends(); renderFriends();
      const fresh = $(`#friend-table tr[data-index="${index}"]`);
      fresh?.focus({preventScroll:true});
    };
    input.addEventListener('blur', () => {if (!$('#context-menu').hidden && contextTarget === input) return; finish(true);});
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape') {event.stopPropagation(); event.preventDefault(); finish(false);}
      if (event.key === 'Enter') {event.preventDefault(); finish(true);}
      if (event.key === 'Tab') {
        event.preventDefault(); const fields = ['name','account','suffix','greeting']; const next = fields.indexOf(field) + (event.shiftKey ? -1 : 1);
        finish(true); if (next >= 0 && next < fields.length) beginCellEdit($(`#friend-table tr[data-index="${index}"] [data-field="${fields[next]}"]`));
      }
    });
  }
  function filteredContacts() {
    const query = $('#contact-search').value.trim().toLocaleLowerCase();
    return contacts.filter(contact => ($('#include-special').checked || contact.type === 'friend') && (!query || ['nickname','remark','phone','wechatId','account','description'].some(field => contact[field].toLocaleLowerCase().includes(query)))).sort((a,b) => a[contactSort.field].localeCompare(b[contactSort.field], 'zh-CN') * contactSort.direction);
  }
  function renderContacts() {
    const rows = filteredContacts();
    $('#contact-table tbody').innerHTML = rows.map(contact => `<tr data-contact="${contact.id}" class="${contact.id === currentContact ? 'current' : ''}">${['nickname','remark','phone','wechatId','account','description'].map(field => `<td tabindex="0" data-contact-field="${field}" data-tooltip="${esc(contact[field])}" class="${['wechatId','account','phone'].includes(field) ? 'account-text' : ''}">${esc(contact[field])}</td>`).join('')}</tr>`).join('');
    $('#contact-count').textContent = `${rows.length} / ${contacts.length}`;
    $('#contact-empty').hidden = rows.length > 0;
    const ordinary = contacts.filter(row => row.type === 'friend').length;
    $('#contact-summary').textContent = `${ordinary} 位普通联系人 · ${contacts.length - ordinary} 个特殊账号`;
    $$('[data-sort]').forEach(button => {
      button.classList.toggle('sorted', button.dataset.sort === contactSort.field);
      button.closest('th').setAttribute('aria-sort', button.dataset.sort === contactSort.field ? (contactSort.direction === 1 ? 'ascending' : 'descending') : 'none');
    });
    updateLocks();
  }
  function startContactRead() {
    if (busy()) return;
    contactRead = {clock: new M.TaskClock(), stage: 0}; contactRead.clock.start();
    $('#cancel-read').hidden = false; $('#contact-elapsed').hidden = false;
    $('#contact-dot').className = 'status-dot busy'; $('#contact-stage').textContent = '正在验证进程';
    updateLocks();
  }
  function cancelContactRead() {
    if (!contactRead) return;
    contactRead = null; $('#cancel-read').hidden = true;
    $('#contact-stage').textContent = '读取已取消'; $('#contact-dot').className = 'status-dot warning';
    updateLocks(); toast('读取已取消，原有表格保留');
  }
  function showSettings(section = settingsSection) {
    settingsSection = section;
    $$('[data-settings]').forEach(button => button.classList.toggle('active', button.dataset.settings === section));
    $$('[data-settings-panel]').forEach(panel => {panel.hidden = panel.dataset.settingsPanel !== section;});
    syncSettings(); openDialog('settings-dialog');
  }
  function syncSettings() {
    $('#message-min').value = prefs.messageInterval[0]; $('#message-max').value = prefs.messageInterval[1];
    $('#friend-min').value = prefs.friendInterval[0]; $('#friend-max').value = prefs.friendInterval[1];
    $('#batch-limit').value = prefs.batchLimit; $('#fuzzy-search').checked = prefs.fuzzy;
    $('#default-greeting').value = prefs.greeting; $('#default-suffix').value = prefs.suffix;
    $('#unknown-policy').value = prefs.unknownPolicy; $('#safe-retries').checked = prefs.safeRetries;
    $('#recovery-policy').value = prefs.recoveryPolicy; $('#login-timeout').value = prefs.loginTimeout;
    $('#glass-enabled').checked = prefs.glass; $('#glass-opacity').value = prefs.opacity; $('#glass-value').textContent = `${prefs.opacity}%`;
    $$('[data-theme-choice]').forEach(button => button.classList.toggle('active', button.dataset.themeChoice === prefs.theme));
    updateLocks();
  }
  function saveInterval(id) {
    const kind = id.startsWith('friend') ? 'friend' : 'message';
    const key = `${kind}Interval`;
    if (busy()) {syncSettings(); return;}
    const result = M.updateInterval(prefs[key], id.endsWith('min') ? 'min' : 'max', document.getElementById(id).value, 1, 300);
    if (!result) {toast('请输入 1–300 内的整数，已恢复保存值', true); syncSettings(); return;}
    prefs[key] = result; persist(); syncSettings(); renderMessage(); renderFriends();
  }
  function saveBatchLimit() {
    if (busy()) {syncSettings(); return;}
    const value = M.integer($('#batch-limit').value);
    if (!Number.isSafeInteger(value) || value < 1 || value > 1000) {toast('每批人数必须为 1–1000 的整数', true); syncSettings(); return;}
    prefs.batchLimit = value;
    let selected = 0; friends.forEach(row => {if (row.selected && ++selected > value) row.selected = false;});
    persist(); renderFriends();
  }
  function commitSettingsInputs() {
    const panel = $(`[data-settings-panel="${settingsSection}"]`);
    // Capture both endpoints before any synchronization can replace the focused draft.
    if (['message','friends'].includes(settingsSection)) {
      const kind = settingsSection === 'friends' ? 'friend' : 'message';
      const minimum = $(`#${kind}-min`).value;
      const maximum = $(`#${kind}-max`).value;
      let range = M.updateInterval(prefs[`${kind}Interval`], 'min', minimum, 1, 300);
      range = range && M.updateInterval(range, 'max', maximum, 1, 300);
      if (range) prefs[`${kind}Interval`] = range;
      else toast('请输入 1–300 内的整数，已恢复保存值', true);
    }
    const pending = [...panel.querySelectorAll('textarea, input:not([type=checkbox]):not([type=range])')].filter(input => !/(?:min|max)$/.test(input.id));
    pending.forEach(input => input.dispatchEvent(new Event('change')));
    persist(); syncSettings(); renderMessage(); renderFriends();
  }
  function applyGlass() { document.documentElement.style.setProperty('--glass', prefs.glass ? (prefs.theme === 'dark' ? `rgba(34,34,38,${prefs.opacity / 100})` : `rgba(247,247,249,${prefs.opacity / 100})`) : 'var(--surface)'); }
  function insertAtCursor(field, value) {
    if (field.disabled || field.readOnly) return;
    remember(field); field.focus(); field.setRangeText(value, field.selectionStart ?? field.value.length, field.selectionEnd ?? field.value.length, 'end');
    field.dispatchEvent(new Event('input', {bubbles:true}));
  }

  function log(message, level = 'normal') {
    if (!task) return;
    task.logs.push({at: new Date().toISOString(), message, level});
    $('#log-content').innerHTML = task.logs.map(entry => `<div class="log-line ${entry.level === 'error' ? 'error' : entry.level === 'warning' ? 'warning' : ''}"><time>${new Date(entry.at).toLocaleTimeString('zh-CN', {hour12:false})}</time><span class="log-level">${entry.level === 'error' ? '异常' : entry.level === 'warning' ? '提示' : '状态'}</span><span>${esc(entry.message)}</span></div>`).join('');
    $('#log-count').textContent = task.logs.length;
    $('#log-content').scrollTop = $('#log-content').scrollHeight;
  }
  const messageSteps = ['绑定微信窗口', '搜索入口已就绪', '已选择目标', '目标校验通过', '输入框已就绪', '内容已写入', '已触发发送', '发送结果已确认'];
  const friendSteps = ['绑定微信窗口', '添加好友窗口已就绪', '账号已写入', '账号搜索完成', '资料核对通过', '申请窗口已就绪', '申请内容已核对', '提交申请', '提交结果已确认'];
  function startTask(kind) {
    if (busy()) {toast('当前任务尚未结束', true); return;}
    const queue = kind === 'message' ? recipients().map((name,index) => ({id:`message-${index}`, sourceIndex:index, target:name, detail:'等待执行', result:'', duration:0})) : friends.map((row,index) => ({...row, sourceIndex:index, target:row.account, detail:'等待执行', result:'', duration:0})).filter(row => row.selected && row.valid);
    if (!queue.length) {toast('请先选择有效记录', true); return;}
    if (kind === 'friends' && queue.length > prefs.batchLimit) {toast('所选记录超过批次上限', true); return;}
    if ($('#settings-dialog').open) $('#settings-dialog').close();
    task = {kind, queue, active:true, paused:false, phase:'preparing', index:0, step:0, clock:new M.TaskClock(), interval:[...(kind === 'message' ? prefs.messageInterval : prefs.friendInterval)], logs:[], nextAt:450, itemStart:0, scenario:'normal', showEditor:false, stoppingReason:''};
    task.clock.start(); workspace = kind;
    $('#monitor-title').textContent = kind === 'message' ? '消息发送队列' : '好友申请队列';
    $('#monitor-eyebrow').textContent = kind === 'message' ? '任务 / 消息' : '任务 / 好友';
    $('#queue-target-title').textContent = kind === 'message' ? '好友' : '账号';
    $('#task-interval').textContent = `本批间隔 ${task.interval.join('–')} 秒`;
    $('#task-log').open = false;
    log('任务已启动，正在恢复并绑定微信窗口');
    updateHealth('正在恢复微信', 'busy'); renderTask(); renderWorkspace(); updateLocks();
  }
  function updateHealth(text, state = '') {
    $('#health-label').textContent = text;
    $('#health-detail').textContent = text;
    $('#health-status .status-dot').className = `status-dot ${state}`;
    $('#monitor-health').textContent = text;
  }
  function beginItem() {
    task.phase = 'processing'; task.step = 0; task.itemStart = task.clock.elapsed(); task.nextAt = task.clock.elapsed() + 280;
    task.queue[task.index].detail = '正在绑定微信窗口';
    updateHealth('自动化执行中', 'busy');
  }
  function finishItem(result, detail) {
    const row = task.queue[task.index];
    row.result = result; row.detail = detail; row.duration = task.clock.elapsed() - task.itemStart;
    if (task.kind === 'friends') { const original = friends[row.sourceIndex]; if (original && original.id === row.id) {original.status = result === 'success' ? '已完成' : result === 'risk' ? '频繁限制' : '失败'; original.risk = result === 'risk';} }
    log(`${row.target}：${detail}`, result === 'failed' || result === 'risk' ? 'error' : result === 'unknown' ? 'warning' : 'normal');
    const stop = result === 'risk' || (result === 'unknown' && prefs.unknownPolicy === 'stop');
    if (stop) {currentFriend = task.kind === 'friends' ? row.sourceIndex : currentFriend; finishTask(result === 'risk' ? '频繁限制，任务已停止' : '结果未知，任务已停止');}
    else if (task.index === task.queue.length - 1) finishTask('任务已结束');
    else {
      task.phase = 'waiting';
      const seconds = task.interval[0] + Math.floor(Math.random() * (task.interval[1] - task.interval[0] + 1));
      task.nextAt = task.clock.elapsed() + seconds * 1000;
    }
    task.scenario = 'normal'; renderTask();
  }
  function finishTask(reason) {
    if (!task?.active || task.phase === 'cleanup') return;
    if (task.paused) {task.paused = false; task.clock.resume();}
    task.phase = 'cleanup'; task.stoppingReason = reason; task.nextAt = task.clock.elapsed() + 450;
    log('正在安全清理任务窗口');
    renderTask();
  }
  function finalizeTask() {
    task.phase = 'finished'; task.active = false; task.clock.stop();
    task.queue.forEach(row => {if (!row.result) row.detail = '未执行';});
    log('任务清理完成，自动化会话已恢复就绪');
    updateHealth('自动化已就绪'); renderTask(); renderFriends(); updateLocks();
  }
  function renderTask() {
    if (!task) return;
    const completed = task.queue.filter(row => row.result).length;
    const successes = task.queue.filter(row => row.result === 'success').length;
    const failures = task.queue.filter(row => ['failed','risk'].includes(row.result)).length;
    const unknown = task.queue.filter(row => row.result === 'unknown').length;
    const percent = Math.round(completed / task.queue.length * 100);
    $('#task-count').textContent = `已处理 ${completed} / ${task.queue.length}`;
    $('#task-percent').textContent = `${percent}%`;
    $('#task-progress').style.width = `${percent}%`;
    $('#task-result-count').textContent = `成功 ${successes} · 失败 ${failures} · 未知 ${unknown}`;
    $('#queue-table tbody').innerHTML = task.queue.map((row,index) => `<tr class="${row.result === 'risk' ? 'risk' : row.result === 'failed' ? 'failed' : index === task.index && task.active ? 'running' : ''}" data-queue-index="${index}"><td class="row-number">${String(row.sourceIndex + 1).padStart(2,'0')}</td><td class="account-text" data-tooltip="${esc(row.target)}">${esc(row.target)}</td><td data-tooltip="${esc(row.detail)}">${esc(row.detail)}</td><td>${row.result ? `<span class="status-badge ${row.result === 'success' ? 'success' : row.result === 'unknown' || row.result === 'risk' ? 'warning' : 'danger'}">${({success:'成功', failed:'失败', unknown:'未知', risk:'频繁限制'})[row.result]}</span>` : '<span class="cell-placeholder">—</span>'}</td><td class="row-number">${row.result ? `${(row.duration / 1000).toFixed(1)}s` : '—'}</td></tr>`).join('');
    const steps = task.kind === 'message' ? messageSteps : friendSteps;
    $('#task-steps').innerHTML = steps.map((step,index) => `<li class="${index < task.step ? 'done' : index === task.step ? task.queue[task.index].result === 'failed' || task.queue[task.index].result === 'risk' ? 'failed' : 'active' : ''}">${step}</li>`).join('');
    $('#current-step-count').textContent = `${Math.min(task.step + 1, steps.length)} / ${steps.length}`;
    $('#return-editor').disabled = task.active;
    $('#pause-task').disabled = !task.active || task.phase === 'cleanup';
    $('#stop-task').disabled = !task.active || task.phase === 'cleanup';
    $('#task-scenario').disabled = !task.active || task.phase === 'cleanup';
    $('#pause-task').innerHTML = `${icon(task.paused ? 'play' : 'pause')}<span>${task.paused ? '继续' : '暂停'}</span>`;
    $('#sidebar-task').hidden = !task.active;
    $('#sidebar-task-text').textContent = task.paused ? '任务已暂停' : '任务执行中';
    $('#task-footer-title').textContent = task.phase === 'finished' ? task.stoppingReason : task.paused ? '任务已暂停' : task.phase === 'cleanup' ? '正在安全收尾' : '任务执行中';
    $('#task-footer-detail').textContent = task.phase === 'finished' ? `成功 ${successes} · 失败 ${failures} · 未知 ${unknown} · 未执行 ${task.queue.length - completed}` : '暂停与停止在安全步骤生效';
    $('#task-footer-dot').className = `status-dot ${task.phase === 'finished' ? failures || unknown ? 'warning' : '' : 'busy'}`;
    const phase = task.paused ? '已暂停' : ({preparing:'正在准备', processing:'正在执行', waiting:'等待下一条', cleanup:'正在清理', finished:'任务结束'})[task.phase];
    $('#task-phase').textContent = phase;
    $('#task-phase').className = `status-badge ${task.phase === 'finished' ? failures || unknown ? 'warning' : 'success' : 'busy'}`;
    icons();
    $(`#queue-table tr[data-queue-index="${task.index}"]`)?.scrollIntoView({block:'nearest', inline:'nearest'});
    updateTaskTime();
  }
  function updateTaskTime() {
    if (!task) return;
    $('#elapsed-time').textContent = M.formatElapsed(task.clock.elapsed());
    $('#task-waiting').textContent = task.phase === 'waiting' ? task.paused ? '等待已暂停' : `下一条将在 ${Math.max(0,Math.ceil((task.nextAt - task.clock.elapsed()) / 1000))} 秒后开始` : task.phase === 'finished' ? '已完成清理与健康复检' : task.phase === 'preparing' ? '正在恢复并绑定微信窗口' : task.phase === 'cleanup' ? '清理完成后解除任务互斥' : task.paused ? '计时已暂停' : `正在处理第 ${task.index + 1} 条`;
  }
  function tick() {
    if (contactRead) {
      const elapsed = contactRead.clock.elapsed();
      $('#contact-elapsed').textContent = M.formatElapsed(elapsed);
      const phases = ['正在验证进程', '正在复制加密快照', '正在查找密钥', '正在校验数据库', '正在读取联系人'];
      $('#contact-stage').textContent = phases[Math.min(4,Math.floor(elapsed / 550))];
      if (elapsed >= 2800) {
        contacts = M.makeContacts(); contactRead = null;
        $('#cancel-read').hidden = true; $('#contact-stage').textContent = '联系人已载入'; $('#contact-dot').className = 'status-dot';
        renderContacts(); toast('已读取 86 条模拟联系人');
      }
    }
    updateTaskTime();
    if (!task?.active || task.paused || task.clock.elapsed() < task.nextAt) return;
    if (task.phase === 'cleanup') {finalizeTask(); return;}
    if (task.phase === 'preparing') {beginItem(); log('微信窗口已绑定，自动化执行中'); renderTask(); return;}
    if (task.phase === 'waiting') {task.index++; beginItem(); renderTask(); return;}
    if (task.phase === 'processing') {
      const steps = task.kind === 'message' ? messageSteps : friendSteps;
      if (task.scenario === 'risk') {finishItem('risk', '检测到操作频繁限制，已停止整批'); return;}
      if (task.scenario === 'failed' && task.step >= 2) {finishItem('failed', '搜索失败：未找到匹配账号'); return;}
      task.step++;
      if (task.step >= steps.length) {finishItem(task.scenario === 'unknown' ? 'unknown' : 'success', task.scenario === 'unknown' ? '结果未知，已保留边界且不会重发' : task.kind === 'message' ? '消息与附件发送完成' : '好友申请已完成'); return;}
      task.queue[task.index].detail = steps[task.step]; task.nextAt = task.clock.elapsed() + 280; renderTask();
    }
  }

  function remember(field) {
    if (!histories.has(field)) histories.set(field, {states:[field.value], index:0});
    return histories.get(field);
  }
  function recordInput(field) {
    const history = remember(field);
    if (history.states[history.index] === field.value) return;
    history.states.splice(history.index + 1); history.states.push(field.value); history.index++;
    if (history.states.length > 80) {history.states.shift(); history.index--;}
  }
  async function copyText(value) {
    clipboardFallback = value;
    try {await navigator.clipboard.writeText(value);}
    catch (_) {
      const field = document.createElement('textarea'); field.value = value; field.style.cssText = 'position:fixed;left:-9999px'; document.body.append(field); field.select();
      const success = document.execCommand('copy'); field.remove();
      if (!success) toast('已保留选中文本，请使用 Ctrl+C 复制', true);
    }
  }
  function closeMenus(returnFocus = false) {
    $('#context-menu').hidden = true; $('#combo-menu').hidden = true;
    if (returnFocus && contextTarget?.isConnected) contextTarget.focus({preventScroll:true});
  }
  function placePopup(element,x,y) {
    element.hidden = false;
    const rect = element.getBoundingClientRect();
    element.style.left = `${Math.max(8,Math.min(x,innerWidth - rect.width - 8))}px`;
    element.style.top = `${Math.max(8,Math.min(y,innerHeight - rect.height - 8))}px`;
  }
  function openMenu(items,x,y,target) {
    closeMenus(); hideTooltip(); contextTarget = target; menuActions = items;
    // Menus inside a modal must share its browser top layer.
    (document.querySelector('dialog[open]') || document.body).append($('#context-menu'));
    $('#context-menu').innerHTML = items.map((item,index) => item.separator ? '<hr role="separator">' : `<button role="menuitem" data-menu-action="${index}" ${item.disabled ? 'disabled' : ''} class="${item.danger ? 'danger' : ''}">${icon(item.icon || 'circle')}<span>${esc(item.label)}</span><kbd>${esc(item.shortcut || '')}</kbd></button>`).join('');
    icons(); placePopup($('#context-menu'),x,y); $('#context-menu button:not(:disabled)')?.focus({preventScroll:true});
  }
  function undo(field, redo = false) {
    const history = remember(field); const next = history.index + (redo ? 1 : -1);
    if (field.disabled || field.readOnly || next < 0 || next >= history.states.length) return;
    history.index = next; field.value = history.states[next];
    field.dispatchEvent(new Event('input',{bubbles:true})); field.focus();
  }
  function textMenu(field,x,y) {
    const history = remember(field);
    const selected = field.value.slice(field.selectionStart ?? 0, field.selectionEnd ?? 0);
    const writable = !field.disabled && !field.readOnly;
    const set = value => insertAtCursor(field,value);
    openMenu([
      {label:'撤销', icon:'undo-2', shortcut:'Ctrl+Z', disabled:!writable || history.index === 0, run:()=>undo(field)},
      {label:'重做', icon:'redo-2', shortcut:'Ctrl+Y', disabled:!writable || history.index === history.states.length - 1, run:()=>undo(field,true)},
      {separator:true},
      {label:'剪切', icon:'scissors', shortcut:'Ctrl+X', disabled:!writable || !selected, run:()=>{copyText(selected); set('');}},
      {label:'复制', icon:'copy', shortcut:'Ctrl+C', disabled:!selected, run:()=>copyText(selected)},
      {label:'粘贴', icon:'clipboard-paste', shortcut:'Ctrl+V', disabled:!writable, run:async()=>{try {set(await navigator.clipboard.readText());} catch (_) {if (clipboardFallback) set(clipboardFallback); else toast('浏览器未授权剪贴板读取，请使用 Ctrl+V',true);}}},
      {label:'删除', icon:'delete', disabled:!writable || !selected, run:()=>set('')},
      {separator:true},
      {label:'全选', icon:'text-select', shortcut:'Ctrl+A', disabled:!field.value, run:()=>{field.focus(); field.select();}}
    ],x,y,field);
  }
  function rowMenu(index,x,y) {
    const row = friends[index];
    const add = offset => {
      if (busy()) return;
      friends.splice(Math.max(0,index + offset),0,{id:`added-${Date.now()}`,source:null,name:'',account:'',suffix:'使用全局',greeting:'',valid:false,error:'账号为空',selected:false,status:'待选择'});
      currentFriend = Math.max(0,index + offset); renderFriends();
    };
    openMenu([
      {label:'在上方新增一行', icon:'list-plus', disabled:busy(), run:()=>add(0)},
      {label:'在下方新增一行', icon:'list-plus', disabled:busy(), run:()=>add(1)},
      {separator:true},
      {label:'复制账号', icon:'copy', disabled:!row?.account, run:()=>{copyText(row.account); toast('账号已复制');}},
      {label:row?.selected ? '取消选择' : '选择此条', icon:'list-checks', disabled:busy() || !row?.valid, run:()=>toggleFriend(index,!row.selected)},
      {separator:true},
      {label:'删除此行', icon:'trash-2', danger:true, disabled:busy() || !row, run:()=>{friends.splice(index,1); currentFriend = Math.min(index,friends.length - 1); renderFriends();}}
    ],x,y,$(`#friend-table tr[data-index="${index}"]`));
  }
  function toggleFriend(index,selected) {
    if (busy() || !friends[index]?.valid) return;
    if (selected && !friends[index].selected && friends.filter(row => row.selected).length >= prefs.batchLimit) {toast(`每批最多选择 ${prefs.batchLimit} 条`,true); renderFriends(); return;}
    friends[index].selected = selected; renderFriends();
  }
  function hideTooltip() {clearTimeout(tooltipTimer); $('#tooltip').hidden = true;}
  function openSuffixMenu() {
    if (busy()) return;
    const rect = $('#global-suffix').getBoundingClientRect();
    $('#combo-menu').innerHTML = suffixes.map(value => `<button role="option" data-suffix-value="${esc(value)}" aria-selected="${value === prefs.suffix}"><span>${esc(value)}</span>${value === prefs.suffix ? icon('check') : ''}</button>`).join('');
    icons(); placePopup($('#combo-menu'),rect.left,rect.bottom + 5); $('#combo-menu button')?.focus();
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (button?.disabled) return;
    if (button?.dataset.workspace) {workspace = button.dataset.workspace; renderWorkspace();}
    if (button?.dataset.settings) {settingsSection = button.dataset.settings; syncSettings(); $$('[data-settings]').forEach(item=>item.classList.toggle('active',item === button)); $$('[data-settings-panel]').forEach(panel=>{panel.hidden = panel.dataset.settingsPanel !== settingsSection;});}
    if (button?.dataset.openSettings) showSettings(button.dataset.openSettings);
    if (button?.dataset.close) closeDialog(button.dataset.close);
    if (button?.dataset.themeChoice) {setTheme(button.dataset.themeChoice); applyGlass();}
    if (button?.dataset.step) {
      const [id,step] = button.dataset.step.split(':'); const field = document.getElementById(id);
      if (!field.disabled) {field.value = Math.min(id === 'batch-limit' ? 1000 : Math.max(1,friends.length),Math.max(1,(M.integer(field.value) || 1) + Number(step))); field.dispatchEvent(new Event('change',{bubbles:true}));}
    }
    if (button?.dataset.placeholder) insertAtCursor($('#global-greeting'),button.dataset.placeholder);
    if (button?.dataset.removeAttachment !== undefined && !busy()) {const [removed] = attachments.splice(Number(button.dataset.removeAttachment),1); if (removed.owned) URL.revokeObjectURL(removed.url); renderMessage();}
    if (button?.dataset.previewAttachment !== undefined) previewAttachment(Number(button.dataset.previewAttachment));
    if (button?.dataset.menuAction !== undefined) {const action = menuActions[Number(button.dataset.menuAction)]; closeMenus(); action?.run?.();}
    if (button?.dataset.suffixValue) {prefs.suffix = button.dataset.suffixValue; $('#global-suffix').value = prefs.suffix; $('#default-suffix').value = prefs.suffix; persist(); closeMenus(); renderFriends();}
    if (button?.dataset.sort) {contactSort = {field:button.dataset.sort, direction:contactSort.field === button.dataset.sort ? -contactSort.direction : 1}; renderContacts();}
    if (button?.dataset.scenario) {
      if (task?.active) {task.scenario = button.dataset.scenario; if (task.scenario === 'risk') {if (task.phase === 'waiting') {task.index++; beginItem();} finishItem('risk','检测到操作频繁限制，已停止整批');} else toast(`已切换${({normal:'正常执行',failed:'搜索失败',unknown:'结果未知'})[task.scenario]}场景`);}
      closeDialog('scenario-dialog');
    }
    const friendCell = event.target.closest('#friend-table tbody td');
    if (friendCell && !event.target.matches('input')) selectFriendRow(Number(friendCell.closest('tr').dataset.index));
    const contactCell = event.target.closest('#contact-table tbody td');
    if (contactCell) {currentContact = Number(contactCell.closest('tr').dataset.contact); $$('#contact-table tbody tr').forEach(row=>row.classList.toggle('current',Number(row.dataset.contact) === currentContact));}
  });
  $('#sidebar-toggle').onclick = () => {prefs.collapsed = !prefs.collapsed; applySidebar(); persist(); closeMenus();};
  $('#toggle-theme').onclick = () => {setTheme(prefs.theme === 'light' ? 'dark' : 'light'); applyGlass();};
  $('#open-settings').onclick = () => showSettings();
  $('#settings-done').onclick = () => closeDialog('settings-dialog');
  $('#health-status').onclick = () => {$('#health-popover').hidden = !$('#health-popover').hidden; $('#health-status').setAttribute('aria-expanded', String(!$('#health-popover').hidden));};
  $('#preview-previous').onclick = () => {previewIndex--; renderMessage();};
  $('#preview-next').onclick = () => {previewIndex++; renderMessage();};
  $('#insert-name').onclick = () => insertAtCursor($('#message-template'),'{name}');
  $('#add-attachment').onclick = $('#attachment-drop').onclick = () => $('#attachment-picker').click();
  $('#attachment-picker').onchange = event => addFiles(event.target.files);
  $('#attachment-drop').ondragover = event => {event.preventDefault(); if (!busy()) $('#attachment-drop').classList.add('drag-over');};
  $('#attachment-drop').ondragleave = () => $('#attachment-drop').classList.remove('drag-over');
  $('#attachment-drop').ondrop = event => {event.preventDefault(); $('#attachment-drop').classList.remove('drag-over'); addFiles(event.dataTransfer.files);};
  $('#recipients').addEventListener('input',renderMessage); $('#message-template').addEventListener('input',renderMessage);
  $('#start-message').onclick = () => startTask('message'); $('#start-friends').onclick = () => startTask('friends');
  $('#select-range').onclick = () => {
    if (busy()) return;
    const result = M.selectRange(friends,$('#range-start').value,$('#range-end').value,prefs.batchLimit);
    $('#range-feedback').textContent = result.error;
    if (result.error) {toast(result.error,true); return;}
    const chosen = new Set(result.indexes); friends.forEach((row,index)=>{row.selected = chosen.has(index);});
    currentFriend = result.indexes[0]; renderFriends(); toast(`已选择 ${result.indexes.length} 条有效记录`);
  };
  $('#clear-selection').onclick = () => {if (!busy()) {friends.forEach(row=>{row.selected=false;}); $('#range-feedback').textContent=''; renderFriends();}};
  $('#clear-friends').onclick = () => confirm('清空名单','清空当前表格？此操作不会改变设置。',()=>{friends=[]; currentFriend=-1; renderFriends();});
  $('#filter-invalid').onclick = () => {invalidOnly=!invalidOnly; $('#filter-invalid').style.color=invalidOnly?'var(--danger)':''; renderFriends();};
  $('#select-visible').onchange = event => {if (busy()) return; let count=0; friends.forEach(row=>{row.selected=event.target.checked && row.valid && count++ < prefs.batchLimit;}); renderFriends();};
  $('#friend-table').addEventListener('change',event=>{if (event.target.dataset.friendCheck !== undefined) toggleFriend(Number(event.target.dataset.friendCheck),event.target.checked);});
  $('#friend-table').addEventListener('dblclick',event=>{const cell=event.target.closest('td[data-field]'); if (cell) beginCellEdit(cell);});
  $('#friend-table').addEventListener('keydown',event=>{
    if (event.target.matches('input')) return;
    const row=event.target.closest('tr[data-index]'); if (!row) return;
    const index=Number(row.dataset.index);
    if (event.key==='Enter') {event.preventDefault(); beginCellEdit(row.querySelector('[data-field="name"]'));}
    if (['ArrowDown','ArrowUp'].includes(event.key)) {event.preventDefault(); const next=Math.max(0,Math.min(friends.length-1,index+(event.key==='ArrowDown'?1:-1))); selectFriendRow(next); $(`#friend-table tr[data-index="${next}"]`)?.focus();}
  });
  $('#global-greeting').addEventListener('input',()=>{if (!busy()) {prefs.greeting=$('#global-greeting').value; $('#default-greeting').value=prefs.greeting; persist();}});
  $('#global-suffix').addEventListener('change',()=>{if (!busy()) {prefs.suffix=$('#global-suffix').value.trim()||'无'; $('#global-suffix').value=prefs.suffix; $('#default-suffix').value=prefs.suffix; persist(); renderFriends();}});
  $('#suffix-options').onclick=openSuffixMenu;
  $('#import-friends').onclick=$('#empty-import').onclick=()=>openDialog('import-dialog');
  $('#import-confirm').onclick=()=>{if (busy()) return; const value=$('input[name="dataset"]:checked').value; friends=value==='empty'?[]:M.makeFriends(value==='invalid'?12:200); if(value==='invalid') friends.forEach((row,index)=>{if(index%3===0){row.account=''; row.valid=false; row.error='账号为空';}}); currentFriend=-1; invalidOnly=false; $('#range-feedback').textContent=''; renderFriends(); closeDialog('import-dialog'); toast(`已导入 ${friends.length} 条模拟记录，尚未勾选`);};
  $('#download-template').onclick=()=>{const blob=new Blob(['\uFEFF姓名,账号,后缀,打招呼语\r\n演示同学,wxid_demo_0001,同学,你好\r\n'],{type:'text/csv;charset=utf-8'}); const link=document.createElement('a'); link.href=URL.createObjectURL(blob); link.download='好友申请_模拟模板.csv'; link.click(); setTimeout(()=>URL.revokeObjectURL(link.href),1000); toast('模拟 CSV 模板已下载');};
  $('#contact-search').oninput=renderContacts; $('#include-special').onchange=renderContacts;
  $('#clear-contact-search').onclick=()=>{$('#contact-search').value=''; renderContacts(); $('#contact-search').focus();};
  $('#toggle-contact-source').onclick=()=>{$('#contact-source').hidden=!$('#contact-source').hidden;};
  $('#detect-directory').onclick=()=>{$('#contact-directory').value='C:\\Users\\User\\xwechat_files'; toast('已选定模拟微信数据目录');};
  $('#browse-directory').onclick=()=>toast('已选择模拟目录：xwechat_files');
  $('#refresh-accounts').onclick=()=>toast('已刷新，发现 2 个模拟账号');
  $('#contact-account').onchange=()=>{contacts=[]; $('#contact-stage').textContent='等待读取联系人'; renderContacts();};
  $('#read-contacts').onclick=startContactRead; $('#cancel-read').onclick=cancelContactRead;
  $('#clear-contacts').onclick=()=>confirm('清空联系人','清空本次读取的联系人？源数据库不会受到影响。',()=>{contacts=[]; $('#contact-stage').textContent='等待读取联系人'; renderContacts();});
  $('#export-contacts').onclick=()=>{$('#export-count').textContent=`${filteredContacts().length} 位联系人`; openDialog('export-dialog');};
  $('#export-confirm').onclick=()=>{const count=filteredContacts().length; const name=$('#export-name').value.trim(); if (!name) {toast('请输入文件名',true); return;} closeDialog('export-dialog'); toast(`模拟导出完成 · ${count} 条 · ${$('#export-format').selectedOptions[0].textContent}`);};
  $('#pause-task').onclick=()=>{if (!task?.active || task.phase==='cleanup') return; task.paused=!task.paused; if(task.paused) task.clock.pause(); else task.clock.resume(); log(task.paused?'任务已暂停，累计计时停止':'任务已继续'); renderTask();};
  $('#stop-task').onclick=()=>finishTask('任务已手动停止');
  $('#return-editor').onclick=()=>{if(task?.active)return; task.showEditor=true; renderWorkspace();};
  $('#sidebar-task').onclick=()=>{if(task){workspace=task.kind; task.showEditor=false; renderWorkspace();}};
  $('#task-scenario').onclick=()=>openDialog('scenario-dialog');
  $('#confirm-accept').onclick=()=>{closeDialog('confirm-dialog'); const action=confirmation; confirmation=null; action?.();};
  $('#window-minimize').onclick=()=>{$('.app').classList.toggle('minimized'); $('#window-minimize').innerHTML=icon($('.app').classList.contains('minimized')?'panel-top-open':'minus'); icons();};
  $('#window-maximize').onclick=()=>{$('.app').classList.toggle('maximized'); document.body.classList.toggle('maximized');};
  $('#window-close').onclick=()=>confirm('关闭交互样例','关闭当前样例窗口？可随时重新打开。',()=>{$('.app').hidden=true; $('#restore-window').hidden=false;});
  $('#restore-button').onclick=()=>{$('.app').hidden=false; $('.app').classList.remove('minimized'); $('#restore-window').hidden=true;};

  ['message-min','message-max','friend-min','friend-max'].forEach(id=>{
    const input=document.getElementById(id); input.addEventListener('change',()=>saveInterval(id)); input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault(); saveInterval(id);}});
  });
  $('#batch-limit').addEventListener('change',saveBatchLimit);
  $('#batch-limit').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault(); saveBatchLimit();}});
  const settingBindings={'fuzzy-search':['fuzzy','checked'], 'default-greeting':['greeting','value'], 'default-suffix':['suffix','value'], 'unknown-policy':['unknownPolicy','value'], 'safe-retries':['safeRetries','checked'], 'recovery-policy':['recoveryPolicy','value'], 'login-timeout':['loginTimeout','value'], 'glass-enabled':['glass','checked'], 'glass-opacity':['opacity','value']};
  Object.entries(settingBindings).forEach(([id,[key,property]])=>{
    document.getElementById(id).addEventListener('change',()=>{
      const appearance=['glass','opacity'].includes(key);
      if (busy()&&!appearance) {syncSettings(); return;}
      let value=document.getElementById(id)[property];
      if (['loginTimeout','opacity'].includes(key)) {value=M.integer(value); if(!Number.isFinite(value)||value<(key==='opacity'?45:1)||value>(key==='opacity'?95:300)){toast('数值超出范围，已恢复保存值',true); syncSettings(); return;}}
      prefs[key]=value; persist();
      if(key==='greeting') $('#global-greeting').value=value;
      if(key==='suffix') $('#global-suffix').value=value;
      if(appearance) {applyGlass(); $('#glass-value').textContent=`${prefs.opacity}%`;}
      renderMessage(); renderFriends();
    });
  });
  $('#glass-opacity').addEventListener('input',()=>{$('#glass-value').textContent=`${$('#glass-opacity').value}%`;});
  $('#reset-settings').onclick=()=>confirm('恢复默认设置','恢复本样例的默认参数与浅色外观？名单不会清空。',()=>{Object.assign(prefs,{...defaults,messageInterval:[2,3],friendInterval:[15,30]}); let count=0; friends.forEach(row=>{if(row.selected&&++count>prefs.batchLimit)row.selected=false;}); $('#global-greeting').value=prefs.greeting; $('#global-suffix').value=prefs.suffix; setTheme(prefs.theme); applyGlass(); applySidebar(); syncSettings(); renderMessage(); renderFriends();});

  document.addEventListener('focusin',event=>{if(event.target.matches('input.text-edit, textarea.text-edit'))remember(event.target);});
  document.addEventListener('beforeinput',event=>{if(event.target.matches('input.text-edit, textarea.text-edit'))remember(event.target);});
  document.addEventListener('input',event=>{if(event.target.matches('input.text-edit, textarea.text-edit'))recordInput(event.target);});
  document.addEventListener('contextmenu',event=>{
    const field=event.target.closest('input.text-edit,textarea.text-edit');
    if(field){event.preventDefault();textMenu(field,event.clientX,event.clientY);return;}
    const row=event.target.closest('#friend-table tr[data-index]');
    if(row){event.preventDefault();const index=Number(row.dataset.index);selectFriendRow(index);rowMenu(index,event.clientX,event.clientY);return;}
    const cell=event.target.closest('#contact-table td');
    if(cell){event.preventDefault();openMenu([{label:'复制单元格',icon:'copy',shortcut:'Ctrl+C',disabled:!cell.textContent,run:()=>{copyText(cell.textContent);toast('单元格已复制');}}],event.clientX,event.clientY,cell);}
  });
  document.addEventListener('keydown',event=>{
    const field=event.target.closest?.('input.text-edit,textarea.text-edit');
    if(field&&(event.ctrlKey||event.metaKey)&&['z','y'].includes(event.key.toLowerCase())){event.preventDefault();undo(field,event.key.toLowerCase()==='y'||event.shiftKey);}
    if(field&&(event.key==='ContextMenu'||event.key==='F10'&&event.shiftKey)){event.preventDefault();const rect=field.getBoundingClientRect();textMenu(field,rect.left+20,rect.top+25);}
    if(event.key==='Escape'){
      if(!$('#context-menu').hidden || !$('#combo-menu').hidden){event.preventDefault();event.stopPropagation();closeMenus(true);}
      $('#health-popover').hidden=true;hideTooltip();
    }
    const menu=event.target.closest?.('#context-menu,#combo-menu');
    if(menu&&['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();const buttons=[...menu.querySelectorAll('button:not(:disabled)')];const index=buttons.indexOf(document.activeElement);buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus();}
    const cell=event.target.closest?.('#contact-table td');if(cell&&(event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='c'){event.preventDefault();copyText(cell.textContent);toast('单元格已复制');}
  });
  document.addEventListener('pointerdown',event=>{
    if(!event.target.closest('#context-menu,#combo-menu,#suffix-options'))closeMenus();
    if(!event.target.closest('#health-status,#health-popover'))$('#health-popover').hidden=true;
    hideTooltip();
  });
  document.addEventListener('pointerover',event=>{
    const target=event.target.closest('[data-tooltip]'); if(!target?.dataset.tooltip||target.disabled)return;
    hideTooltip(); tooltipTimer=setTimeout(()=>{const rect=target.getBoundingClientRect();$('#tooltip').textContent=target.dataset.tooltip;placePopup($('#tooltip'),rect.left,rect.bottom+7);},600);
  });
  document.addEventListener('pointerout',event=>{if(event.target.closest?.('[data-tooltip]'))hideTooltip();});
  window.addEventListener('resize',()=>{closeMenus();hideTooltip();});
  $$('dialog').forEach(dialog=>{
    dialog.addEventListener('cancel',event=>{event.preventDefault();closeDialog(dialog.id);});
    dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)closeDialog(dialog.id);}});
  });
  $('#large-image').addEventListener('error',()=>{closeDialog('image-dialog');toast('图片无法读取，请检查文件',true);});
  window.addEventListener('beforeunload',()=>attachments.filter(item=>item.owned).forEach(item=>URL.revokeObjectURL(item.url)));

  $('#global-greeting').value=prefs.greeting; $('#global-suffix').value=prefs.suffix;
  $('#preview-date').textContent=new Date().toLocaleString('zh-CN',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});
  applySidebar();setTheme(prefs.theme);applyGlass();syncSettings();renderMessage();renderFriends();renderContacts();renderWorkspace();
  setInterval(tick,100);
  window.fugePreview={setTheme:theme=>{setTheme(theme);applyGlass();}};
})();
