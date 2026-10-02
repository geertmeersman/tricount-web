function filterLabel(label) {
  document.querySelectorAll('.tricount-item').forEach(el => {
    el.classList.toggle('hidden', label !== null && el.dataset.label !== label);
  });
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.classList.remove('ring-2');
    btn.style.opacity = '0.5';
  });
  const active = label
    ? document.getElementById('filter-' + label.replace(/ /g, '-'))
    : document.getElementById('filter-all');
  if (active) { active.style.opacity = '1'; active.classList.add('ring-2'); }
}

function updateFilters(labelColors) {
  const labels = [...new Set(
    [...document.querySelectorAll('.tricount-item')].map(el => el.dataset.label).filter(Boolean)
  )];
  const wrap = document.getElementById('filterWrap');
  if (!wrap) return;
  if (labels.length === 0) { wrap.innerHTML = ''; return; }
  wrap.innerHTML = `
    <button data-filter="" id="filter-all" class="filter-btn text-xs px-3 py-1 rounded-full bg-gray-200 text-gray-700 hover:bg-blue-100" style="opacity:1">Alle</button>
    ${labels.map(l => {
      const color = (labelColors && labelColors[l]) || '#3b82f6';
      return `<button data-filter="${l}" id="filter-${l.replace(/ /g, '-')}" class="filter-btn text-xs px-3 py-1 rounded-full font-medium" style="background:${color}22;color:${color};opacity:0.6">${l}</button>`;
    }).join('')}
  `;
  wrap.addEventListener('click', (e) => {
    const btn = e.target.closest('.filter-btn');
    if (btn) filterLabel(btn.dataset.filter || null);
  });
  // activeer 'Alle' standaard
  document.getElementById('filter-all').style.opacity = '1';
  document.getElementById('filter-all').classList.add('ring-2', 'ring-gray-400');
}

function renderTricount(item, labelColors) {
  const color = (labelColors && item.label && labelColors[item.label]) || '#3b82f6';
  const labelBadge = item.label
    ? `<span class="ml-1 text-xs font-medium px-2 py-0.5 rounded-full" style="background:${color}22;color:${color}">${item.label}</span>`
    : '';
  const archived = item.archived ? `<span class="ml-1 text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">${_i18n.archived}</span>` : '';
  const div = document.createElement('div');
  div.id = `tc-${item.token}`;
  div.className = 'bg-white rounded-xl shadow px-4 py-3 tricount-item';
  div.dataset.label = item.label || '';
  div.innerHTML = `
    <a href="/tricount/${item.token}" class="flex-1 min-w-0 block">
      <div class="font-medium truncate">${item.emoji} ${item.title} ${labelBadge} ${archived}</div>
      <div class="text-xs text-gray-400 mt-0.5">${item.currency} · ${item.members} ${_i18n.members}</div>
    </a>`;
  return div;
}

function loadTricounts(tokens, labelColors, force = false) {
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
      items.forEach(item => list.appendChild(renderTricount(item, labelColors)));
      if (items.length === 0) emptyMsg.classList.remove('hidden');

      let filterWrap = document.getElementById('filterWrap');
      if (!filterWrap) {
        filterWrap = document.createElement('div');
        filterWrap.id = 'filterWrap';
        filterWrap.className = 'flex flex-wrap gap-2 mb-4';
        list.parentNode.insertBefore(filterWrap, list);
      }
      updateFilters(labelColors);
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
