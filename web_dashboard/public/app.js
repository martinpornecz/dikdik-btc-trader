async function loadState() {
  const res = await fetch("/api/state");
  const data = await res.json();

  if (!data.balance) return;

  document.getElementById("balance").textContent =
    "$" + data.balance.toFixed(2);

  const pnl = data.balance - (data.start_balance || 100);
  const pnlEl = document.getElementById("pnl");

  pnlEl.textContent = "$" + pnl.toFixed(2);
  pnlEl.className = pnl >= 0 ? "green" : "red";

  const trades = data.trades || [];
  const wins = trades.filter(t => t.pnl > 0).length;
  const wr = trades.length ? (wins / trades.length) * 100 : 0;

  document.getElementById("wr").textContent =
    wr.toFixed(1) + "%";
}


async function loadTrades() {
  const res = await fetch("/api/trades");
  const trades = await res.json();

  const tbody = document.getElementById("trades");
  tbody.innerHTML = "";

  trades.slice(0, 50).forEach(t => {
    const tr = document.createElement("tr");

    const pnl = parseFloat(t.pnl);
    const cls = pnl >= 0 ? "green" : "red";

    tr.innerHTML = `
      <td>${t.id}</td>
      <td>${t.side}</td>
      <td class="${cls}">${pnl.toFixed(2)}</td>
      <td>${t.entry_price}</td>
      <td>${t.exit_price}</td>
      <td>${t.reason}</td>
    `;

    tbody.appendChild(tr);
  });
}


// 🔁 Auto-Refresh
async function refresh() {
  await loadState();
  await loadTrades();
}

setInterval(refresh, 2000);
refresh();