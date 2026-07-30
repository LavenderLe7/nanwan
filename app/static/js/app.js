// 轻量交互：匹配工作台加载、匹配状态标记、看板/列表辅助。零外部依赖。
async function postJSON(url, data) {
  const body = new URLSearchParams(data || {});
  const r = await fetch(url, { method: 'POST', body,
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' } });
  return r.json().catch(() => ({}));
}

// ---- 匹配工作台 ----
function matchLoad(mode, id, el) {
  document.querySelectorAll('.pick-list a').forEach(a => a.classList.remove('cur'));
  if (el) el.classList.add('cur');
  const box = document.getElementById('match-results');
  box.innerHTML = '<p class="muted">计算结果加载中…</p>';
  fetch(`/gov/api/match/${mode}/${id}`).then(r => r.text()).then(h => { box.innerHTML = h; });
}
function matchFilter(input, listId) {
  const kw = input.value.trim();
  document.querySelectorAll(`#${listId} a`).forEach(a => {
    a.style.display = a.textContent.includes(kw) ? '' : 'none';
  });
}
async function matchStatus(mid, status, btn) {
  await postJSON(`/gov/api/match/${mid}/status`, { status });
  const row = btn.closest('tr');
  const cell = row.querySelector('.mstatus');
  if (cell) cell.textContent = status;
  if (status === '已排除') row.style.opacity = 0.35; else row.style.opacity = 1;
}
async function matchToProject(mid, btn) {
  const r = await postJSON(`/gov/api/match/${mid}/to_project`);
  if (r.ok) { btn.textContent = '已转项目'; btn.disabled = true; matchStatus(mid, '已对接', btn); }
}

// ---- 通用 ----
function confirmDel(msg) { return confirm(msg || '确认删除？该操作不可恢复。'); }
function recompute(btn) {
  btn.disabled = true; btn.textContent = '重算中，请稍候…';
  fetch('/gov/match/recompute', { method: 'POST' }).then(r => r.text()).then(h => {
    document.getElementById('recompute-box').innerHTML = h;
    btn.disabled = false; btn.textContent = '重新计算全部匹配';
  });
}
