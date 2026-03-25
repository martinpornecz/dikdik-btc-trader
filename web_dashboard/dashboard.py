from flask import Flask, jsonify, send_from_directory
import csv
import json
import os

app = Flask(__name__, static_folder="public")

STATE_FILE = "./trading_engine/logs/paper_state.json"
TRADES_FILE = "./trading_engine/logs/paper_trades.csv"


# ─── API: State ─────────────────────────────────
@app.route("/api/state")
def get_state():
    if not os.path.exists(STATE_FILE):
        return jsonify({})
    with open(STATE_FILE) as f:
        return jsonify(json.load(f))


# ─── API: Trades ────────────────────────────────
@app.route("/api/trades")
def get_trades():
    if not os.path.exists(TRADES_FILE):
        return jsonify([])

    trades = []
    with open(TRADES_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(row)

    return jsonify(list(reversed(trades)))

# ─── API: Positionen ────────────────────────────────
@app.route("/api/position")
def get_position():
    if not os.path.exists(STATE_FILE):
        return jsonify(None)

    with open(STATE_FILE) as f:
        data = json.load(f)

    return jsonify(data.get("open_pos"))

# ─── Frontend ───────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("public", "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("public", path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)