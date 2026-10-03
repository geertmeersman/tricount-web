function renderTricount(item, labelColors) {
  const archived = item.archived ? `<span class="ml-1 text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">${_i18n.archived}</span>` : '';
  const div = document.createElement('div');
  div.id = `tc-${item.token}`;
  div.className = 'bg-white dark:bg-gray-800 rounded-xl shadow px-4 py-3 tricount-item';
  div.dataset.label = item.label || '';
  div.innerHTML = `
    <a href="/tricount/${item.token}" class="flex-1 min-w-0 block">
      <div class="font-medium truncate dark:text-gray-100">${item.emoji} ${item.title} ${archived}</div>
      <div class="text-xs text-gray-400 dark:text-gray-500 mt-0.5">${item.currency} · ${item.members} ${_i18n.members}</div>
    </a>`;
  return div;
}

function renderGrouped(items, labelColors) {
  const list = document.getElementById('tricountList');
  list.innerHTML = '';

  // Groepeer per label, ongelabelde tricounts apart
  const groups = {};
  const unlabeled = [];
  items.forEach(item => {
    if (item.label) {
      if (!groups[item.label]) groups[item.label] = [];
      groups[item.label].push(item);
    } else {
      unlabeled.push(item);
    }
  });

  // Sorteer labels alfabetisch
  const sortedLabels = Object.keys(groups).sort((a, b) => a.localeCompare(b));

  function appendGroup(label, groupItems, color) {
    if (label) {
      const header = document.createElement('div');
      header.className = 'flex items-center gap-2 mt-6 mb-2 px-1';
      header.innerHTML = `
        <span class="w-2.5 h-2.5 rounded-full shrink-0" style="background:${color}"></span>
        <span class="text-xs font-semibold uppercase tracking-wide" style="color:${color}">${label}</span>
        <span class="text-xs text-gray-400">(${groupItems.length})</span>`;
      list.appendChild(header);
    }
    const wrap = document.createElement('div');
    wrap.className = 'space-y-2';
    groupItems.sort((a, b) => a.title.localeCompare(b.title));
    groupItems.forEach(item => wrap.appendChild(renderTricount(item, labelColors)));
    list.appendChild(wrap);
  }

  sortedLabels.forEach(label => {
    const color = (labelColors && labelColors[label]) || '#3b82f6';
    appendGroup(label, groups[label], color);
  });

  if (unlabeled.length > 0) {
    if (sortedLabels.length > 0) {
      const header = document.createElement('div');
      header.className = 'flex items-center gap-2 mt-6 mb-2 px-1';
      header.innerHTML = `<span class="text-xs font-semibold uppercase tracking-wide text-gray-400">${_i18n.noLabel}</span>`;
      list.appendChild(header);
    }
    const wrap = document.createElement('div');
    wrap.className = 'space-y-2';
    unlabeled.sort((a, b) => a.title.localeCompare(b.title));
    unlabeled.forEach(item => wrap.appendChild(renderTricount(item, labelColors)));
    list.appendChild(wrap);
  }
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

  if (force) fetch('/refresh');

  progressWrap.classList.remove('hidden');
  progressBar.style.width = '0%';

  const items = [];
  const es = new EventSource('/api/tricounts');

  es.onmessage = (e) => {
    const data = JSON.parse(e.data);

    if (data.type === 'done') {
      es.close();
      progressWrap.classList.add('hidden');
      if (items.length === 0) { emptyMsg.classList.remove('hidden'); return; }
      renderGrouped(items, labelColors);
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
