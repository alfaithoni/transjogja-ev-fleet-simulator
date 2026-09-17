# -*- coding: utf-8 -*-
"""
dashboard/app.py
-----------------
Flask entry point untuk dashboard TransJogja EV Sim.
Jalankan: python dashboard/app.py
Buka: http://localhost:5000
"""

from flask import Flask, render_template
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))

app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates",
)

from api.routes_api import api_bp
app.register_blueprint(api_bp, url_prefix="/api")


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    print("=" * 55)
    print("  TransJogja EV Sim — Dashboard")
    print("  Buka: http://localhost:5000")
    print("=" * 55)
    app.run(debug=True, port=5000, use_reloader=False)
