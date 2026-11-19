const state = { drafts: [], currentView: 'overview', profile: null, metrics: null, platforms: [], selectedPlatform: null };

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function showToast(message, isError = false) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.style.background = isError ? '#913f3f' : '#23362d';
  toast.classList.add('is-visible');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('is-visible'), 3000);
}

async function request(url, options = {}) {
  const response = await fetch(url, { headers: { Accept: 'application/json', ...(options.headers || {}) }, ...options });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error?.message || '请求失败');
  }
  return payload.data;
}

function setView(view) {
  state.currentView = view;
  $$('.nav-item').forEach((item) => item.classList.toggle('is-active', item.dataset.view === view));
  $$('[data-view-panel]').forEach((panel) => panel.classList.toggle('is-visible', panel.dataset.viewPanel === view));
  const titles = { overview: '运营总览', platforms: '平台接入', research: '选题调研', drafts: '内容草稿', publish: '发布预览', activity: '操作记录' };
  $('#page-title').textContent = titles[view] || '运营总览';
  if (view === 'platforms') loadPlatforms();
  if (view === 'research') loadResearch();
  if (view === 'drafts') loadDrafts();
  if (view === 'publish') loadDrafts();
  if (view === 'activity') loadReport();
}

function formatNumber(value) {
  if (value === undefined || value === null || value === '') return '—';
  return new Intl.NumberFormat('zh-CN').format(value);
}

function formatDate(value) {
  if (!value) return '—';
  return String(value).replace('T', ' ').replace('+00:00', ' UTC');
}

function setSyncLabel() {
  $('#last-sync').textContent = `同步于 ${new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
}

async function loadAccount() {
  try {
    const data = await request('/api/accounts/probe?platform=bilibili');
    const status = data.status || {};
    const user = status.user || data.profile || {};
    const loggedIn = Boolean(status.logged_in);
    $('#account-status').textContent = loggedIn ? '已连接' : '未登录';
    $('#account-name').textContent = loggedIn ? user.name || 'B 站账号' : '请先在 bili-cli 中登录';
    $('#sidebar-account').textContent = loggedIn ? user.name || 'B 站账号' : '未登录';
    $('#profile-name').textContent = loggedIn ? user.name || 'B 站账号' : '未登录';
    $('#profile-meta').textContent = loggedIn ? `UID ${user.mid || '—'} · Lv.${user.level || '—'}` : 'bili-cli 登录态不可用';
    $('#profile-avatar').textContent = (user.name || 'B').slice(0, 1).toUpperCase();
    if (data.profile?.url) $('#profile-link').href = data.profile.url;
    state.profile = data;
  } catch (error) {
    $('#account-status').textContent = '读取失败';
    $('#account-name').textContent = error.message;
    $('#sidebar-account').textContent = '读取失败';
    showToast(error.message, true);
  }
}

async function loadMetrics() {
  try {
    const data = await request('/api/metrics?platform=bilibili');
    const result = data.result || {};
    state.metrics = result;
    $('#total-plays').textContent = formatNumber(result.totals?.plays);
    $('#total-fans').textContent = formatNumber(result.fans?.total);
    $('#new-fans').textContent = `本周新增 ${formatNumber(result.new_fans?.now)}`;
    $('#metric-date').textContent = `数据日期 ${result.data_date || '—'}`;
    $('#week-plays').textContent = formatNumber(result.plays?.now);
    $('#week-visitors').textContent = formatNumber(result.visitors?.now);
    $('#interacting-percent').textContent = result.fans?.interacting_percent == null ? '—' : `${result.fans.interacting_percent}%`;
    $('#peer-percent').textContent = result.versus_peers?.plays?.better_than_percent == null ? '—' : `${result.versus_peers.plays.better_than_percent}%`;
    const works = result.top_videos_yesterday || [];
    $('#works-list').innerHTML = works.length ? works.map((work, index) => `<div class="work-row"><span class="work-rank">${String(index + 1).padStart(2, '0')}</span><div class="work-info"><div class="work-title">${escapeHtml(work.title || '未命名作品')}</div><div class="work-meta">${escapeHtml(work.bvid || '')}</div></div><span class="work-plays">${formatNumber(work.plays)} 播放</span></div>`).join('') : '<div class="empty-state">暂无作品数据</div>';
  } catch (error) {
    $('#works-list').innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  }
}

async function loadReport() {
  try {
    const data = await request('/api/report');
    const local = data.local || {};
    $('#report-summary').textContent = `${formatNumber(local.operation_count)} 条操作记录`;
    $('#operation-count').textContent = formatNumber(local.operation_count);
    $('#operation-status').textContent = Object.entries(local.operations_by_status || {}).map(([key, value]) => `${key} ${value}`).join(' · ') || '暂无操作';
    const rows = data.recent_operations || [];
    $('#activity-table').innerHTML = rows.length ? rows.map((row) => `<tr><td>${formatDate(row.created_at)}</td><td>${escapeHtml(row.action)}</td><td>${escapeHtml(row.platform || '—')}</td><td><span class="status-text">${escapeHtml(row.status)}</span></td><td>${row.dry_run ? 'dry-run' : 'live'}</td></tr>`).join('') : '<tr><td colspan="5"><div class="empty-state">暂无操作记录</div></td></tr>';
  } catch (error) {
    $('#activity-table').innerHTML = `<tr><td colspan="5"><div class="empty-state">${escapeHtml(error.message)}</div></td></tr>`;
  }
}

async function loadResearch() {
  const table = $('#research-table');
  table.innerHTML = '<tr><td colspan="4"><div class="empty-state">正在读取热搜…</div></td></tr>';
  try {
    const data = await request(`/api/research?platform=bilibili&limit=${encodeURIComponent($('#research-limit').value)}`);
    const result = data.result || {};
    $('#research-source').textContent = `数据源：${result.source || 'bili-cli'}`;
    $('#research-updated').textContent = `更新于 ${new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
    const items = result.items || [];
    table.innerHTML = items.length ? items.map((item) => `<tr><td class="rank-cell">${item.rank || '—'}</td><td><strong>${escapeHtml(item.keyword || item.title || '—')}</strong></td><td class="heat-cell">${formatNumber(item.heat)}</td><td><button class="table-link" data-topic="${escapeAttr(item.keyword || item.title || '')}">写入草稿 →</button></td></tr>`).join('') : '<tr><td colspan="4"><div class="empty-state">暂无热搜数据</div></td></tr>';
    $$('#research-table [data-topic]').forEach((button) => button.addEventListener('click', () => { setView('drafts'); document.querySelector('#draft-form input[name="title"]').value = button.dataset.topic; showToast('已把热搜关键词填入草稿标题'); }));
  } catch (error) {
    table.innerHTML = `<tr><td colspan="4"><div class="empty-state">${escapeHtml(error.message)}</div></td></tr>`;
  }
}

async function loadDrafts() {
  try {
    const drafts = await request('/api/drafts');
    state.drafts = drafts;
    const list = $('#draft-list');
    list.innerHTML = drafts.length ? drafts.map((draft) => `<div class="draft-item"><div class="draft-title">${escapeHtml(draft.title || draft.id)}</div><div class="draft-meta">${escapeHtml(draft.platforms.join(' · '))}<br>${formatDate(draft.created_at)}</div><div class="draft-actions"><button data-draft-preview="${escapeAttr(draft.path)}">去预览</button><button data-draft-copy="${escapeAttr(draft.path)}">复制路径</button></div></div>`).join('') : '<div class="empty-state">还没有本地草稿</div>';
    const select = $('#publish-draft-select');
    select.innerHTML = '<option value="">请选择本地草稿</option>' + drafts.map((draft) => `<option value="${escapeAttr(draft.path)}">${escapeHtml(draft.title || draft.id)}</option>`).join('');
    $$('[data-draft-preview]').forEach((button) => button.addEventListener('click', () => { setView('publish'); $('#publish-draft-select').value = button.dataset.draftPreview; }));
    $$('[data-draft-copy]').forEach((button) => button.addEventListener('click', async () => { await navigator.clipboard.writeText(button.dataset.draftCopy); showToast('草稿路径已复制'); }));
  } catch (error) {
    $('#draft-list').innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  }
}

const platformLabels = { xiaohongshu: '小红书', douyin: '抖音', zhihu: '知乎', youtube: 'YouTube', bilibili: 'B 站' };

function connectionLabel(platform) {
  if (platform.connected) return '已连接';
  return {
    login_required: '需要登录',
    snapshot_ready: '已导入数据',
    import_required: '待导入数据',
  }[platform.state] || '未接入';
}

async function loadPlatforms() {
  const grid = $('#platform-grid');
  grid.innerHTML = '<div class="panel"><div class="empty-state">正在检查平台连接…</div></div>';
  try {
    const platforms = await request('/api/platforms');
    state.platforms = platforms;
    grid.innerHTML = platforms.map((platform) => {
      const stateLabel = connectionLabel(platform);
      const stateClass = platform.connected ? 'connected' : platform.state;
      const connector = platform.id === 'xiaohongshu' ? '官方报表 · 本地读取' : platform.connector_installed ? '检测到本机连接器' : 'Social Agent 连接器待接入';
      return `<article class="platform-card"><div class="platform-card-head"><div class="platform-mark ${escapeAttr(platform.id)}">${escapeHtml(platform.mark)}</div><div class="platform-heading"><strong>${escapeHtml(platform.name)}</strong><small>${connector}</small></div><span class="connection-pill ${escapeAttr(stateClass)}">${stateLabel}</span></div><div class="platform-auth">${escapeHtml(platform.auth)}</div><div class="capability-line">${platform.available.map((item) => `<span class="capability-chip">${escapeHtml(item)}</span>`).join('')}${platform.planned.map((item) => `<span class="capability-chip pending">${escapeHtml(item)} · 待接入</span>`).join('')}</div><div class="platform-actions"><button class="button ${platform.id === 'bilibili' ? 'button-primary' : 'button-quiet'}" data-connect-platform="${escapeAttr(platform.id)}">${{ bilibili: '检查连接', xiaohongshu: '查看笔记数据' }[platform.id] || '查看接入步骤'}</button><button class="button button-quiet" data-create-platform="${escapeAttr(platform.id)}">创建平台草稿</button><a class="outline-button" href="${escapeAttr(platform.url)}" target="_blank" rel="noreferrer">打开创作中心</a></div></article>`;
    }).join('');
    $$('[data-connect-platform]').forEach((button) => button.addEventListener('click', () => {
      const platformId = button.dataset.connectPlatform;
      showIntegration(platformId, platforms);
      if (platformId === 'xiaohongshu') $('#integration-placeholder').scrollIntoView({ block: 'start' });
    }));
    $$('[data-create-platform]').forEach((button) => button.addEventListener('click', () => {
      const target = button.dataset.createPlatform;
      setView('drafts');
      $$('input[name="platforms"]').forEach((input) => { input.checked = input.value === target; });
      showToast(`已选择${platformLabels[target]}草稿目标`);
    }));
    if (state.selectedPlatform) showIntegration(state.selectedPlatform, platforms);
    else $('#integration-placeholder').textContent = '选择一个平台查看当前接入状态与所需步骤。';
  } catch (error) {
    grid.innerHTML = `<div class="panel"><div class="empty-state">${escapeHtml(error.message)}</div></div>`;
  }
}

async function loadOverviewPlatforms() {
  const list = $('#overview-platform-list');
  try {
    const platforms = await request('/api/platforms');
    state.platforms = platforms;
    list.innerHTML = platforms.map((platform) => {
      const status = connectionLabel(platform);
      const statusClass = platform.connected || platform.state === 'snapshot_ready' ? 'is-connected' : 'is-pending';
      const capabilities = platform.connected || platform.connector_installed && platform.id === 'xiaohongshu'
        ? platform.available.slice(0, 3).join('、') : '可创建草稿并生成发布预览';
      return `<div class="channel-row"><div class="channel-identity"><span class="platform-mark ${escapeAttr(platform.id)}">${escapeHtml(platform.mark)}</span><strong>${escapeHtml(platform.name)}</strong></div><span class="channel-state ${statusClass}">${status}</span><span class="channel-capabilities">${escapeHtml(capabilities)}</span><button class="channel-manage" data-manage-platform="${escapeAttr(platform.id)}">平台详情 →</button></div>`;
    }).join('');
    $$('[data-manage-platform]').forEach((button) => button.addEventListener('click', () => {
      const platformId = button.dataset.managePlatform;
      setView('platforms');
      showIntegration(platformId, state.platforms);
    }));
  } catch (error) {
    list.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  }
}

function showIntegration(platformId, platforms) {
  const platform = platforms.find((item) => item.id === platformId);
  if (!platform) return;
  state.selectedPlatform = platformId;
  if (platformId === 'xiaohongshu') {
    showXiaohongshu(platform);
    return;
  }
  const connected = Boolean(platform.connected);
  const details = connected
    ? `<p>${escapeHtml(platform.next_step)}</p><p>当前可用：${platform.available.map(escapeHtml).join('、')}。</p><button class="button button-primary" data-run-connection-check>重新检查 B 站连接</button>`
    : `<p>${escapeHtml(platform.next_step)}</p><ol><li>打开创作中心，只在平台官方页面完成登录或 OAuth。</li><li>当前版本不会读取该平台 Cookie，也没有该平台账号数据连接器。</li><li>登录后仍可创建内容草稿并运行 dry-run；真实发布保持关闭。</li></ol><span class="blocked-pill">未接入：不能读取账号数据或真实发布</span>`;
  $('#integration-placeholder').innerHTML = `<div><strong>${escapeHtml(platform.name)} · ${connected ? '已连接' : '接入步骤'}</strong><div class="integration-copy"><p>认证方式：${escapeHtml(platform.auth)}</p>${details}</div></div>`;
  const check = document.querySelector('[data-run-connection-check]');
  if (check) check.addEventListener('click', async () => {
    check.disabled = true;
    check.textContent = '检查中…';
    try {
      await request('/api/accounts/probe?platform=bilibili');
      showToast('B 站连接正常');
      await loadPlatforms();
      showIntegration('bilibili', await request('/api/platforms'));
    } catch (error) { showToast(error.message, true); }
  });
}

function showXiaohongshu(platform) {
  const panel = $('#integration-placeholder');
  panel.innerHTML = `<div class="xhs-data">
    <strong>小红书笔记数据</strong>
    <p>${escapeHtml(platform.next_step)} <a href="${escapeAttr(platform.url)}" target="_blank" rel="noreferrer">打开内容分析</a></p>
    <p>每个账号保留最近一次导入的报表。</p>
    <form class="xhs-import">
      <label>报表所属账号<input name="account" maxlength="100" required></label>
      <label>笔记明细文件<input name="file" type="file" accept=".xlsx" required></label>
      <button class="button button-primary">导入 XLSX</button>
    </form>
    <div data-xhs-results aria-live="polite">正在读取本地数据…</div>
  </div>`;
  const form = panel.querySelector('form');
  const results = panel.querySelector('[data-xhs-results]');
  const button = form.querySelector('button');

  async function showNotes() {
    const data = await request('/api/metrics?platform=xiaohongshu');
    if (!data.available) {
      results.textContent = data.reason;
      return;
    }
    const { account, imported_at: importedAt, exported_at: exportedAt, note_count: noteCount, notes, totals } = data.result;
    if (!form.elements.account.value) form.elements.account.value = account;
    const fields = [['impressions', '曝光'], ['views', '观看'], ['likes', '点赞'], ['comments', '评论'], ['favorites', '收藏']];
    const totalText = fields.map(([key, label]) => `${label} ${formatNumber(totals[key])}`).join(' · ');
    const signedTime = (value) => new Intl.DateTimeFormat('zh-CN', {
      dateStyle: 'short', timeStyle: 'short', timeZone: 'Asia/Shanghai',
    }).format(new Date(value));
    results.innerHTML = `<p><strong>${escapeHtml(account)}</strong> · ${noteCount} 篇 · 导入于 ${escapeHtml(signedTime(importedAt))}
      ${exportedAt ? ` · 导出于 ${escapeHtml(signedTime(exportedAt))}` : ''}（北京时间）</p>
      <p>${escapeHtml(totalText)}</p>
      ${notes.length ? `<div class="xhs-table" tabindex="0" role="region" aria-label="小红书笔记明细"><table>
        <thead><tr><th>笔记</th><th>发布时间</th>${fields.map(([, label]) => `<th>${label}</th>`).join('')}</tr></thead>
        <tbody>${notes.map((note) => `<tr><td>${escapeHtml(note.title)}</td><td>${escapeHtml(formatDate(note.published_at))}</td>
          ${fields.map(([key]) => `<td>${formatNumber(note[key])}</td>`).join('')}</tr>`).join('')}</tbody>
      </table></div>` : '<p>此报表没有笔记。</p>'}`;
  }

  showNotes().catch((error) => { results.textContent = error.message; });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const file = form.elements.file.files[0];
    const account = form.elements.account.value.trim();
    if (!file || !account) {
      showToast('请选择 XLSX 并填写报表所属账号', true);
      return;
    }
    button.disabled = true;
    try {
      const snapshot = await request('/api/xiaohongshu/import-notes', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          'X-Social-Agent-Account': new URLSearchParams({ account }).toString(),
        },
        body: file,
      });
      form.elements.file.value = '';
      showToast(`已导入 ${snapshot.note_count} 篇笔记`);
      if (state.selectedPlatform === 'xiaohongshu' && state.currentView === 'platforms') {
        await loadPlatforms();
      }
      await loadOverviewPlatforms();
    } catch (error) {
      showToast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
}

async function submitDraft(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const platforms = form.getAll('platforms');
  if (!platforms.length) { showToast('至少选择一个目标平台', true); return; }
  $('#draft-form-status').textContent = '正在保存…';
  try {
    const data = await request('/api/drafts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: form.get('title'), body: form.get('body'), platforms, tags: String(form.get('tags') || '').split(',').map((value) => value.trim()).filter(Boolean), media: [] }) });
    $('#draft-form-status').textContent = `已保存：${data.path}`;
    event.currentTarget.reset();
    showToast('草稿已保存');
    await loadDrafts();
  } catch (error) { $('#draft-form-status').textContent = error.message; showToast(error.message, true); }
}

async function previewPublish() {
  const draftPath = $('#publish-draft-select').value;
  if (!draftPath) { showToast('请先选择草稿', true); return; }
  $('#preview-result').innerHTML = '<div class="empty-state">正在生成预览…</div>';
  try {
    const data = await request('/api/publish-preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ draft_path: draftPath }) });
    const targets = data.targets || [];
    $('#preview-result').innerHTML = `<div class="preview-grid">${targets.map((target) => `<div class="preview-item"><div class="preview-platform">${escapeHtml(target.platform)}</div><div class="preview-summary">${escapeHtml(target.title)} · ${target.body_characters} 字 · ${target.media_count} 个素材</div><div class="preview-status">仅预览</div></div>`).join('')}</div>`;
    showToast('预览已生成，未访问发布接口');
    await loadReport();
  } catch (error) { $('#preview-result').innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`; showToast(error.message, true); }
}

function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char])); }
function escapeAttr(value) { return escapeHtml(value).replace(/`/g, '&#96;'); }

async function loadOverview() {
  await Promise.all([loadAccount(), loadMetrics(), loadReport(), loadOverviewPlatforms()]);
  setSyncLabel();
}

$$('.nav-item').forEach((item) => item.addEventListener('click', () => setView(item.dataset.view)));
$$('[data-view-target]').forEach((item) => item.addEventListener('click', () => setView(item.dataset.viewTarget)));
$('#refresh-button').addEventListener('click', () => { loadOverview(); showToast('正在刷新数据'); });
$('#research-button').addEventListener('click', loadResearch);
$('#draft-form').addEventListener('submit', submitDraft);
$('#draft-refresh').addEventListener('click', loadDrafts);
$('#preview-button').addEventListener('click', previewPublish);
$('#report-refresh').addEventListener('click', loadReport);
$('#platform-refresh').addEventListener('click', loadPlatforms);
document.querySelector('[data-action="open-account"]').addEventListener('click', () => { setView('overview'); $('#profile-link').focus(); });

loadOverview().catch((error) => showToast(error.message, true));
