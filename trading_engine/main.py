"""
╔══════════════════════════════════════════════════════════════════════════╗
║      Polymarket BTC 15m — Paper Trading Bot (Python)                    ║
║      Liest ./logs/signals.csv und simuliert Trades.                     ║
║      🟡  NUR SIMULATION — kein echtes Geld!                              ║
╚══════════════════════════════════════════════════════════════════════════╝

Wie es funktioniert:
  1. Starte zuerst den Node.js-Assistant:   npm start
     → Dieser schreibt laufend Zeilen in  ./logs/signals.csv
  2. Starte dann dieses Script (in einem zweiten Terminal):
     python paper_trader.py
  3. Der Paper-Trader liest die CSV, erkennt neue Signale und simuliert
     automatisch Käufe/Verkäufe — ohne echtes Geld.

CSV-Format von signals.csv (wird vom Assistant erzeugt):
  timestamp, entry_minute, time_left_min, regime,
  signal, model_up, model_down, mkt_up, mkt_down,
  edge_up, edge_down, recommendation

Voraussetzungen:
  - Python 3.8+
  - Keine zusätzlichen Pakete nötig (nur stdlib)

Konfiguration: siehe SETTINGS unten
"""

import csv
import os
import sys
import time
import json
from datetime import datetime, timezone
from pathlib import Path

# ═══════════════════════════ SETTINGS ════════════════════════════════════
# Pfad zum PolymarketBTC15mAssistant-Verzeichnis (wo npm start läuft)
ASSISTANT_DIR   = "../"

# Startkapital und Einsatz
START_BALANCE   = 100.0   # USD (virtuell)
ORDER_SIZE_USD  = 5.0     # Einsatz pro Trade in USD

# Entry-Filter: Nur handeln wenn diese Bedingungen erfüllt sind
ALLOWED_STRENGTHS  = {"STRONG", "GOOD"}   # aus recommendation-Feld
ALLOWED_PHASES     = {"EARLY", "MID"}     # LATE wird übersprungen
MIN_MODEL_PROB     = 0.57                 # model_up oder model_down muss >= dieser Wert sein

# Exit-Logik
PRE_SETTLE_MIN     = 2.0   # Unter X Minuten -> Pre-Settlement Exit
PRE_SETTLE_FACTOR  = 0.97  # Abschlag auf Marktpreis beim Pre-Settlement Exit

# Poll-Intervall: wie oft die CSV neu gelesen wird (Sekunden)
POLL_INTERVAL      = 2.0

# Ausgabe-Dateien (im selben Verzeichnis wie dieses Script)
TRADE_LOG_FILE  = "paper_trades.csv"
STATE_FILE      = "paper_state.json"   # Persistiert den Portfolio-Stand

VERBOSE = True
# ═════════════════════════════════════════════════════════════════════════


# Pfad zur signals.csv
SIGNALS_CSV = os.path.join(ASSISTANT_DIR, "logs", "signals.csv")


# ─── Farben ───────────────────────────────────────────────────────────────
class C:
    RESET = ""; BOLD = ""; GREEN = ""
    RED = "";  YELLOW = ""; CYAN = ""
    GRAY = ""; BLUE = "";  MAGENTA = ""

if not sys.stdout.isatty():
    for a in list(vars(C).keys()):
        if not a.startswith("_"):
            setattr(C, a, "")


# ─── CSV-Parsing ──────────────────────────────────────────────────────────
# Spaltenindizes laut appendCsvRow in utils.js:
# timestamp(0), entry_minute(1), time_left_min(2), regime(3),
# signal(4), model_up(5), model_down(6), mkt_up(7), mkt_down(8),
# edge_up(9), edge_down(10), recommendation(11)
COL = {
    "timestamp":      0,
    "entry_minute":   1,
    "time_left_min":  2,
    "regime":         3,
    "signal":         4,
    "model_up":       5,
    "model_down":     6,
    "mkt_up":         7,
    "mkt_down":       8,
    "edge_up":        9,
    "edge_down":      10,
    "recommendation": 11,
}

def _f(row, key):
    """Gibt Wert aus Zeile als float, None bei Fehler."""
    try:
        v = row[COL[key]]
        return float(v) if v not in ("", "-", "null", "None") else None
    except (IndexError, ValueError):
        return None

def _s(row, key):
    """Gibt Wert aus Zeile als String."""
    try:
        return str(row[COL[key]]).strip()
    except IndexError:
        return ""

def parse_recommendation(rec_str):
    """
    Parst z.B. "UP:EARLY:STRONG" oder "NO_TRADE"
    -> dict mit action, side, phase, strength
    """
    rec_str = rec_str.strip()
    if rec_str == "NO_TRADE" or not rec_str:
        return {"action": "NO_TRADE", "side": None, "phase": None, "strength": None}
    parts = rec_str.split(":")
    if len(parts) >= 3:
        return {
            "action":   "ENTER",
            "side":     parts[0],
            "phase":    parts[1],
            "strength": parts[2],
        }
    return {"action": "NO_TRADE", "side": None, "phase": None, "strength": None}

def read_last_n_rows(filepath, n=5):
    """Liest die letzten n Zeilen der CSV (ohne Header)."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if len(rows) <= 1:
            return []
        return rows[1:][-n:]   # ohne Header, letzte n
    except (FileNotFoundError, PermissionError):
        return []


# ─── Portfolio ────────────────────────────────────────────────────────────
class PaperPortfolio:
    def __init__(self):
        self.balance       = START_BALANCE
        self.start_balance = START_BALANCE
        self.open_pos      = None
        self.trades        = []
        self.trade_count   = 0

    def load(self):
        """Lädt gespeicherten Zustand (falls vorhanden)."""
        if not Path(STATE_FILE).exists():
            return
        try:
            with open(STATE_FILE, "r") as f:
                s = json.load(f)
            self.balance     = s.get("balance", START_BALANCE)
            self.open_pos    = s.get("open_pos", None)
            self.trades      = s.get("trades", [])
            self.trade_count = s.get("trade_count", 0)
            print(f"{C.CYAN}[STATE] Zustand geladen: "
                  f"Balance=${self.balance:.2f}, "
                  f"Trades={len(self.trades)}{C.RESET}")
        except Exception as e:
            print(f"{C.YELLOW}[WARN] State-Datei konnte nicht geladen werden: {e}{C.RESET}")

    def save(self):
        """Speichert aktuellen Zustand."""
        try:
            with open(STATE_FILE, "w") as f:
                json.dump({
                    "balance":     self.balance,
                    "open_pos":    self.open_pos,
                    "trades":      self.trades,
                    "trade_count": self.trade_count,
                }, f, indent=2)
        except Exception as e:
            print(f"{C.YELLOW}[WARN] State konnte nicht gespeichert werden: {e}{C.RESET}")

    @property
    def pnl(self):
        return self.balance - self.start_balance

    @property
    def pnl_pct(self):
        return (self.pnl / self.start_balance) * 100 if self.start_balance else 0

    @property
    def win_rate(self):
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t["pnl"] > 0)
        return (wins / len(self.trades)) * 100

    def open_trade(self, side, price, mkt_up, mkt_down,
                   model_up, model_down, time_left, timestamp):
        if self.open_pos:
            return False
        if ORDER_SIZE_USD > self.balance:
            return False
        shares = ORDER_SIZE_USD / price
        self.balance -= ORDER_SIZE_USD
        self.trade_count += 1
        self.open_pos = {
            "id":          self.trade_count,
            "side":        side,
            "entry_price": price,
            "shares":      shares,
            "cost":        ORDER_SIZE_USD,
            "mkt_up":      mkt_up,
            "mkt_down":    mkt_down,
            "model_up":    model_up,
            "model_down":  model_down,
            "time_left":   time_left,
            "opened_at":   timestamp,
        }
        self.save()
        return True

    def close_trade(self, exit_price, reason, timestamp):
        if not self.open_pos:
            return None
        pos = self.open_pos
        proceeds = pos["shares"] * exit_price
        pnl = proceeds - pos["cost"]
        self.balance += proceeds
        trade = {
            **pos,
            "exit_price": exit_price,
            "proceeds":   proceeds,
            "pnl":        pnl,
            "pnl_pct":    (pnl / pos["cost"]) * 100,
            "closed_at":  timestamp,
            "reason":     reason,
            "result":     "WIN" if pnl > 0 else "LOSS",
        }
        self.trades.append(trade)
        self.open_pos = None
        self.save()
        return trade


# ─── Trade-Log (CSV) ──────────────────────────────────────────────────────
TRADE_FIELDS = [
    "id", "opened_at", "closed_at", "side",
    "entry_price", "exit_price", "shares", "cost", "proceeds", "pnl", "pnl_pct",
    "model_up", "model_down", "mkt_up", "mkt_down",
    "time_left", "reason", "result"
]

def log_trade(trade):
    exists = Path(TRADE_LOG_FILE).exists()
    with open(TRADE_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerow(trade)


# ─── Entry / Exit Logik ───────────────────────────────────────────────────
def should_enter(row, port):
    """Gibt (enter: bool, side: str, price: float) zurueck."""
    if port.open_pos:
        return False, "", 0.0

    rec = parse_recommendation(_s(row, "recommendation"))

    if rec["action"] != "ENTER":
        return False, "", 0.0

    if rec["strength"] not in ALLOWED_STRENGTHS:
        return False, "", 0.0

    if rec["phase"] not in ALLOWED_PHASES:
        return False, "", 0.0

    side = rec["side"]
    if side == "UP":
        model_prob = _f(row, "model_up") or 0
        price      = _f(row, "mkt_up")
    elif side == "DOWN":
        model_prob = _f(row, "model_down") or 0
        price      = _f(row, "mkt_down")
    else:
        return False, "", 0.0

    if model_prob < MIN_MODEL_PROB:
        return False, "", 0.0

    if not price or price <= 0 or price >= 1:
        return False, "", 0.0

    return True, side, price


def should_exit(row, port):
    """Gibt (exit: bool, price: float, reason: str) zurueck."""
    pos = port.open_pos
    if not pos:
        return False, 0.0, ""

    time_left  = _f(row, "time_left_min") or 99
    side       = pos["side"]
    rec        = parse_recommendation(_s(row, "recommendation"))

    # Settlement: weniger als 0.5 Minuten
    if time_left <= 0.5:
        model_prob = _f(row, "model_up" if side == "UP" else "model_down") or 0.5
        # Paper-Simulation: >60% Modell = angenommener Win (1.0), sonst Loss (0.0)
        if model_prob > 0.60:
            return True, 1.0, f"Settlement-WIN (model={model_prob:.1%})"
        else:
            return True, 0.0, f"Settlement-LOSS (model={model_prob:.1%})"

    # Pre-Settlement Exit (unter PRE_SETTLE_MIN Minuten)
    if time_left < PRE_SETTLE_MIN:
        mkt_price = _f(row, "mkt_up" if side == "UP" else "mkt_down") or pos["entry_price"]
        exit_p = max(0.01, min(0.99, mkt_price * PRE_SETTLE_FACTOR))
        return True, exit_p, f"Pre-Settlement Exit (<{PRE_SETTLE_MIN:.0f}m)"

    # Gegenseitiges Signal
    if rec["action"] == "ENTER" and rec["side"] and rec["side"] != side:
        mkt_price = _f(row, "mkt_up" if side == "UP" else "mkt_down") or pos["entry_price"]
        exit_p = max(0.01, min(0.99, mkt_price))
        return True, exit_p, f"Gegensignal ({rec['side']})"

    return False, 0.0, ""


# ─── Display ──────────────────────────────────────────────────────────────
def banner():
    strengths_str = ', '.join(sorted(ALLOWED_STRENGTHS))
    print(f"""
{C.CYAN}{C.BOLD}+===========================================================+
|    Polymarket BTC 15m -- Paper Trader                     |
|    NUR SIMULATION -- kein echtes Geld!                    |
+===========================================================+{C.RESET}
Startkapital  : {C.BOLD}${START_BALANCE:.2f}{C.RESET}
Einsatz/Trade : {C.BOLD}${ORDER_SIZE_USD:.2f}{C.RESET}
Min. Model    : {C.BOLD}{MIN_MODEL_PROB:.0%}{C.RESET}   Staerken: {C.BOLD}{strengths_str}{C.RESET}
CSV-Quelle    : {C.BOLD}{SIGNALS_CSV}{C.RESET}
Trade-Log     : {C.BOLD}{TRADE_LOG_FILE}{C.RESET}

{C.CYAN}Warte auf Signale... (Strg+C zum Beenden){C.RESET}
{C.GRAY}Starte den Assistant zuerst:  npm start{C.RESET}
""")

def fmt_row(row):
    ts    = _s(row, "timestamp")[-8:] or "?"
    tl    = _f(row, "time_left_min") or 0
    mu    = _f(row, "model_up") or 0
    md    = _f(row, "model_down") or 0
    rec   = _s(row, "recommendation")
    eu    = _f(row, "edge_up") or 0
    ed    = _f(row, "edge_down") or 0
    return (f"{C.GRAY}[{ts}]{C.RESET} "
            f"T-{tl:.1f}m  "
            f"ModelUP={C.GREEN}{mu:.1%}{C.RESET} "
            f"ModelDN={C.RED}{md:.1%}{C.RESET}  "
            f"Edge U={eu:+.3f} D={ed:+.3f}  "
            f"-> {C.BOLD}{rec}{C.RESET}")

def print_trade_opened(pos):
    sc = C.GREEN if pos["side"] == "UP" else C.RED
    print(f"\n  {C.BOLD}> TRADE EROEFFNET{C.RESET}  "
          f"#{pos['id']}  Side: {sc}{pos['side']}{C.RESET}  "
          f"Entry: {pos['entry_price']:.4f}  "
          f"Shares: {pos['shares']:.2f}  Cost: ${pos['cost']:.2f}\n")

def print_trade_closed(trade):
    col = C.GREEN if trade["pnl"] > 0 else C.RED
    sym = "WIN" if trade["pnl"] > 0 else "LOSS"
    print(f"\n  {C.BOLD}< TRADE GESCHLOSSEN{C.RESET}  "
          f"#{trade['id']}  {col}{sym}{C.RESET}  "
          f"PnL: {col}{trade['pnl']:+.2f}$ ({trade['pnl_pct']:+.1f}%){C.RESET}  "
          f"-> {trade['reason']}\n")

def print_status(port):
    pc = C.GREEN if port.pnl >= 0 else C.RED
    pos_str = (f"OPEN #{port.open_pos['id']} {port.open_pos['side']}"
               if port.open_pos else "--")
    print(f"  {C.CYAN}Portfolio{C.RESET}: "
          f"${port.balance:.2f}  "
          f"PnL={pc}{port.pnl:+.2f}$ ({port.pnl_pct:+.1f}%){C.RESET}  "
          f"Trades={len(port.trades)}  WR={port.win_rate:.0f}%  "
          f"Pos: {C.YELLOW}{pos_str}{C.RESET}")

def print_summary(port):
    pc = C.GREEN if port.pnl >= 0 else C.RED
    print(f"\n{C.CYAN}{C.BOLD}======= ZUSAMMENFASSUNG ======={C.RESET}")
    print(f"  Startkapital : ${port.start_balance:.2f}")
    print(f"  Endkapital   : ${port.balance:.2f}")
    print(f"  Gesamt PnL   : {pc}{port.pnl:+.2f}$ ({port.pnl_pct:+.1f}%){C.RESET}")
    print(f"  Trades       : {len(port.trades)}")
    print(f"  Win-Rate     : {port.win_rate:.1f}%")
    if port.trades:
        best  = max(port.trades, key=lambda t: t["pnl"])
        worst = min(port.trades, key=lambda t: t["pnl"])
        print(f"  Bester Trade : +${best['pnl']:.2f} (#{best['id']} {best['side']})")
        print(f"  Schlechtester: ${worst['pnl']:+.2f}$ (#{worst['id']} {worst['side']})")
    if port.open_pos:
        print(f"  Offene Pos.  : #{port.open_pos['id']} {port.open_pos['side']} "
              f"(Entry {port.open_pos['entry_price']:.4f}) -- kein Exit-Preis verfuegbar")
    print(f"\n  Trade-Log    : {C.BOLD}{TRADE_LOG_FILE}{C.RESET}")
    print(f"  State-Datei  : {C.BOLD}{STATE_FILE}{C.RESET}\n")


# ─── Hauptschleife ────────────────────────────────────────────────────────
def main():
    banner()

    port = PaperPortfolio()
    port.load()  # Vorherigen Zustand laden (falls vorhanden)

    last_processed_ts = None
    csv_missing_warned = False

    try:
        while True:
            time.sleep(POLL_INTERVAL)

            # CSV existiert noch nicht (Assistant noch nicht gestartet)
            if not Path(SIGNALS_CSV).exists():
                if not csv_missing_warned:
                    print(f"{C.YELLOW}[WARTE] {SIGNALS_CSV} nicht gefunden. "
                          f"Bitte 'npm start' im Assistant-Verzeichnis starten.{C.RESET}")
                    csv_missing_warned = True
                continue
            csv_missing_warned = False

            # Letzte Zeilen lesen
            rows = read_last_n_rows(SIGNALS_CSV, n=3)
            if not rows:
                continue

            latest_row = rows[-1]
            current_ts = _s(latest_row, "timestamp")

            # Nur verarbeiten wenn neue Zeile
            if current_ts == last_processed_ts:
                continue
            last_processed_ts = current_ts

            if VERBOSE:
                print(fmt_row(latest_row))

            # Exit pruefen
            if port.open_pos:
                do_exit, exit_price, reason = should_exit(latest_row, port)
                if do_exit:
                    trade = port.close_trade(exit_price, reason, current_ts)
                    if trade:
                        print_trade_closed(trade)
                        log_trade(trade)

            # Entry pruefen
            do_enter, side, price = should_enter(latest_row, port)
            if do_enter:
                mu   = _f(latest_row, "model_up")
                md   = _f(latest_row, "model_down")
                mu_v = _f(latest_row, "mkt_up")
                md_v = _f(latest_row, "mkt_down")
                tl   = _f(latest_row, "time_left_min")

                success = port.open_trade(
                    side=side, price=price,
                    mkt_up=mu_v, mkt_down=md_v,
                    model_up=mu, model_down=md,
                    time_left=tl, timestamp=current_ts
                )
                if success:
                    print_trade_opened(port.open_pos)
                else:
                    skip_reason = ("Pos. bereits offen" if port.open_pos
                                   else f"Kapital < ${ORDER_SIZE_USD}")
                    print(f"  {C.YELLOW}[SKIP] Entry nicht moeglich: {skip_reason}{C.RESET}")

            if VERBOSE:
                print_status(port)

    except KeyboardInterrupt:
        print(f"\n\n{C.YELLOW}Gestoppt.{C.RESET}")
    finally:
        print_summary(port)


if __name__ == "__main__":
    main()