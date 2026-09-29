function filterLabel(label) {
  document.querySelectorAll('.tricount-item').forEach(el => {
    el.classList.toggle('hidden', label !== null && el.dataset.label !== label);
  });
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.classList.remove('bg-blue-600', 'text-white');
    btn.classList.add('bg-gray-200', 'text-gray-700');
  });
  const active = label
    ? document.getElementById('filter-' + label.replace(/ /g, '-'))
    : document.getElementById('filter-all');
  if (active) {
    active.classList.add('bg-blue-600', 'text-white');
    active.classList.remove('bg-gray-200', 'text-gray-700');
  }
}

function updateFilters() {
  const labels = [...new Set(
    [...document.querySelectorAll('.tricount-item')].map(el => el.dataset.label).filter(Boolean)
  )];
  const wrap = document.getElementById('filterWrap');
  if (!wrap) return;
  if (labels.length === 0) { wrap.innerHTML = ''; return; }
  wrap.innerHTML = `
    <button onclick="filterLabel(null)" id="filter-all" class="filter-btn text-xs px-3 py-1 rounded-full bg-blue-600 text-white">Alle</button>
    ${labels.map(l => `<button onclick="filterLabel('${l}')" id="filter-${l.replace(/ /g, '-')}" class="filter-btn text-xs px-3 py-1 rounded-full bg-gray-200 text-gray-700 hover:bg-blue-100">${l}</button>`).join('')}
  `;
}

function renderTricount(item) {
  const label = item.label ? `<span class="ml-1 text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">${item.label}</span>` : '';
  const archived = item.archived ? `<span class="ml-1 text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">${_i18n.archived}</span>` : '';
  const div = document.createElement('div');
  div.id = `tc-${item.token}`;
  div.className = 'bg-white rounded-xl shadow px-4 py-3 tricount-item';
  div.dataset.label = item.label || '';
  div.innerHTML = `
    <a href="/tricount/${item.token}" class="flex-1 min-w-0 block">
      <div class="font-medium truncate">${item.emoji} ${item.title} ${label} ${archived}</div>
      <div class="text-xs text-gray-400 mt-0.5">${item.currency} · ${item.members} ${_i18n.members}</div>
    </a>`;
  return div;
}

function loadTricounts(tokens, force = false) {
  const list = document.getElementById('tricountList');
  const progressWrap = document.getElementById('progressWrap');
  const progressBar = document.getElementById('progressBar');
  const progressLabel = document.getElementById('progressLabel');
  const progressCount = document.getElementById('progressCount');
  const emptyMsg = document.getElementById('emptyMsg');

  list.innerHTML = '';
  emptyMsg.classList.add('hidden');

  if (tokens.length === 0) {
    emptyMsg.classList.remove('hidden');
    return;
  }

  if (force) {
    fetch('/refresh');
  }

  progressWrap.classList.remove('hidden');
  progressBar.style.width = '0%';

  const items = [];
  const es = new EventSource('/api/tricounts');

  es.onmessage = (e) => {
    const data = JSON.parse(e.data);

    if (data.type === 'done') {
      es.close();
      progressWrap.classList.add('hidden');
      items.sort((a, b) => (a.label || a.title).localeCompare(b.label || b.title));
      list.innerHTML = '';
      items.forEach(item => list.appendChild(renderTricount(item)));
      if (items.length === 0) emptyMsg.classList.remove('hidden');

      let filterWrap = document.getElementById('filterWrap');
      if (!filterWrap) {
        filterWrap = document.createElement('div');
        filterWrap.id = 'filterWrap';
        filterWrap.className = 'flex flex-wrap gap-2 mb-4';
        list.parentNode.insertBefore(filterWrap, list);
      }
      updateFilters();
      return;
    }

    const pct = Math.round((data.done / data.total) * 100);
    progressBar.style.width = pct + '%';
    progressCount.textContent = `${data.done}/${data.total}`;

    if (data.type === 'error') {
      progressLabel.textContent = `${_i18n.error}: ${data.label || data.token}`;
    } else {
      progressLabel.textContent = `${data.emoji} ${data.title} — ${_i18n.loaded}`;
      items.push(data);
    }
  };

  es.onerror = () => { es.close(); progressWrap.classList.add('hidden'); progressLabel.textContent = '❌ ' + _i18n.error; };
}
