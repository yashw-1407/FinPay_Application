"""
FinPay Application Main Entrypoint.
Initializes the SQLite database (finpay.db) and launches the backend server.
"""

import os
import sys

# Ensure backend package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.database import init_db
from backend.app import app

if __name__ == "__main__":
    print("=" * 65)
    print("  FINPAY — Campus Digital Wallet & Cashback System")
    print("  Based on FinPay Scenario & Lab 4 Detailed Design (DDR)")
    print("=" * 65)
    
    # Ensure database tables and reference data exist
    init_db(force=False)
    print("✔ SQLite Database initialized (backend/finpay.db)")
    print("✔ TalentHub JWT Authentication ready")
    print("✔ Ready to serve frontend and backend APIs")
    print("\n👉 Open your browser at: http://127.0.0.1:5000\n")
    print("=" * 65)

    app.run(host="127.0.0.1", port=5000, debug=True)

