// ---------- Tabs ----------
const tabs = document.querySelectorAll('.tab');
const panels = document.querySelectorAll('.tab-panel');
let dataPageLoaded = false;

function activateTab(name) {
  tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  panels.forEach(p => p.classList.toggle('active', p.id === `panel-${name}`));
  if (name === 'sql') loadSqlSchema();
  if (name === 'data' && !dataPageLoaded) { dataPageLoaded = true; loadDataPage(1); }
}

tabs.forEach(tab => {
  tab.addEventListener('click', () => {
    activateTab(tab.dataset.tab);
    history.replaceState(null, '', `#${tab.dataset.tab}`);
  });
});

const initialTab = (window.location.hash || '#overview').replace('#', '');

// ---------- KPI Sparklines ----------
(function renderSparklines() {
  document.querySelectorAll('[data-sparkline]').forEach(svg => {
    let points;
    try { points = JSON.parse(svg.getAttribute('data-sparkline')); } catch { return; }
    if (!points || points.length < 2) return;
    const min = Math.min(...points), max = Math.max(...points);
    const range = max - min || 1;
    const stepX = 100 / (points.length - 1);
    const coords = points.map((v, i) => `${(i * stepX).toFixed(1)},${(22 - ((v - min) / range) * 20).toFixed(1)}`);
    const isUp = points[points.length - 1] >= points[0];
    const color = isUp ? '#22D3B8' : '#F76E6E';
    svg.innerHTML = `<polyline points="${coords.join(' ')}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>`;
  });
})();

// ---------- EDA category chip filters ----------
const chipRow = document.getElementById('chartCategoryChips');
let activeCategory = 'all';
if (chipRow) {
  chipRow.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
      chipRow.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      activeCategory = chip.dataset.category;
      applyChartFilter();
    });
  });
}

function applyChartFilter() {
  document.querySelectorAll('#chartGrid .card').forEach(card => {
    const match = activeCategory === 'all' || card.dataset.category === activeCategory;
    card.style.display = match ? '' : 'none';
  });
}

// ---------- Dashboard search (filters Data Preview + Column Profile tables) ----------
const dashboardSearch = document.getElementById('dashboardSearch');
if (dashboardSearch) {
  dashboardSearch.addEventListener('input', () => {
    const q = dashboardSearch.value.trim().toLowerCase();
    ['dataPreviewTable', 'columnProfileTable'].forEach(id => {
      const table = document.getElementById(id);
      if (!table) return;
      table.querySelectorAll('tbody tr').forEach(row => {
        row.style.display = !q || row.textContent.toLowerCase().includes(q) ? '' : 'none';
      });
    });
  });
}

// ---------- Cached AI summary (rendered once on load if present) ----------
(function renderCachedSummary() {
  const raw = document.getElementById('cachedSummaryData');
  const target = document.getElementById('insightsContent');
  if (!raw || !target) return;
  const cached = JSON.parse(raw.textContent);
  if (cached) target.innerHTML = markdownToHtml(cached);
})();

// ---------- Charts (server-rendered images — no client-side charting library) ----------
// Charts are drawn server-side with matplotlib/seaborn (utils/chart_images.py)
// and embedded directly as base64 <img> tags in the initial HTML. This is
// deliberate: the core EDA experience has zero external script dependency,
// so it can't be broken by a blocked CDN, an ad-blocker, or an offline
// browser. All that's left to wire up client-side is the fullscreen viewer
// and the AI-explain buttons.
document.querySelectorAll('#chartGrid [data-action="fullscreen"]').forEach(btn => {
  btn.addEventListener('click', () => openImageFullscreen(btn.dataset.img, btn.dataset.title));
});

function openImageFullscreen(imgSrc, title) {
  const overlay = document.createElement('div');
  overlay.className = 'chart-fullscreen-overlay';
  overlay.innerHTML = `
    <div class="chart-fullscreen-inner" style="text-align:center;">
      <div style="font-size:13px; font-weight:600; margin-bottom:12px; color:var(--text);">${escapeHtml(title || '')}</div>
      <img src="${imgSrc}" style="max-width:100%; max-height:75vh; border-radius:8px;">
    </div>`;
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
}

async function explainChart(title, targetId, btn) {
  const container = document.getElementById(`explain-${targetId}`);
  btn.disabled = true;
  btn.textContent = 'Thinking...';
  try {
    const res = await fetch(`/api/explain-chart/${DATASET_ID}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chart_title: title }),
    });
    const data = await res.json();
    if (res.ok) {
      container.innerHTML = data.explanation;
      container.classList.add('loaded');
    } else {
      container.innerHTML = `<span style="color:var(--danger)">${data.error}</span>`;
    }
  } catch (e) {
    container.innerHTML = '<span style="color:var(--danger)">Could not reach the AI service.</span>';
  }
}
document.querySelectorAll('#chartGrid [data-chart]').forEach(btn => {
  btn.addEventListener('click', () => explainChart(btn.dataset.chart, btn.dataset.target, btn));
});

// ---------- Insights ----------
const genBtn = document.getElementById('genInsightsBtn');
if (genBtn) {
  genBtn.addEventListener('click', async () => {
    const target = document.getElementById('insightsContent');
    genBtn.disabled = true;
    genBtn.textContent = 'Generating...';
    target.innerHTML = '<p class="empty-note">Analyzing the dataset...</p>';
    try {
      const res = await fetch(`/api/insights/${DATASET_ID}`, { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        target.innerHTML = markdownToHtml(data.summary);
        if (window.showToast) window.showToast('Executive summary generated', 'success', 3000);
      } else {
        target.innerHTML = `<p style="color:var(--danger)">${data.error}</p>`;
        if (window.showToast) window.showToast(data.error, 'error', 5000);
      }
    } catch (e) {
      target.innerHTML = '<p style="color:var(--danger)">Could not reach the AI service.</p>';
      if (window.showToast) window.showToast('Could not reach the AI service.', 'error', 5000);
    }
    genBtn.disabled = false;
    genBtn.textContent = 'Regenerate Summary';
  });
}

// ---------- Chat (persistent sessions) ----------
const chatMessages = document.getElementById('chatMessages');
const chatInput = document.getElementById('chatInput');
const chatSendBtn = document.getElementById('chatSendBtn');
const chatSessionList = document.getElementById('chatSessionList');
const newChatBtn = document.getElementById('newChatBtn');
const chatSessionTitle = document.getElementById('chatSessionTitle');
const followupChips = document.getElementById('followupChips');
let activeChatId = null;
let chatHistory = []; // fallback, used only if session storage is unavailable

function appendMessage(role, text) {
  const div = document.createElement('div');
  div.className = `chat-msg ${role === 'user' ? 'user' : 'ai'}`;
  div.innerHTML = role === 'user' ? escapeHtml(text) : markdownToHtml(text);
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

async function loadChatSessions(selectId) {
  if (!chatSessionList) return;
  try {
    const res = await fetch(`/api/chat/${DATASET_ID}/sessions`);
    const data = await res.json();
    if (!data.chats.length) {
      chatSessionList.innerHTML = '<p class="empty-note" style="padding:8px 0; font-size:12px;">No chats yet.</p>';
      return;
    }
    chatSessionList.innerHTML = data.chats.map(c => `
      <div class="chat-session-item ${c.id === (selectId || activeChatId) ? 'active' : ''}" data-chat-id="${c.id}" title="${escapeHtml(c.title)}">
        ${escapeHtml(c.title)}
      </div>
    `).join('');
    chatSessionList.querySelectorAll('[data-chat-id]').forEach(el => {
      el.addEventListener('click', () => openChatSession(el.dataset.chatId));
    });
  } catch (e) { /* session list is a convenience feature, fail silent */ }
}

async function openChatSession(chatId) {
  activeChatId = chatId;
  chatMessages.innerHTML = '';
  followupChips.innerHTML = '';
  try {
    const res = await fetch(`/api/chat/${DATASET_ID}/sessions/${chatId}`);
    const chat = await res.json();
    if (!res.ok) throw new Error(chat.error);
    chatSessionTitle.textContent = chat.title;
    if (!chat.messages.length) {
      appendMessage('ai', "Ask me anything about this dataset — totals, trends, outliers, or what a specific column means for the business.");
    } else {
      chat.messages.forEach(m => appendMessage(m.role === 'user' ? 'user' : 'ai', m.content));
    }
    loadChatSessions(chatId);
  } catch (e) {
    if (window.showToast) window.showToast('Could not load that chat.', 'error', 4000);
  }
}

async function createNewChat() {
  try {
    const res = await fetch(`/api/chat/${DATASET_ID}/sessions`, { method: 'POST' });
    const chat = await res.json();
    activeChatId = chat.id;
    chatMessages.innerHTML = '';
    followupChips.innerHTML = '';
    chatSessionTitle.textContent = chat.title;
    appendMessage('ai', "Ask me anything about this dataset — totals, trends, outliers, or what a specific column means for the business.");
    loadChatSessions(chat.id);
  } catch (e) {
    if (window.showToast) window.showToast('Could not start a new chat.', 'error', 4000);
  }
}

if (newChatBtn) newChatBtn.addEventListener('click', createNewChat);

async function sendChat(question) {
  if (!question.trim()) return;
  if (!activeChatId) {
    try {
      const res = await fetch(`/api/chat/${DATASET_ID}/sessions`, { method: 'POST' });
      const chat = await res.json();
      activeChatId = chat.id;
    } catch (e) { /* fall back to stateless chat_id=null, still works */ }
  }
  appendMessage('user', question);
  chatHistory.push({ role: 'user', content: question });
  chatInput.value = '';
  followupChips.innerHTML = '';

  const typing = appendMessage('ai', '<span class="typing-dots"><span></span><span></span><span></span></span>');

  try {
    const res = await fetch(`/api/chat/${DATASET_ID}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, history: chatHistory, chat_id: activeChatId }),
    });
    const data = await res.json();
    typing.remove();
    if (res.ok) {
      appendMessage('ai', data.answer);
      chatHistory.push({ role: 'assistant', content: data.answer });
      if (data.followups && data.followups.length) {
        followupChips.innerHTML = data.followups.map(q =>
          `<span class="followup-chip" data-q="${escapeHtml(q)}">${escapeHtml(q)}</span>`
        ).join('');
        followupChips.querySelectorAll('.followup-chip').forEach(chip => {
          chip.addEventListener('click', () => sendChat(chip.dataset.q));
        });
      }
      if (activeChatId) loadChatSessions(activeChatId);
    } else {
      appendMessage('ai', `<span style="color:var(--danger)">${data.error}</span>`);
    }
  } catch (e) {
    typing.remove();
    appendMessage('ai', '<span style="color:var(--danger)">Could not reach the AI service.</span>');
  }
}

if (chatSendBtn) {
  chatSendBtn.addEventListener('click', () => sendChat(chatInput.value));
  chatInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendChat(chatInput.value); });
  document.querySelectorAll('.chat-suggest-btn[data-q]').forEach(btn => {
    btn.addEventListener('click', () => sendChat(btn.dataset.q));
  });
  loadChatSessions();
}

// ---------- SQL Analytics ----------
let schemaLoaded = false;
let lastResult = null;

async function loadSqlSchema() {
  if (schemaLoaded || !SQL_READY) return;
  schemaLoaded = true;
  const container = document.getElementById('sqlSchema');
  if (!container) return;
  try {
    const res = await fetch(`/api/sql/${DATASET_ID}/schema`);
    const data = await res.json();
    if (res.ok) {
      container.innerHTML = data.columns.map(c => `<span class="pill">${c.name} <span style="color:var(--text-faint)">${c.type}</span></span>`).join('');
    }
  } catch (e) { /* silent - schema is a nice-to-have */ }
  loadSavedQueries();
  loadQueryHistory();
}

async function loadSavedQueries() {
  const list = document.getElementById('savedQueriesList');
  if (!list) return;
  try {
    const res = await fetch(`/api/sql/${DATASET_ID}/saved`);
    const data = await res.json();
    if (!data.saved.length) {
      list.innerHTML = '<p class="empty-note" style="padding:8px 0;">No saved queries yet.</p>';
      return;
    }
    list.innerHTML = data.saved.map(q => `
      <div class="query-item" data-sql="${escapeHtml(q.sql)}">
        <div class="query-item-name">${escapeHtml(q.name)}</div>
        <div class="query-item-sql">${escapeHtml(q.sql)}</div>
        <div class="query-item-meta">
          <span></span>
          <span class="query-item-delete" data-delete-id="${q.id}">Delete</span>
        </div>
      </div>
    `).join('');
    list.querySelectorAll('.query-item').forEach(el => {
      el.addEventListener('click', (e) => {
        if (e.target.dataset.deleteId) return;
        sqlEditor.value = el.dataset.sql;
      });
    });
    list.querySelectorAll('[data-delete-id]').forEach(el => {
      el.addEventListener('click', async (e) => {
        e.stopPropagation();
        await fetch(`/api/sql/${DATASET_ID}/saved/${el.dataset.deleteId}`, { method: 'DELETE' });
        loadSavedQueries();
      });
    });
  } catch (e) { /* silent */ }
}

async function loadQueryHistory() {
  const list = document.getElementById('queryHistoryList');
  if (!list) return;
  try {
    const res = await fetch(`/api/sql/${DATASET_ID}/history`);
    const data = await res.json();
    if (!data.history.length) {
      list.innerHTML = '<p class="empty-note" style="padding:8px 0;">No queries run yet.</p>';
      return;
    }
    list.innerHTML = data.history.slice(0, 15).map(h => `
      <div class="query-item" data-sql="${escapeHtml(h.sql)}">
        <div class="query-item-sql">${escapeHtml(h.sql)}</div>
        <div class="query-item-meta">
          <span>${h.row_count} rows &middot; ${h.source}</span>
        </div>
      </div>
    `).join('');
    list.querySelectorAll('.query-item').forEach(el => {
      el.addEventListener('click', () => { sqlEditor.value = el.dataset.sql; });
    });
  } catch (e) { /* silent */ }
}

const clearHistoryBtn = document.getElementById('clearHistoryBtn');
if (clearHistoryBtn) {
  clearHistoryBtn.addEventListener('click', async () => {
    await fetch(`/api/sql/${DATASET_ID}/history`, { method: 'DELETE' });
    loadQueryHistory();
    if (window.showToast) window.showToast('Query history cleared', 'info', 2500);
  });
}

const saveSqlBtn = document.getElementById('saveSqlBtn');
if (saveSqlBtn) {
  saveSqlBtn.addEventListener('click', async () => {
    const sql = sqlEditor.value.trim();
    if (!sql) return;
    const name = window.prompt('Name this query:', 'My query');
    if (!name) return;
    try {
      const res = await fetch(`/api/sql/${DATASET_ID}/saved`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, sql }),
      });
      if (!res.ok) throw new Error((await res.json()).error);
      loadSavedQueries();
      if (window.showToast) window.showToast('Query saved', 'success', 2500);
    } catch (e) {
      if (window.showToast) window.showToast(e.message || 'Could not save query.', 'error', 4000);
    }
  });
}

const optimizeSqlBtn = document.getElementById('optimizeSqlBtn');
if (optimizeSqlBtn) {
  optimizeSqlBtn.addEventListener('click', async () => {
    const sql = sqlEditor.value.trim();
    if (!sql) return;
    const target = document.getElementById('sqlExplain');
    optimizeSqlBtn.disabled = true;
    target.textContent = 'Analyzing for optimizations...';
    try {
      const res = await fetch(`/api/sql/${DATASET_ID}/optimize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql }),
      });
      const data = await res.json();
      if (res.ok) {
        sqlEditor.value = data.optimized_sql;
        target.textContent = 'Optimized (or confirmed already efficient) — see updated query above.';
        target.classList.add('loaded');
      } else {
        target.textContent = data.error;
      }
    } catch (e) {
      target.textContent = 'Could not reach the AI service.';
    }
    optimizeSqlBtn.disabled = false;
  });
}

const sqlEditor = document.getElementById('sqlEditor');
const runSqlBtn = document.getElementById('runSqlBtn');
const sqlErrorEl = document.getElementById('sqlError');
const sqlResultsWrap = document.getElementById('sqlResultsWrap');
const sqlResultsTable = document.getElementById('sqlResultsTable');
const sqlResultMeta = document.getElementById('sqlResultMeta');

async function runSql(sql) {
  sqlErrorEl.style.display = 'none';
  runSqlBtn.disabled = true;
  runSqlBtn.textContent = 'Running...';
  try {
    const res = await fetch(`/api/sql/${DATASET_ID}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Query failed.');
    renderSqlResults(data);
    if (window.showToast) window.showToast(`Query returned ${data.row_count} row(s)`, 'success', 2500);
    loadQueryHistory();
  } catch (e) {
    sqlErrorEl.textContent = e.message;
    sqlErrorEl.style.display = 'block';
    sqlResultsWrap.style.display = 'none';
    if (window.showToast) window.showToast(e.message, 'error', 5000);
  }
  runSqlBtn.disabled = false;
  runSqlBtn.textContent = 'Run Query';
}

function renderSqlResults(data) {
  lastResult = data;
  sqlResultsWrap.style.display = 'block';
  sqlResultMeta.textContent = `${data.row_count} row(s)${data.truncated ? ' (truncated to first 500)' : ''}`;

  const thead = `<thead><tr>${data.columns.map(c => `<th>${c}</th>`).join('')}</tr></thead>`;
  const tbody = `<tbody>${data.rows.map(r => `<tr>${r.map(v => `<td>${v === null ? '' : v}</td>`).join('')}</tr>`).join('')}</tbody>`;
  sqlResultsTable.innerHTML = thead + tbody;
  document.getElementById('sqlChartOutput').innerHTML = '';
}

if (runSqlBtn) {
  runSqlBtn.addEventListener('click', () => runSql(sqlEditor.value));
}

const nlBtn = document.getElementById('nlToSqlBtn');
if (nlBtn) {
  nlBtn.addEventListener('click', async () => {
    const question = document.getElementById('nlQuestion').value.trim();
    if (!question) return;
    nlBtn.disabled = true;
    nlBtn.textContent = 'Thinking...';
    sqlErrorEl.style.display = 'none';
    try {
      const res = await fetch(`/api/sql/${DATASET_ID}/nl2sql`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Could not translate that question to SQL.');
      sqlEditor.value = data.sql;
      renderSqlResults(data);
      loadQueryHistory();
    } catch (e) {
      sqlErrorEl.textContent = e.message;
      sqlErrorEl.style.display = 'block';
    }
    nlBtn.disabled = false;
    nlBtn.textContent = 'Generate SQL';
  });
}

const explainSqlBtn = document.getElementById('explainSqlBtn');
if (explainSqlBtn) {
  explainSqlBtn.addEventListener('click', async () => {
    const sql = sqlEditor.value.trim();
    if (!sql) return;
    const target = document.getElementById('sqlExplain');
    explainSqlBtn.disabled = true;
    target.textContent = 'Explaining...';
    try {
      const res = await fetch(`/api/sql/${DATASET_ID}/explain`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql }),
      });
      const data = await res.json();
      target.textContent = res.ok ? data.explanation : data.error;
      target.classList.toggle('loaded', res.ok);
    } catch (e) {
      target.textContent = 'Could not reach the AI service.';
    }
    explainSqlBtn.disabled = false;
  });
}

const sqlDownloadBtn = document.getElementById('sqlDownloadBtn');
if (sqlDownloadBtn) {
  sqlDownloadBtn.addEventListener('click', () => {
    if (!lastResult) return;
    const csvRows = [lastResult.columns.join(',')].concat(
      lastResult.rows.map(r => r.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(','))
    );
    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'query_results.csv'; a.click();
    URL.revokeObjectURL(url);
  });
}

const sqlChartBtn = document.getElementById('sqlChartBtn');
if (sqlChartBtn) {
  sqlChartBtn.addEventListener('click', async () => {
    if (!lastResult || !lastResult.rows.length) return;
    const container = document.getElementById('sqlChartOutput');
    sqlChartBtn.disabled = true;
    container.innerHTML = '<div class="chart-skeleton skeleton" style="height:220px;"></div>';
    try {
      const res = await fetch(`/api/sql/${DATASET_ID}/chart`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ columns: lastResult.columns, rows: lastResult.rows }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Could not chart these results.');
      container.innerHTML = `<img src="data:image/png;base64,${data.image_base64}" style="max-width:100%; border-radius:8px;">`;
    } catch (e) {
      container.innerHTML = `<div class="empty-note" style="color:var(--danger);">${escapeHtml(e.message)}</div>`;
    }
    sqlChartBtn.disabled = false;
  });
}

// ---------- Data Preview pagination ----------
let currentPage = 1;
const pageSize = 25;
const prevPageBtn = document.getElementById('prevPageBtn');
const nextPageBtn = document.getElementById('nextPageBtn');
const pageIndicator = document.getElementById('pageIndicator');

async function loadDataPage(page) {
  try {
    const res = await fetch(`/api/data/${DATASET_ID}?page=${page}&page_size=${pageSize}`);
    const data = await res.json();
    if (!res.ok) return;
    currentPage = data.page;
    const table = document.getElementById('dataPreviewTable');
    const tbody = table.querySelector('tbody');
    tbody.innerHTML = data.rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>`).join('');
    pageIndicator.textContent = `Page ${data.page} of ${data.total_pages}`;
    prevPageBtn.disabled = data.page <= 1;
    nextPageBtn.disabled = data.page >= data.total_pages;
  } catch (e) { /* keep showing whatever was already rendered */ }
}

if (prevPageBtn && nextPageBtn) {
  prevPageBtn.addEventListener('click', () => loadDataPage(currentPage - 1));
  nextPageBtn.addEventListener('click', () => loadDataPage(currentPage + 1));
}

// ---------- Pin toggle ----------
const pinToggleBtn = document.getElementById('pinToggleBtn');
if (pinToggleBtn) {
  pinToggleBtn.addEventListener('click', async () => {
    try {
      const res = await fetch(`/api/pin/${DATASET_ID}`, { method: 'POST' });
      const data = await res.json();
      pinToggleBtn.classList.toggle('active', data.pinned);
      pinToggleBtn.querySelector('svg').setAttribute('fill', data.pinned ? 'currentColor' : 'none');
      if (window.showToast) window.showToast(data.pinned ? 'Dataset pinned' : 'Dataset unpinned', 'info', 2000);
    } catch (e) { /* non-critical */ }
  });
}

// ---------- Keyboard shortcuts ----------
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault();
    const search = document.getElementById('dashboardSearch');
    if (search) { activateTab('data'); search.focus(); }
  }
  if (e.key === 'Escape') {
    document.querySelectorAll('.chart-fullscreen-overlay').forEach(el => el.remove());
  }
});

// ---------- Helpers ----------
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function markdownToHtml(md) {
  // Minimal, safe markdown renderer: escapes HTML first, then applies a
  // small set of formatting rules. Good enough for AI-generated summaries
  // (headings, bold, bullet lists, paragraphs) without a client-side dependency.
  let text = escapeHtml(md);
  text = text.replace(/^### (.*)$/gm, '<h4>$1</h4>');
  text = text.replace(/^## (.*)$/gm, '<h3>$1</h3>');
  text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/(^|\n)- (.*)/g, '$1<li>$2</li>');
  text = text.replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>');
  text = text.replace(/\n{2,}/g, '</p><p>');
  return `<p>${text}</p>`;
}

// ---------- Initial tab activation (must run after all functions/consts above are declared) ----------
activateTab(document.getElementById(`panel-${initialTab}`) ? initialTab : 'overview');
