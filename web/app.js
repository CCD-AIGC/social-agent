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
  if (view === 'drafts') {
    loadDrafts();
    renderDraftPlatforms();
  }
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
    $$('#activity-table tr').forEach((tr, index) => {
      const row = rows[index];
      if (row?.action !== 'remote_draft') return;
      const button = document.createElement('button');
      button.className = 'text-button';
      button.textContent = draftStatuses[row.status] || row.status;
      tr.cells[3].replaceChildren(button);
      tr.cells[4].textContent = { official_api: '官方 API', sau: 'SAU', creator_handoff: '创作中心交接' }[row.request.route] || '—';
      button.addEventListener('click', async () => {
        setView('publish');
        try {
          const latest = await request('/api/remote-drafts?operation=' + row.id);
          if (latest.status === 'handoff_ready' && latest.request.draft_path) {
            const handoff = await postJson('/api/remote-drafts/handoff', {
              draft_path: latest.request.draft_path, platform: latest.platform, account: latest.request.alias,
            });
            if (handoff.status === 'handoff_ready') {
              $('#remote-draft-result').hidden = false;
              showHandoff(handoff);
              return;
            }
          }
          await drawRemoteDraft(latest);
        }
        catch (error) { showToast(error.message, true); }
      });
    });
  } catch (error) {
    $('#activity-table').innerHTML = `<tr><td colspan="5"><div class="empty-state">${escapeHtml(error.message)}</div></td></tr>`;
  }
}

let researchSources;

function researchUrl(value) {
  try {
    const url = new URL(value);
    if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) return url.href;
  } catch { return null; }
  return null;
}

async function loadResearch() {
  const table = $('#research-table');
  table.innerHTML = '<tr><td colspan="4"><div class="empty-state">正在读取调研源…</div></td></tr>';
  try {
    const select = $('#research-platform');
    if (!researchSources) {
      researchSources = await request('/api/research/sources');
      select.replaceChildren(...researchSources.map((source) => new Option(source.name, source.id)));
    }
    const source = researchSources.find((item) => item.id === select.value);
    const count = $('#research-limit');
    const choices = [10, 20, source.max_limit === 25 ? 25 : 30];
    const wanted = Number(count.value) || 10;
    const limit = choices.includes(wanted) ? wanted : choices[2];
    count.replaceChildren(...choices.map((n) => new Option(n, n)));
    count.value = String(limit);
    $('#research-heading').textContent = source.name;
    $('#research-source').textContent = '数据源：' + source.provider;
    const data = await request('/api/research?' + new URLSearchParams({ platform: source.id, limit }));
    if (select.value !== source.id || Number(count.value) !== limit) return;
    $('#research-updated').textContent = '更新于 ' + new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    const items = data.result?.items || [];
    table.innerHTML = items.length ? items.map((item) => {
      const title = item.keyword || item.title || '—';
      const url = researchUrl(item.url);
      return '<tr><td class="rank-cell">' + escapeHtml(item.rank || '—') + '</td><td><strong>' + escapeHtml(title)
        + '</strong>' + (url ? ' <a class="table-link" href="' + escapeAttr(url) + '" target="_blank" rel="noreferrer">原文 ↗</a>' : '')
        + '</td><td class="heat-cell">' + escapeHtml(formatNumber(item.heat))
        + '</td><td><button class="table-link" data-topic="' + escapeAttr(title) + '">写入草稿 →</button></td></tr>';
    }).join('') : '<tr><td colspan="4"><div class="empty-state">暂无数据</div></td></tr>';
    $$('#research-table [data-topic]').forEach((button) => button.addEventListener('click', () => {
      setView('drafts');
      $('#draft-form input[name="title"]').value = button.dataset.topic;
      showToast('已把调研主题填入草稿标题');
    }));
  } catch (error) {
    table.innerHTML = '<tr><td colspan="4"><div class="empty-state">' + escapeHtml(error.message) + '</div></td></tr>';
  }
}

async function loadDrafts() {
  try {
    const drafts = await request('/api/drafts');
    state.drafts = drafts;
    const list = $('#draft-list');
    list.innerHTML = drafts.length ? drafts.map((draft) => `<div class="draft-item"><div class="draft-title">${escapeHtml(draft.title || draft.id)}</div><div class="draft-meta">${escapeHtml(draft.platforms.join(' · '))}<br>${formatDate(draft.created_at)}</div><div class="draft-actions"><button data-draft-preview="${escapeAttr(draft.path)}">去预览</button><button data-draft-copy="${escapeAttr(draft.path)}">复制路径</button></div></div>`).join('') : '<div class="empty-state">还没有本地草稿</div>';
    const select = $('#publish-draft-select');
    const selected = select.value;
    select.innerHTML = '<option value="">请选择本地草稿</option>' + drafts.map((draft) => `<option value="${escapeAttr(draft.path)}">${escapeHtml(draft.title || draft.id)}</option>`).join('');
    if (drafts.some((draft) => draft.path === selected)) select.value = selected;
    $$('[data-draft-preview]').forEach((button) => button.addEventListener('click', () => { setView('publish'); $('#publish-draft-select').value = button.dataset.draftPreview; }));
    $$('[data-draft-copy]').forEach((button) => button.addEventListener('click', async () => { await navigator.clipboard.writeText(button.dataset.draftCopy); showToast('草稿路径已复制'); }));
  } catch (error) {
    $('#draft-list').innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  }
}

const platformLabels = { xiaohongshu: '小红书', wechat_mp: '微信公众号', wechat_channels: '微信视频号', douyin: '抖音', zhihu: '知乎', youtube: 'YouTube', bilibili: 'B 站' };

async function renderDraftPlatforms(target) {
  const field = $('#draft-platforms');
  const selected = target ? [target] : [...field.querySelectorAll('input:checked')].map((input) => input.value);
  try {
    const platforms = state.platforms.length ? state.platforms : await request('/api/platforms');
    const current = [...field.querySelectorAll('input:checked')].map((input) => input.value);
    const values = target ? selected : current.length ? current : ['bilibili'];
    field.replaceChildren(...platforms.map((platform) => {
      const label = document.createElement('label');
      const input = document.createElement('input');
      Object.assign(input, { type: 'checkbox', name: 'platforms', value: platform.id, checked: values.includes(platform.id) });
      label.append(input, ' ' + platform.name);
      return label;
    }));
  } catch (error) {
    showToast(error.message, true);
  }
}

function postJson(path, body) {
  return request(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}

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
      const connector = platform.id === 'wechat_mp' ? '官方接口 · 图文草稿' : platform.id === 'wechat_channels' ? '视频草稿交接' : platform.id === 'xiaohongshu' ? '官方报表 · 本地读取' : platform.connector_installed ? '检测到本机连接器' : 'Social Agent 连接器待接入';
      return `<article class="platform-card"><div class="platform-card-head"><div class="platform-mark ${escapeAttr(platform.id)}">${escapeHtml(platform.mark)}</div><div class="platform-heading"><strong>${escapeHtml(platform.name)}</strong><small>${connector}</small></div><span class="connection-pill ${escapeAttr(stateClass)}">${stateLabel}</span></div><div class="platform-auth">${escapeHtml(platform.auth)}</div><div class="capability-line">${platform.available.map((item) => `<span class="capability-chip">${escapeHtml(item)}</span>`).join('')}${platform.planned.map((item) => `<span class="capability-chip pending">${escapeHtml(item)} · 待接入</span>`).join('')}</div><div class="platform-actions"><button class="button ${platform.id === 'bilibili' ? 'button-primary' : 'button-quiet'}" data-connect-platform="${escapeAttr(platform.id)}">${{ bilibili: '查看稿件与连接', xiaohongshu: '查看笔记数据', wechat_mp: '设置接口账号' }[platform.id] || '查看接入步骤'}</button><button class="button button-quiet" data-create-platform="${escapeAttr(platform.id)}">创建平台草稿</button><a class="outline-button" href="${escapeAttr(platform.creator_url || platform.url)}" target="_blank" rel="noreferrer">打开创作中心</a></div></article>`;
    }).join('');
    $$('[data-connect-platform]').forEach((button) => button.addEventListener('click', () => {
      const platformId = button.dataset.connectPlatform;
      showIntegration(platformId, platforms);
      $('#integration-placeholder').scrollIntoView({ block: 'start' });
    }));
    $$('[data-create-platform]').forEach((button) => button.addEventListener('click', () => {
      const target = button.dataset.createPlatform;
      setView('drafts');
      renderDraftPlatforms(target);
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
  if (platformId === 'wechat_mp') {
    showWechatMP();
    return;
  }
  if (platformId === 'wechat_channels') {
    $('#integration-placeholder').textContent = '在发布预览中准备视频号草稿交接，再打开视频号助手核对账号并保存草稿。重新打开草稿后可登记核验结果。';
    return;
  }
  if (platformId === 'bilibili' && platform.connected) {
    const area = $('#integration-placeholder');
    area.innerHTML = '<div><strong>B 站 · bili-cli</strong><p>投稿和定时通过本机 bili-cli 执行。工作台可复查已有稿件。</p>'
      + '<button class="button button-quiet" data-load-works>查看最近稿件</button><div data-works-result></div></div>';
    area.querySelector('[data-load-works]').onclick = async () => {
      const output = area.querySelector('[data-works-result]');
      output.textContent = '正在读取稿件…';
      try {
        const works = await request('/api/bilibili/works');
        const list = document.createElement('ul');
        for (const item of works) {
          const row = document.createElement('li');
          row.textContent = [item.title, item.state_desc, item.bvid].filter(Boolean).join(' · ');
          list.append(row);
        }
        output.replaceChildren(works.length ? list : '暂无稿件');
      } catch (error) {
        output.textContent = error.message;
      }
    };
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

function showWechatMP() {
  const area = $('#integration-placeholder');
  area.innerHTML = '<div><strong>微信公众号 · 官方 API</strong><p>在公众号后台查看 AppID、AppSecret 和接口 IP 白名单。凭证保存在这台 Mac 的钥匙串。</p>'
    + '<form id="wechat-account-form" class="form-stack"><label>本机账号别名<input name="account" required maxlength="100" /></label>'
    + '<label>AppID<input name="app_id" required autocomplete="off" /></label>'
    + '<label>AppSecret<input name="secret" type="password" required autocomplete="new-password" /></label>'
    + '<div class="form-actions"><button class="button button-primary">保存并检查草稿权限</button>'
    + '<button type="button" class="button button-quiet" id="wechat-probe">检查已保存账号</button></div>'
    + '<span role="status" id="wechat-account-status"></span></form></div>';
  const form = $('#wechat-account-form');
  async function check(save) {
    const fields = new FormData(form);
    const account = fields.get('account').trim();
    const output = $('#wechat-account-status');
    for (const button of form.querySelectorAll('button')) button.disabled = true;
    output.textContent = '正在检查官方草稿接口…';
    try {
      if (save) {
        await postJson('/api/accounts/wechat-mp', Object.fromEntries(fields));
        form.elements.secret.value = '';
      }
      const data = await request('/api/accounts/probe?platform=wechat_mp&account=' + encodeURIComponent(account));
      output.textContent = data.account + '已验证草稿读取权限，草稿箱内有 ' + data.status.draft_count + ' 条。';
    } catch (error) {
      output.textContent = error.message;
    } finally {
      for (const button of form.querySelectorAll('button')) button.disabled = false;
    }
  }
  form.addEventListener('submit', (event) => { event.preventDefault(); check(true); });
  $('#wechat-probe').addEventListener('click', () => check(false));
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

async function saveMedia(file, kind) {
  if (!file?.size) return null;
  const data = await request('/api/draft-media?kind=' + kind, {
    method: 'POST', headers: { 'Content-Type': file.type }, body: file,
  });
  return data.path;
}

async function submitDraft(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const platforms = form.getAll('platforms');
  if (!platforms.length) { showToast('至少选择一个目标平台', true); return; }
  $('#draft-form-status').textContent = '正在保存…';
  try {
    const video = await saveMedia(form.get('video'), 'video');
    const cover = await saveMedia(form.get('cover'), 'cover');
    const data = await postJson('/api/drafts', {
      title: form.get('title'), body: form.get('body'), platforms,
      tags: String(form.get('tags') || '').split(',').map((value) => value.trim()).filter(Boolean),
      media: video ? [video] : [], cover, ai_generated: form.has('ai_generated'),
    });
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
    $('#remote-draft-result').hidden = true;
    delete $('#remote-draft-result').dataset.operation;
    const accounts = (await request('/api/accounts')).filter((account) => account.platform === 'wechat_mp');
    const onSAU = targets.filter((target) => target.media_count && ['wechat_channels', 'xiaohongshu'].includes(target.platform));
    const sau = Object.fromEntries(await Promise.all(onSAU.map(async (target) => [
      target.platform, await request('/api/sau/accounts?platform=' + target.platform),
    ])));
    $('#preview-result').innerHTML = '<div class="preview-grid">' + targets.map((target) => {
      const platform = platformLabels[target.platform] || target.platform;
      return '<div class="preview-item"><div class="preview-platform">' + escapeHtml(platform) + '</div>'
        + '<div class="preview-summary"><strong>' + escapeHtml(target.title) + '</strong><p>' + escapeHtml(target.body_preview)
        + '</p><small>' + target.media_count + ' 个素材' + (target.cover ? ' · 有封面' : '') + (target.ai_generated ? ' · AI 辅助制作' : '')
        + '</small></div><div class="preview-status">本地预览</div>' + remoteActions(target, accounts) + sauAction(target, sau[target.platform]) + '</div>';
    }).join('') + '</div>';
    $$('#preview-result form').forEach((form) => form.addEventListener('submit', (event) => {
      event.preventDefault();
      const button = event.submitter || form.querySelector('button');
      if (form.dataset.sauLogin) startSauLogin(form, button);
      else if (form.dataset.sau) submitSau(form, draftPath, button);
      else submitRemoteDraft(form, draftPath, button);
    }));
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
$('#research-platform').addEventListener('change', loadResearch);
$('#research-limit').addEventListener('change', loadResearch);
const draftStatuses = {
  queued: '等待平台操作', running: '正在保存', needs_verification: '待核对', failed: '未保存',
  verified: '已通过官方 API 回读', handoff_ready: '已准备交接', verified_manually: '已人工复查',
  superseded: '已由后续任务接替', verified_platform: '已从平台回读',
};

function remoteActions(target, accounts) {
  if (!['wechat_mp', 'xiaohongshu', 'wechat_channels'].includes(target.platform)) return '';
  const options = accounts.map(({ alias }) => '<option value="' + escapeAttr(alias) + '">' + escapeHtml(alias) + '</option>').join('');
  if (target.platform === 'wechat_mp') {
    const article = options
      ? '<label>公众号接口账号<select name="account" required>' + options + '</select></label>'
        + '<button class="button button-quiet" value="article">保存公众号图文草稿</button>'
      : '<small>要走官方 API，请先到平台接入设置公众号。</small>';
    return article && options
      ? '<form class="form-stack" data-platform="wechat_mp">' + article + '</form>'
        + (target.media_count ? handoffForm(target.platform) : '')
      : '<p>' + article + '</p>' + (target.media_count ? handoffForm(target.platform) : '');
  }
  return target.media_count ? handoffForm(target.platform) : '<p>选择视频后可准备平台草稿交接。</p>';
}

function sauAction(target, setup) {
  if (!setup) return '';
  if (!setup.installed) return '<p>安装 SAU 后可使用视频自动化。</p>';
  const alias = setup.accounts[0] || '';
  const login = sauLoginForm(target.platform, alias);
  if (!setup.accounts.length) return login;
  const options = setup.accounts.map((alias) => '<option value="' + escapeAttr(alias) + '">' + escapeHtml(alias) + '</option>').join('');
  const scheduled = setup.mode === 'schedule';
  const label = scheduled ? '确认定时发送' : '自动保存视频草稿';
  const confirm = scheduled
    ? '我已核对扫码使用的账号，确认作品到时自动发表'
    : '我已核对扫码使用的账号，确认保存视频草稿';
  return '<form class="form-stack" data-sau="' + setup.mode + '" data-platform="' + escapeAttr(target.platform) + '">'
    + '<label>SAU 本机别名<select name="account" required><option value="">选择本机别名</option>' + options + '</select></label>'
    + '<small>别名由你填写。请确认当时用来扫码的是目标平台账号。</small>'
    + (scheduled ? '<label>小红书后台昵称<input name="expected_account" maxlength="100" required></label>'
      + '<label>发布时间（北京时间）<input name="scheduled" type="datetime-local" value="'
      + escapeAttr(setup.default_schedule) + '" required></label>' : '')
    + '<label><input type="checkbox" name="confirmed" required> ' + confirm + '</label>'
    + '<button class="button button-quiet">' + label + '</button></form>'
    + '<details><summary>SAU 登录</summary>' + login + '</details>';
}

function sauLoginForm(platform, alias) {
  return '<form class="form-stack" data-sau-login="' + escapeAttr(platform) + '">'
    + '<label>SAU 本机别名<input name="account" required maxlength="64" placeholder="如：主号或测试号" value="' + escapeAttr(alias) + '"></label>'
    + '<button class="button button-quiet">打开扫码窗口</button>'
    + '<small role="status">在弹出的窗口中扫码，等待登录完成。</small></form>';
}

async function startSauLogin(form, button) {
  const platform = form.dataset.sauLogin;
  const alias = form.elements.account.value.trim();
  const status = form.querySelector('[role="status"]');
  button.disabled = true;
  status.textContent = '正在启动扫码窗口…';
  try {
    await postJson('/api/sau/login', { platform, account: alias });
    status.textContent = '请在弹出的窗口扫码并确认，等登录完成。';
    while (form.isConnected) {
      await new Promise((resolve) => setTimeout(resolve, 1800));
      const data = await request('/api/sau/accounts?platform=' + platform);
      if (data.login?.running) continue;
      if (data.login?.exit_code === 0 && data.accounts.includes(alias)) {
        showToast('SAU 扫码成功，已载入账号');
        await previewPublish();
      } else {
        status.textContent = '登录未完成。窗口关闭或扫码超时后，可以重新打开。';
      }
      return;
    }
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function submitSau(form, draftPath, button) {
  if (!form.elements.confirmed.checked) return;
  const area = $('#remote-draft-result');
  area.hidden = false;
  delete area.dataset.operation;
  area.textContent = '正在登记 SAU 操作…';
  button.disabled = true;
  try {
    const row = await postJson('/api/sau/video', {
      draft_path: draftPath, platform: form.dataset.platform, account: form.elements.account.value,
      mode: form.dataset.sau, expected_account: form.elements.expected_account?.value,
      scheduled: form.elements.scheduled?.value, confirmed: true,
    });
    form.elements.confirmed.checked = false;
    await drawRemoteDraft(row);
  } catch (error) {
    area.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function handoffForm(platform) {
  return '<form class="form-stack" data-platform="' + escapeAttr(platform) + '">'
    + '<label>平台账号<input name="account" required maxlength="100" placeholder="填写创作后台显示的账号名称"></label>'
    + '<button class="button button-quiet" value="handoff">准备视频草稿交接</button></form>';
}

async function submitRemoteDraft(form, draftPath, button) {
  const account = form.elements.account.value.trim();
  const area = $('#remote-draft-result');
  area.hidden = false;
  delete area.dataset.operation;
  area.textContent = '正在准备草稿…';
  button.disabled = true;
  try {
    const payload = { account, platform: form.dataset.platform, draft_path: draftPath };
    const path = button.value === 'handoff' ? '/api/remote-drafts/handoff' : '/api/remote-drafts';
    const result = await postJson(path, payload);
    if (result.status === 'handoff_ready') showHandoff(result);
    else await drawRemoteDraft(result);
  } catch (error) {
    area.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function drawRemoteDraft(row, area = $('#remote-draft-result')) {
  area.hidden = false;
  area.dataset.operation = row.id;
  area.textContent = (draftStatuses[row.status] || row.status) + ' · ' + row.request.alias + ' · ' + row.request.title;
  if (row.request.scheduled_at) {
    area.append(document.createElement('br'), '请求排期（北京时间） ' + row.request.scheduled_at.slice(0, 16).replace('T', ' '));
  }
  if (row.result?.message) area.append(document.createElement('br'), row.result.message);
  if (row.result?.error) area.append(document.createElement('br'), row.result.error.message);
  if (row.result?.reference) area.append(document.createElement('br'), '平台编号 ' + row.result.reference);
  if (row.result?.scope) area.append(document.createElement('br'), row.result.scope === 'browser' ? '此浏览器草稿' : '平台账号草稿');
  if (row.request.route === 'official_api' && ['verified', 'needs_verification'].includes(row.status)) {
    const verify = document.createElement('button');
    verify.textContent = '回读平台草稿';
    verify.className = 'button button-quiet';
    const reference = document.createElement('input');
    reference.placeholder = '平台草稿编号';
    if (!row.result?.reference && row.result?.cover_id) area.append(document.createElement('br'), reference);
    verify.addEventListener('click', async () => {
      verify.disabled = true;
      try { await drawRemoteDraft(await postJson('/api/remote-drafts/verify', { operation: row.id, reference: reference.value }), area); }
      catch (error) { showToast(error.message, true); }
      finally { verify.disabled = false; }
    });
    area.append(document.createElement('br'), verify);
  }
  if (row.request.route === 'sau' && row.status === 'needs_verification') {
    const isPublish = ['publish', 'schedule'].includes(row.request.mode);
    const holder = document.createElement('div');
    holder.innerHTML = '<p><a class="outline-button" href="' + escapeAttr(row.request.creator_url)
      + '" target="_blank" rel="noreferrer">打开创作后台复查</a></p>'
      + '<form class="form-stack"><label>复查所用 SAU 账号<input name="account" required maxlength="64"></label>'
      + '<label>平台编号或作品链接<input name="reference" maxlength="160"' + (isPublish ? ' required' : '') + '></label>'
      + '<label><input type="checkbox" required> 我已在后台重新打开并核对作品'
      + (row.request.mode === 'schedule' ? '与实际排期' : '') + '</label>'
      + '<button class="button button-quiet">登记复查结果</button></form>';
    holder.querySelector('form').onsubmit = async (event) => {
      event.preventDefault();
      try {
        const result = await postJson('/api/remote-drafts/receipt', {
          operation: row.id, scope: 'account', ...Object.fromEntries(new FormData(event.target)),
        });
        await drawRemoteDraft(result, area);
      } catch (error) { showToast(error.message, true); }
    };
    area.append(holder);
  }
  if (['running', 'queued'].includes(row.status)) {
    await new Promise((resolve) => setTimeout(resolve, 1200));
    if (area.isConnected && !area.hidden && area.dataset.operation === row.id) {
      const latest = await request('/api/remote-drafts?operation=' + row.id);
      if (!area.hidden && area.dataset.operation === row.id) await drawRemoteDraft(latest, area);
    }
  }
}

function showHandoff(row) {
  const area = $('#remote-draft-result');
  area.dataset.operation = row.id;
  const { title, body, tags, video, cover } = row.handoff;
  area.innerHTML = '<div><strong>视频草稿交接 · ' + escapeHtml(row.request.alias) + '</strong>'
    + '<p>' + escapeHtml(title) + '</p><p>' + escapeHtml(body) + '</p>'
    + '<p>视频 ' + escapeHtml(video) + '</p>' + (cover ? '<p>封面 ' + escapeHtml(cover) + '</p>' : '')
    + '<div class="form-actions"><button class="button button-quiet" data-copy-note>复制文案</button>'
    + '<button class="button button-quiet" data-copy-video>复制视频路径</button>'
    + '<a class="outline-button" href="' + escapeAttr(row.request.creator_url) + '" target="_blank" rel="noreferrer">打开创作后台</a></div>'
    + '<form class="form-stack"><label>复查所用账号<input name="account" required maxlength="100"></label>'
    + '<label>草稿保存范围<select name="scope"><option value="account">平台账号草稿</option><option value="browser">此浏览器草稿</option></select></label>'
    + '<label>平台编号（可选）<input name="reference" maxlength="160"></label>'
    + '<label><input type="checkbox" required> 我已重新打开草稿并核对视频和标题</label>'
    + '<button class="button button-primary">登记复查结果</button></form></div>';
  area.querySelector('[data-copy-note]').onclick = () => navigator.clipboard.writeText([title, body, tags.map((tag) => '#' + tag).join(' ')].join('\n\n'));
  area.querySelector('[data-copy-video]').onclick = () => navigator.clipboard.writeText(video);
  area.querySelector('form').onsubmit = async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const receipt = await postJson('/api/remote-drafts/receipt', { operation: row.id, ...Object.fromEntries(new FormData(event.target)) });
      await drawRemoteDraft(receipt);
    } catch (error) { showToast(error.message, true); }
    finally { button.disabled = false; }
  };
}

$('#draft-form').addEventListener('submit', submitDraft);
$('#draft-refresh').addEventListener('click', loadDrafts);
$('#preview-button').addEventListener('click', previewPublish);
$('#report-refresh').addEventListener('click', loadReport);
$('#platform-refresh').addEventListener('click', loadPlatforms);
document.querySelector('[data-action="open-account"]').addEventListener('click', () => { setView('overview'); $('#profile-link').focus(); });

loadOverview().catch((error) => showToast(error.message, true));
