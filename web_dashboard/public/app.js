let chart;
let lastTradeId = null;

// ─── STATE ─────────────────────────────
async function loadState() {
  const res = await fetch("/api/state");
  const data = await res.json();

  if (data.balance === undefined) return;

  document.getElementById("balance").textContent =
    "$" + Number(data.balance).toFixed(2);

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

function createRow(t) {
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

  return tr;
}


// ─── TRADES + CHART ────────────────────
async function loadTrades() {
  const res = await fetch("/api/trades");
  const trades = await res.json();

  const tbody = document.getElementById("trades");

  // ─── EQUITY berechnen ─────────────────
  let equity = 100;
  const equityData = [equity];

  trades.slice().reverse().forEach(t => {
    const pnl = parseFloat(t.pnl);
    equity += pnl;
    equityData.push(equity);
  });

  drawChart(equityData);

  if (!trades.length) return;

  // ─── ERSTER LOAD → alles rendern ──────
  if (lastTradeId === null) {
    trades.slice(0, 50).forEach(t => {
      const tr = createRow(t);
      tbody.appendChild(tr);
    });

    lastTradeId = trades[0].id;
    return;
  }

  // ─── NUR NEUE TRADES ─────────────────
  let newTrades = [];

  for (let t of trades) {
    if (t.id == lastTradeId) break;
    newTrades.push(t);
  }

  if (newTrades.length === 0) return;

  // neue oben einfügen
  newTrades.reverse().forEach(t => {
    const tr = createRow(t);
    tbody.insertBefore(tr, tbody.firstChild);
  });

  lastTradeId = trades[0].id;

  // max 50 behalten
  while (tbody.children.length > 50) {
    tbody.removeChild(tbody.lastChild);
  }
}


// ─── POSITION ──────────────────────────
async function loadPosition() {
  const res = await fetch("/api/position");
  const pos = await res.json();

  const el = document.getElementById("position");

  if (!pos) {
    el.innerHTML = "Keine offene Position";
    return;
  }

  el.innerHTML = `
    <b>Side:</b> ${pos.side} <br>
    <b>Entry:</b> ${pos.entry_price} <br>
    <b>Shares:</b> ${pos.shares} <br>
    <b>Zeit:</b> ${pos.time_left} min
  `;
}


// ─── CHART ─────────────────────────────
function drawChart(data) {
  const ctx = document.getElementById("equityChart");

  // 🟢 Chart nur einmal erstellen
  if (!chart) {
    chart = new Chart(ctx, {
      type: "line",
      data: {
        labels: data.map((_, i) => i),
        datasets: [{
          label: "Equity",
          data: data,
          borderWidth: 2,
          tension: 0.2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false, // wichtig!
        animation: false, // verhindert Jump
        plugins: {
          legend: { display: false }
        }
      }
    });
  } else {
    // 🔵 Nur Daten updaten (KEIN destroy!)
    chart.data.labels = data.map((_, i) => i);
    chart.data.datasets[0].data = data;
    chart.update("none"); // kein Animation-Jump
  }
}

// 🔁 REFRESH LOOP
async function refresh() {
  await loadState();
  await loadTrades();
  await loadPosition();
}

setInterval(refresh, 2000);
refresh();