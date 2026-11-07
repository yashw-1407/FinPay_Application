# FinPay — Campus Digital Wallet & Cashback Application

An end-to-end implementation of **FinPay**, designed and structured in strict compliance with the **FinPay Scenario Specification** and the **Laboratory 4 AI-Assisted Detailed Design Record (DDR)**.

---

## 🏛 System Architecture & 4-Layer Design

FinPay follows the standard enterprise layered architecture with separation of concerns:

```
┌────────────────────────────────────────────────────────┐
│ 1. ROUTER LAYER (Flask REST API Endpoints)            │
│    - Verifies TalentHub JWT signature, expiry & roles  │
│    - Rejects invalid tokens with 401 Unauthorized      │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ 2. SERVICE LAYER (Business Logic & Constraints)        │
│    - process_payment() coordinates transactions        │
│    - calculate_cashback() algorithm (Pure, no DB)      │
│    - Ownership Check: wallet.student_id == token.sub   │
│    - Enforces monthly category cashback limits (caps)  │
│    - reconciliation_service for Finance/Admin auditing │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ 3. REPOSITORY LAYER (Parameterized SQL & Indices)      │
│    - Parameterized queries to prevent SQL injection    │
│    - PRAGMA foreign_keys = ON; (ON DELETE RESTRICT)   │
│    - Index on (wallet_id, created_at) for fast SUM     │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ 4. MODEL & DATABASE LAYER (SQLite: finpay.db)          │
│    - Option A: Single relational store (Source of truth)│
│    - Normalized up to 3NF and BCNF                     │
│    - Strict integer paise (no floating-point decimals) │
└────────────────────────────────────────────────────────┘
```

---

## 🗄 Relational Database Schema (3NF & BCNF)

All monetary amounts are stored as **integer paise** (₹1 = 100 paise) and all rates in **basis points** (1% = 100 bps) to prevent decimal rounding errors:

1. **`WALLET_TIER`** (Lookup table):
   - `tier` (TEXT, PK): `'BASIC'`, `'PRIME'`, `'PREMIUM'`
   - `rate_mult_x10` (INTEGER): `10`, `15`, `20` (representing 1.0×, 1.5×, 2.0×)
   - `cap_mult_x10` (INTEGER): `10`, `15`, `20` (representing 1.0×, 1.5×, 2.0×)

2. **`CASHBACK_RULE`** (Lookup table):
   - `category_code` (TEXT, PK): `'CANTEEN'`, `'STATIONERY'`, `'TRANSPORT'`, `'HOSTEL'`, `'ONLINE'`, `'TOPUP'`
   - `rate_bps` (INTEGER): Canteen=200 (2.0%), Stationery=100 (1.0%), Transport=300 (3.0%), Hostel=50 (0.5%), Online=100 (1.0%), Topup=0 (0%)
   - `basic_monthly_cap_paise` (INTEGER): Canteen=5,000 (₹50), Stationery=2,000 (₹20), Transport=10,000 (₹100), Hostel=20,000 (₹200), Online=3,000 (₹30), Topup=0

3. **`WALLET`** (Student Wallet entity):
   - `wallet_id` (INTEGER, PK AUTOINCREMENT)
   - `student_id` (TEXT, UNIQUE): Foreign identifier corresponding to TalentHub student
   - `tier` (TEXT, FK -> WALLET_TIER.tier ON DELETE RESTRICT)
   - `balance_paise` (INTEGER, CHECK >= 0)
   - */monthly_cashback is derived on-the-fly from TRANSACTION to eliminate stale-data anomalies.*

4. **`MERCHANT`** (Merchant entity):
   - `merchant_id` (INTEGER, PK AUTOINCREMENT)
   - `merchant_name` (TEXT)
   - `category_code` (TEXT, FK -> CASHBACK_RULE.category_code ON DELETE RESTRICT)

5. **`TRANSACTION`** (Transactional ledger):
   - `transaction_id` (INTEGER, PK AUTOINCREMENT)
   - `wallet_id` (INTEGER, FK -> WALLET.wallet_id ON DELETE RESTRICT)
   - `merchant_id` (INTEGER, FK -> MERCHANT.merchant_id ON DELETE RESTRICT)
   - `idempotency_key` (TEXT NOT NULL)
   - `amount_paise` (INTEGER, CHECK > 0)
   - `cashback_paise` (INTEGER, CHECK >= 0)
   - `created_at` (TEXT NOT NULL, ISO-8601)
   - **`UNIQUE(wallet_id, idempotency_key)`**: Database-level guarantee against duplicate debits.
   - **`INDEX idx_trans_wallet_created ON TRANSACTION(wallet_id, created_at)`**: Optimizes monthly limit SUM queries.

---

## 🧮 Critical Algorithm: `calculate_cashback()`

From Lab 4 Part B:
```python
def calculate_cashback(amount_paise: int, rate_bps: int, tier_mult_x10: int) -> int:
    if amount_paise <= 0 or rate_bps < 0 or tier_mult_x10 <= 0:
        raise InvalidInput("Violated constraints: amount_paise > 0, rate_bps >= 0, tier_mult_x10 > 0.")
    if rate_bps == 0:
        return 0
    # 64-bit integer numerator; cut off once (floor DIV 100,000)
    numerator = amount_paise * rate_bps * tier_mult_x10
    return numerator // 100000
```

### Monthly Limit Application in `process_payment()`:
```python
monthly_cap = (rule.basic_monthly_cap_paise * tier.cap_mult_x10) // 10
already_earned = SUM(cashback_paise) for (wallet_id, category_code, current_month)
remaining_cap = max(monthly_cap - already_earned, 0)
awarded_cashback = min(raw_cashback, remaining_cap)
```

---

## 🛡 Security Controls Approved in DDR (Part C)

1. **TalentHub JWT Authentication & Service Ownership Check**:
   - Reuses TalentHub's JWT infrastructure.
   - The router validates JWT token signature and expiry (401).
   - The service layer performs an ownership check: `wallet.student_id == token.subject`. If a student attempts to pay with another student's wallet, the service refuses with `403 Forbidden`.
2. **Role-Based Field Filtering**:
   - Students only see their own wallet and transaction history.
   - Reconciliation summaries are restricted to users with `role: "finance"` or `role: "admin"`.
3. **Database-Level Idempotency Protection**:
   - `UNIQUE(wallet_id, idempotency_key)` stops double payments.
   - If an idempotency key is re-submitted, the system returns the original transaction record without a second debit or second cashback grant.

---

## 🧪 Laboratory 4 Boundary & Edge-Case Verification

All 10 test cases from Table 3 in the Lab 4 manual are verified:

| # | Scenario / Input | Expected Result | Verified Check |
|---|---|---|---|
| **1** | 10,000 paise (₹100), CANTEEN, BASIC | 200 paise (₹2.00) | Rahul's example from scenario |
| **2** | 1,234 paise, CANTEEN, PRIME | 37 paise | 37.02 -> 37 (Alternative A: one-step floor) |
| **3** | 50 paise, CANTEEN, BASIC | 1 paise | Smallest amount that earns 1 paise |
| **4** | 49 paise, CANTEEN, BASIC | 0 paise | 0.98 -> 0 (Floor cut-off, no rounding up) |
| **5** | 333 paise, STATIONERY, BASIC | 3 paise | 3.33 -> 3 paise |
| **6** | 100,000 paise (₹1,000), HOSTEL, PREMIUM | 1,000 paise (₹10.00) | Effective rate 1.0% |
| **7** | 50,000 paise, TOPUP, any tier | 0 paise | rate_bps = 0, no cashback |
| **8** | Amount 0 or negative | InvalidInput Exception | Refusal on non-positive input |
| **9** | process_payment: raw 200, cap 5000, earned 4900 | 100 paise | Partial cap reduction |
| **10** | process_payment: raw 200, cap 5000, earned 5000 | 0 paise | Cap exhausted |

---

## 🚀 Running the Application

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Automated Test Suite
```bash
python -m unittest backend/tests/test_lab4_cases.py
```
*(All 13 unit tests pass in ~0.14s)*

### 3. Start Application
```bash
python run.py
```
Open **`http://127.0.0.1:5000`** in your browser.

---

## 💻 Frontend UI Features

- **TalentHub User Switcher**: Switch between **Rahul Verma** (BASIC), **Priya Sharma** (PRIME), **Amit Patel** (PREMIUM), and **Prof. Sen** (Finance Officer) to test multi-tenancy and role checks.
- **Digital Wallet Card**: Live balance in ₹ and paise, active tier, and instant tier upgrade selector.
- **Interactive Payment Module**:
  - Select merchant with category badges.
  - Enter amount in Rupees (auto-converts to integer paise).
  - Auto-generated or custom Idempotency Key with a **"Re-send Duplicate"** button to simulate and verify idempotency live in the browser.
- **Live Reactive Cashback Preview**:
  - Dynamically calculates raw cashback, category cap remaining, and final awarded cashback before confirming.
- **Monthly Category Limits Visualizer**:
  - Animated progress bars for Canteen, Stationery, Transport, Hostel, Online, and Top-up.
- **Lab 4 Test Suite Tab**:
  - 1-click execution of all 10 boundary cases directly in the browser with pass/fail badges.
- **Finance Monthly Reconciliation Tab**:
  - Financial KPI metrics, volume summaries, category settlements, and complete audit ledger.

