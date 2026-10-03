function h(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

let _allTransactions = [];
let _tricountData = null;
let _token = null;
let _bulkMode = false;

function renderTxRow(tx) {
  return `
    <div class="tx-row px-4 py-3 flex items-start gap-3 hover:bg-gray-50 dark:hover:bg-gray-700/50"
         data-id="${tx.id}" data-desc="${h(tx.description.toLowerCase())}" data-payer="${h(tx.payer.toLowerCase())}" data-amount="${tx.amount}">
      <label class="bulk-check flex items-center shrink-0 hidden mt-0.5 cursor-pointer">
        <input type="checkbox" class="tx-checkbox w-4 h-4 accent-blue-600" data-id="${tx.id}">
      </label>
      <div class="tx-row-inner flex flex-1 justify-between items-start cursor-pointer min-w-0">
        <div class="min-w-0">
          <div class="text-sm font-medium truncate dark:text-gray-100">${h(tx.description)}</div>
          <div class="text-xs text-gray-400 dark:text-gray-500">${h(tx.payer)}${tx.payer_is_me ? ` <span class="text-blue-500">(${h(_t.you)})</span>` : ''} · ${h(tx.date)}</div>
        </div>
        <div class="text-sm font-semibold ml-4 shrink-0 dark:text-gray-100">${tx.amount.toFixed(2)} ${h(tx.currency)}</div>
      </div>
    </div>`;
}

function renderTxModal(tx, token, data) {
  return `
    <div id="modal-${tx.id}" class="tx-modal hidden fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4" data-modal-id="${tx.id}">
      <div class="tx-modal-inner bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-sm p-5">
        <div class="flex justify-between items-start mb-3">
          <div>
            <div class="font-semibold dark:text-gray-100">${h(tx.description)}</div>
            <div class="text-xs text-gray-400 dark:text-gray-500">${h(tx.date)} · ${h(_t.paidBy)} ${h(tx.payer)}</div>
          </div>
          <button class="tx-modal-close text-gray-400 hover:text-gray-600 text-xl leading-none ml-3" data-modal-id="${tx.id}">✕</button>
        </div>
        <div class="text-lg font-bold mb-3 dark:text-gray-100">${tx.amount.toFixed(2)} ${h(tx.currency)}</div>
        <div class="space-y-1">
          ${tx.allocations.map(a => `
            <div class="flex justify-between text-sm">
              <span>${h(a.name)}</span>
              <span class="font-medium">${a.amount.toFixed(2)} ${h(tx.currency)}</span>
            </div>`).join('')}
        </div>
        ${!data.archived ? `
        <a href="/tricount/${h(token)}/edit/${tx.id}"
          class="mt-4 block text-center bg-blue-600 hover:bg-blue-700 text-white py-2 rounded-lg text-sm font-medium">${h(_t.editTransaction)}</a>` : ''}
      </div>
    </div>`;
}

function updateBulkBar() {
  const checked = document.querySelectorAll('.tx-checkbox:checked');
  const bar = document.getElementById('bulkBar');
  const countEl = document.getElementById('bulkCount');
  if (countEl) countEl.textContent = checked.length;
  if (bar) bar.classList.toggle('hidden', checked.length === 0);
  const selectAll = document.getElementById('selectAllCheckbox');
  if (selectAll) {
    const visible = document.querySelectorAll('.tx-row:not(.hidden) .tx-checkbox');
    selectAll.indeterminate = checked.length > 0 && checked.length < visible.length;
    selectAll.checked = visible.length > 0 && checked.length === visible.length;
  }
}

function toggleBulkMode() {
  _bulkMode = !_bulkMode;
  document.querySelectorAll('.bulk-check').forEach(el => el.classList.toggle('hidden', !_bulkMode));
  document.getElementById('bulkModeBtn').classList.toggle('text-blue-600', _bulkMode);
  document.getElementById('bulkModeBtn').classList.toggle('bg-blue-50', _bulkMode);
  document.getElementById('txSelectAllRow').classList.toggle('hidden', !_bulkMode);
  if (!_bulkMode) {
    document.querySelectorAll('.tx-checkbox').forEach(cb => cb.checked = false);
    updateBulkBar();
  }
}

function filterTransactions(query) {
  const q = query.toLowerCase().trim();
  const rows = document.querySelectorAll('.tx-row');
  let visible = 0;
  let total = 0;
  rows.forEach(row => {
    const match = !q || row.dataset.desc.includes(q) || row.dataset.payer.includes(q);
    row.classList.toggle('hidden', !match);
    if (match) { visible++; total += parseFloat(row.dataset.amount); }
  });
  const noResults = document.getElementById('txNoResults');
  if (noResults) noResults.classList.toggle('hidden', visible > 0 || rows.length === 0);
  const totalEl = document.getElementById('txTotal');
  if (totalEl) totalEl.textContent = total.toFixed(2);
  updateBulkBar();
}

function showPayModal(dname, cname, pay, currency, payerUuid, receiverUuid, token) {
  const existing = document.getElementById('payModal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'payModal';
  modal.className = 'fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4';

  const inner = document.createElement('div');
  inner.className = 'bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-sm p-6';
  inner.innerHTML = `
    <h3 class="font-semibold text-lg mb-1 dark:text-gray-100">${h(_t.confirmPayment)}</h3>
    <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
      <span class="font-medium text-red-500">${h(dname)}</span>
      ${h(_t.pays)}
      <span class="font-medium text-green-600">${h(cname)}</span>
    </p>
    <div class="text-3xl font-bold text-center mb-6 dark:text-gray-100">${pay} ${h(currency)}</div>
    <div class="flex gap-3">
      <button id="payModalCancel" class="flex-1 border border-gray-300 text-gray-600 hover:bg-gray-50 py-2 rounded-lg text-sm">${h(_t.cancel)}</button>
      <form method="POST" action="/tricount/${h(token)}/reimburse" class="flex-1">
        <input type="hidden" name="payer_uuid" value="${h(payerUuid)}">
        <input type="hidden" name="receiver_uuid" value="${h(receiverUuid)}">
        <input type="hidden" name="amount" value="${pay}">
        <button type="submit" class="w-full bg-green-600 hover:bg-green-700 text-white py-2 rounded-lg text-sm font-medium">${h(_t.confirm)}</button>
      </form>
    </div>`;

  modal.appendChild(inner);
  modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
  inner.querySelector('#payModalCancel').addEventListener('click', () => modal.remove());
  document.body.appendChild(modal);
}

function confirmBulkDelete(token) {
  const checked = document.querySelectorAll('.tx-checkbox:checked');
  if (!checked.length) return;

  const existing = document.getElementById('bulkConfirmModal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'bulkConfirmModal';
  modal.className = 'fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4';

  const inner = document.createElement('div');
  inner.className = 'bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4';
  inner.innerHTML = `
    <h3 class="font-semibold text-lg text-red-600 flex items-center gap-2"><svg xmlns='http://www.w3.org/2000/svg' class='w-5 h-5' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='3 6 5 6 21 6'/><path d='M19 6l-1 14H6L5 6'/><path d='M10 11v6'/><path d='M14 11v6'/><path d='M9 6V4h6v2'/></svg> ${h(_t.deleteSelected)}</h3>
    <p class="text-sm text-gray-600 dark:text-gray-300">${_t.confirmDelete.replace('{n}', checked.length)}</p>
    <div class="flex gap-3 pt-2">
      <button id="bulkConfirmCancel" class="flex-1 border border-gray-300 text-gray-600 hover:bg-gray-50 py-2 rounded-lg text-sm">${h(_t.cancel)}</button>
      <button id="bulkConfirmOk" class="flex-1 bg-red-600 hover:bg-red-700 text-white py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-1.5"><svg xmlns='http://www.w3.org/2000/svg' class='w-4 h-4' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='3 6 5 6 21 6'/><path d='M19 6l-1 14H6L5 6'/><path d='M10 11v6'/><path d='M14 11v6'/><path d='M9 6V4h6v2'/></svg> ${h(_t.deleteSelected)}</button>
    </div>`;

  modal.appendChild(inner);
  modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
  inner.querySelector('#bulkConfirmCancel').addEventListener('click', () => modal.remove());
  inner.querySelector('#bulkConfirmOk').addEventListener('click', () => {
    const container = document.getElementById('bulkHiddenInputs');
    container.innerHTML = '';
    document.querySelectorAll('.tx-checkbox:checked').forEach(cb => {
      const inp = document.createElement('input');
      inp.type = 'hidden'; inp.name = 'tx_ids'; inp.value = cb.dataset.id;
      container.appendChild(inp);
    });
    document.getElementById('bulkDeleteForm').submit();
  });
  document.body.appendChild(modal);
}

function shareTricount() {
  const url = document.getElementById('shareBtn').dataset.shareUrl;
  if (url) copyToClipboard(url);
}

document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
    const search = document.getElementById('txSearch');
    if (search) { e.preventDefault(); search.focus(); search.select(); }
  }
});

// Event delegation for tx rows, modals, pay buttons and checkboxes
document.addEventListener('click', (e) => {
  // tx row inner click → open modal or toggle checkbox
  const rowInner = e.target.closest('.tx-row-inner');
  if (rowInner) {
    const row = rowInner.closest('.tx-row');
    if (_bulkMode) {
      const cb = row.querySelector('.tx-checkbox');
      cb.checked = !cb.checked;
      updateBulkBar();
    } else {
      const id = row.dataset.id;
      document.getElementById('modal-' + id)?.classList.remove('hidden');
    }
    return;
  }

  // tx-checkbox change via click
  if (e.target.classList.contains('tx-checkbox')) {
    updateBulkBar();
    return;
  }

  // close modal via backdrop
  if (e.target.classList.contains('tx-modal')) {
    e.target.classList.add('hidden');
    return;
  }

  // close modal via ✕ button
  const closeBtn = e.target.closest('.tx-modal-close');
  if (closeBtn) {
    document.getElementById('modal-' + closeBtn.dataset.modalId)?.classList.add('hidden');
    return;
  }

  // pay button (data-pay-* attributes set during render)
  const payBtn = e.target.closest('.pay-btn');
  if (payBtn) {
    const d = payBtn.dataset;
    showPayModal(d.dname, d.cname, d.pay, d.currency, d.payerUuid, d.receiverUuid, d.token);
    return;
  }
});

function renderTricount(data, token, label, labelColors) {
  _token = token;
  _tricountData = data;
  const displayTitle = (data.emoji ? data.emoji + ' ' : '') + data.title;
  document.getElementById('pageTitle').textContent = displayTitle;
  const labelEl = document.getElementById('pageTitleLabel');
  if (labelEl) {
    if (label) {
      labelEl.textContent = label;
      const color = (labelColors && labelColors[label]) || '#3b82f6';
      labelEl.style.backgroundColor = color + '22';
      labelEl.style.color = color;
      labelEl.classList.remove('hidden');
    } else {
      labelEl.classList.add('hidden');
    }
  }

  // Leden
  document.getElementById('membersList').innerHTML =
    data.members.map(m => {
      const isMe = m.uuid === data.linked_uuid;
      return `<span class="text-xs px-2 py-1 rounded-full ${isMe ? 'bg-blue-600 text-white font-medium' : 'bg-gray-200 text-gray-700'}">${h(m.name)}${isMe ? ` <span class="opacity-75">(${h(_t.you)})</span>` : ''}</span>`;
    }).join('');

  // Bereken settlements
  const debtors = Object.entries(data.balances).filter(([, b]) => b < -0.01).map(([n, b]) => [n, Math.abs(b)]).sort((a, b) => b[1] - a[1]);
  const creditors = Object.entries(data.balances).filter(([, b]) => b > 0.01).map(([n, b]) => [n, b]).sort((a, b) => b[1] - a[1]);
  const settlements = [];
  {
    const d = debtors.map(([n, b]) => [n, b]);
    const c = creditors.map(([n, b]) => [n, b]);
    let i = 0, j = 0;
    while (i < d.length && j < c.length) {
      const pay = Math.min(d[i][1], c[j][1]);
      if (pay > 0.01) settlements.push([d[i][0], c[j][0], pay]);
      d[i][1] -= pay; c[j][1] -= pay;
      if (d[i][1] < 0.01) i++;
      if (c[j][1] < 0.01) j++;
    }
  }

  function payBtnHtml(dname, cname, pay, debtor, creditor) {
    if (!debtor || !creditor) return '';
    return `<button class="pay-btn text-xs bg-green-600 hover:bg-green-700 text-white px-3 py-1 rounded-lg shrink-0"
      data-dname="${h(dname)}" data-cname="${h(cname)}" data-pay="${pay.toFixed(2)}"
      data-currency="${h(data.currency)}" data-payer-uuid="${h(debtor.uuid)}"
      data-receiver-uuid="${h(creditor.uuid)}" data-token="${h(token)}">${h(_t.paid)}</button>`;
  }

  // Persoonlijke samenvatting
  const myName = data.linked_uuid ? (data.members.find(m => m.uuid === data.linked_uuid) || {}).name : null;
  let myHtml = '';
  if (myName) {
    const myBal = data.balances[myName] || 0;
    if (Math.abs(myBal) < 0.01) {
      myHtml = `<div class="bg-green-50 border border-green-200 rounded-xl p-3 text-sm text-green-700 font-medium">${h(_t.everyoneSettled)}</div>`;
    } else {
      myHtml = settlements
        .filter(([dname, cname]) => dname === myName || cname === myName)
        .map(([dname, cname, pay]) => {
          const iDebtor = dname === myName;
          const other = iDebtor ? cname : dname;
          const debtor = data.members.find(m => m.name === dname);
          const creditor = data.members.find(m => m.name === cname);
          return `<div class="${iDebtor ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'} border rounded-xl p-3 flex items-center justify-between gap-2">
            <span class="text-sm font-medium ${iDebtor ? 'text-red-700' : 'text-green-700'}">
              ${iDebtor ? _t.youOwe : _t.youAreOwed} <span class="font-bold">${h(other)}</span>: ${pay.toFixed(2)} ${h(data.currency)}
            </span>
            ${!data.archived && iDebtor ? payBtnHtml(dname, cname, pay, debtor, creditor) : ''}
          </div>`;
        }).join('');
    }
  }
  document.getElementById('mySummary').innerHTML = myHtml;

  // Saldi
  let debtsHtml = '';
  if (debtors.length === 0) {
    debtsHtml = `<p class="text-sm text-green-600 mb-2">${h(_t.everyoneSettled)}</p>`;
  } else {
    settlements.forEach(([dname, cname, pay]) => {
      const debtor = data.members.find(m => m.name === dname);
      const creditor = data.members.find(m => m.name === cname);
      debtsHtml += `
        <div class="flex items-center justify-between gap-2">
          <span class="text-sm">
            <span class="font-medium text-red-500">${h(dname)}</span> ${h(_t.mustPay)}
            <span class="font-medium text-green-600">${h(cname)}</span>
            <span class="font-semibold"> ${pay.toFixed(2)} ${h(data.currency)}</span>
          </span>
          ${!data.archived ? payBtnHtml(dname, cname, pay, debtor, creditor) : ''}
        </div>`;
    });
  }
  document.getElementById('debts').innerHTML = debtsHtml;

  document.getElementById('balances').innerHTML = Object.entries(data.balances).map(([name, bal]) => `
    <div class="flex justify-between text-xs text-gray-400">
      <span>${h(name)}</span>
      <span class="${bal > 0 ? 'text-green-600' : bal < 0 ? 'text-red-500' : ''}">${bal > 0 ? '+' : ''}${bal.toFixed(2)} ${h(data.currency)}</span>
    </div>`).join('');

  // Acties
  document.getElementById('actions').innerHTML = data.archived ? '' : `
    <a href="/tricount/${h(token)}/add" class="flex-1 text-center bg-green-600 hover:bg-green-700 text-white py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-1.5"><svg xmlns='http://www.w3.org/2000/svg' class='w-4 h-4' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><line x1='12' y1='5' x2='12' y2='19'/><line x1='5' y1='12' x2='19' y2='12'/></svg>${h(_t.addTransaction)}</a>
    <a href="/tricount/${h(token)}/recurring" class="flex-1 text-center bg-purple-600 hover:bg-purple-700 text-white py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-1.5"><svg xmlns='http://www.w3.org/2000/svg' class='w-4 h-4' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='17 1 21 5 17 9'/><path d='M3 11V9a4 4 0 0 1 4-4h14'/><polyline points='7 23 3 19 7 15'/><path d='M21 13v2a4 4 0 0 1-4 4H3'/></svg>${h(_t.recurring)}</a>`;

  // Transacties
  let txHtml = '';
  let modalsHtml = '';
  if (data.transactions.length === 0) {
    txHtml = `<p class="px-4 py-3 text-sm text-gray-400">${h(_t.noTransactions)}</p>`;
  } else {
    data.transactions.forEach(tx => {
      txHtml += renderTxRow(tx);
      modalsHtml += renderTxModal(tx, token, data);
    });
  }
  document.getElementById('transactions').innerHTML = txHtml +
    `<p id="txNoResults" class="hidden px-4 py-3 text-sm text-gray-400">${h(_t.noResults)}</p>`;
  document.getElementById('modals').innerHTML = modalsHtml;

  const total = data.transactions.reduce((sum, tx) => sum + tx.amount, 0);
  document.getElementById('txTotal').textContent = total.toFixed(2);
  document.getElementById('txCurrency').textContent = data.currency;
  document.getElementById('txTotalAll').textContent = `${total.toFixed(2)} ${data.currency}`;
  if (data.public_token) {
    document.getElementById('shareBtn').dataset.shareUrl = `https://tricount.com/${data.public_token}`;
  } else {
    document.getElementById('shareBtn').classList.add('hidden');
  }
  document.getElementById('content').classList.remove('hidden');
}

function loadTricountDetail(token, label, labelColors) {
  const es = new EventSource(`/api/tricount/${token}`);
  es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.type === 'status') {
      document.getElementById('progressLabel').textContent = data.message;
      document.getElementById('progressBar').style.width = '50%';
    } else if (data.type === 'data') {
      document.getElementById('progressBar').style.width = '100%';
      document.getElementById('progressLabel').textContent = _t.ready;
      setTimeout(() => {
        document.getElementById('progressWrap').classList.add('hidden');
        renderTricount(data, token, label, labelColors);
      }, 300);
      es.close();
    } else if (data.type === 'error') {
      document.getElementById('progressLabel').textContent = '❌ ' + data.message;
      es.close();
    } else if (data.type === 'done') {
      es.close();
    }
  };
  es.onerror = () => {
    document.getElementById('progressLabel').textContent = '❌ ' + _t.connError;
    es.close();
  };
}
