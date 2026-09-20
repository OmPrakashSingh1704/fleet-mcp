from __future__ import annotations

from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/")
def index():
    return jsonify({"service": "fixture-hello-mcp"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
