function h(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function showPayModal(dname, cname, pay, currency, payerUuid, receiverUuid, token) {
  const existing = document.getElementById('payModal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'payModal';
  modal.className = 'fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4';
  modal.innerHTML = `
    <div class="bg-white rounded-xl shadow-xl w-full max-w-sm p-6" onclick="event.stopPropagation()">
      <h3 class="font-semibold text-lg mb-1">${h(_t.confirmPayment)}</h3>
      <p class="text-sm text-gray-500 mb-4">
        <span class="font-medium text-red-500">${h(dname)}</span>
        ${h(_t.pays)}
        <span class="font-medium text-green-600">${h(cname)}</span>
      </p>
      <div class="text-3xl font-bold text-center mb-6">${pay} ${h(currency)}</div>
      <div class="flex gap-3">
        <button onclick="document.getElementById('payModal').remove()"
          class="flex-1 border border-gray-300 text-gray-600 hover:bg-gray-50 py-2 rounded-lg text-sm">${h(_t.cancel)}</button>
        <form method="POST" action="/tricount/${h(token)}/reimburse" class="flex-1">
          <input type="hidden" name="payer_uuid" value="${h(payerUuid)}">
          <input type="hidden" name="receiver_uuid" value="${h(receiverUuid)}">
          <input type="hidden" name="amount" value="${pay}">
          <button class="w-full bg-green-600 hover:bg-green-700 text-white py-2 rounded-lg text-sm font-medium">${h(_t.confirm)}</button>
        </form>
      </div>
    </div>`;
  modal.addEventListener('click', () => modal.remove());
  document.body.appendChild(modal);
}

function renderTricount(data, token) {
  document.getElementById('pageTitle').textContent = (data.emoji ? data.emoji + ' ' : '') + data.title;

  // Leden
  document.getElementById('membersList').innerHTML =
    data.members.map(m => {
      const isMe = m.uuid === data.linked_uuid;
      return `<span class="text-xs px-2 py-1 rounded-full ${isMe ? 'bg-blue-600 text-white font-medium' : 'bg-gray-200 text-gray-700'}">${h(m.name)}${isMe ? ` <span class="opacity-75">(${h(_t.you)})</span>` : ''}</span>`;
    }).join('');

  // Saldi
  const debtors = Object.entries(data.balances).filter(([, b]) => b < -0.01).map(([n, b]) => [n, Math.abs(b)]);
  const creditors = Object.entries(data.balances).filter(([, b]) => b > 0.01);

  let debtsHtml = '';
  if (debtors.length === 0) {
    debtsHtml = `<p class="text-sm text-green-600 mb-2">${h(_t.everyoneSettled)}</p>`;
  } else {
    debtors.forEach(([dname, damt]) => {
      creditors.forEach(([cname, camt]) => {
        const pay = Math.min(damt, camt).toFixed(2);
        const debtor = data.members.find(m => m.name === dname);
        const creditor = data.members.find(m => m.name === cname);
        debtsHtml += `
          <div class="flex items-center justify-between gap-2">
            <span class="text-sm">
              <span class="font-medium text-red-500">${h(dname)}</span> ${h(_t.mustPay)}
              <span class="font-medium text-green-600">${h(cname)}</span>
              <span class="font-semibold"> ${pay} ${h(data.currency)}</span>
            </span>
            ${!data.archived && debtor && creditor ? `
            <button onclick="showPayModal('${h(dname)}','${h(cname)}','${pay}','${h(data.currency)}','${h(debtor.uuid)}','${h(creditor.uuid)}','${h(token)}')"
              class="text-xs bg-green-600 hover:bg-green-700 text-white px-3 py-1 rounded-lg shrink-0">${h(_t.paid)}</button>` : ''}
          </div>`;
      });
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
    <a href="/tricount/${h(token)}/add" class="flex-1 text-center bg-green-600 hover:bg-green-700 text-white py-2 rounded-lg text-sm font-medium">${h(_t.addTransaction)}</a>
    <a href="/tricount/${h(token)}/recurring" class="flex-1 text-center bg-purple-600 hover:bg-purple-700 text-white py-2 rounded-lg text-sm font-medium">${h(_t.recurring)}</a>`;

  // Transacties
  let txHtml = '';
  let modalsHtml = '';
  if (data.transactions.length === 0) {
    txHtml = `<p class="px-4 py-3 text-sm text-gray-400">${h(_t.noTransactions)}</p>`;
  } else {
    data.transactions.forEach(tx => {
      txHtml += `
        <div class="px-4 py-3 flex justify-between items-start cursor-pointer hover:bg-gray-50"
             onclick="document.getElementById('modal-${tx.id}').classList.remove('hidden')">
          <div class="min-w-0">
            <div class="text-sm font-medium truncate">${h(tx.description)}</div>
            <div class="text-xs text-gray-400">${h(tx.payer)}${tx.payer_is_me ? ` <span class="text-blue-500">(${h(_t.you)})</span>` : ''} · ${h(tx.date)}</div>
          </div>
          <div class="text-sm font-semibold ml-4 shrink-0">${tx.amount.toFixed(2)} ${h(tx.currency)}</div>
        </div>`;

      modalsHtml += `
        <div id="modal-${tx.id}" class="hidden fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4"
             onclick="this.classList.add('hidden')">
          <div class="bg-white rounded-xl shadow-xl w-full max-w-sm p-5" onclick="event.stopPropagation()">
            <div class="flex justify-between items-start mb-3">
              <div>
                <div class="font-semibold">${h(tx.description)}</div>
                <div class="text-xs text-gray-400">${h(tx.date)} · ${h(_t.paidBy)} ${h(tx.payer)}</div>
              </div>
              <button onclick="document.getElementById('modal-${tx.id}').classList.add('hidden')"
                class="text-gray-400 hover:text-gray-600 text-xl leading-none ml-3">✕</button>
            </div>
            <div class="text-lg font-bold mb-3">${tx.amount.toFixed(2)} ${h(tx.currency)}</div>
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
    });
  }
  document.getElementById('transactions').innerHTML = txHtml;
  document.getElementById('modals').innerHTML = modalsHtml;
  document.getElementById('content').classList.remove('hidden');
}

function loadTricountDetail(token) {
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
        renderTricount(data, token);
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
