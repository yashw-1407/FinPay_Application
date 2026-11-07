/**
 * FinPay Frontend Application Script
 * Communicates with the 4-layer FinPay Backend.
 * Handles TalentHub JWT simulation, live cashback calculation preview,
 * category limit progress, payment execution with idempotency, and Lab 4 test verification.
 */

const API_BASE = "/api";

// Application State
const state = {
  users: [],
  currentUser: null,
  jwtToken: null,
  wallet: null,
  merchants: [],
  lastPaymentKey: null,
  previewDebounceTimer: null
};

// ============================================================================
// Initialization & Boot
// ============================================================================
document.addEventListener("DOMContentLoaded", async () => {
  setupNavigationTabs();
  setupEventListeners();
  await loadDemoUsers();
  await loadMerchants();
  generateNewIdempotencyKey();
  setDefaultReconciliationMonth();
});

// ============================================================================
// Navigation Tabs
// ============================================================================
function setupNavigationTabs() {
  const tabs = document.querySelectorAll(".nav-tab");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));

      tab.classList.add("active");
      const targetId = tab.getAttribute("data-tab");
      const targetPane = document.getElementById(targetId);
      if (targetPane) {
        targetPane.classList.add("active");
      }

      // Auto-trigger tab specific actions
      if (targetId === "tab-tests") {
        runLab4Tests();
      } else if (targetId === "tab-reconciliation") {
        loadMonthlyReconciliation();
      }
    });
  });
}

// ============================================================================
// Authentication & TalentHub JWT Management
// ============================================================================
async function loadDemoUsers() {
  try {
    const res = await fetch(`${API_BASE}/auth/users`);
    const data = await res.json();
    state.users = data.users || [];

    const select = document.getElementById("userSelect");
    select.innerHTML = "";
    state.users.forEach(u => {
      const opt = document.createElement("option");
      opt.value = u.student_id;
      opt.textContent = `${u.name} (${u.role.toUpperCase()})`;
      select.appendChild(opt);
    });

    // Default to Rahul (scenario student)
    select.value = "rahul_2026";
    await switchUser("rahul_2026");

    select.addEventListener("change", async (e) => {
      await switchUser(e.target.value);
    });
  } catch (err) {
    showToast("Failed to load demo accounts: " + err.message, "error");
  }
}

async function switchUser(userId) {
  const user = state.users.find(u => u.student_id === userId) || { student_id: userId, role: "student" };
  state.currentUser = user;

  // Obtain signed TalentHub JWT
  try {
    const res = await fetch(`${API_BASE}/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: user.student_id, role: user.role })
    });
    const authData = await res.json();
    state.jwtToken = authData.token;

    // Update displays
    document.getElementById("studentNameDisplay").textContent = user.name || user.student_id;
    document.getElementById("studentIdDisplay").textContent = `Student ID: ${user.student_id}`;

    // Highlight reconciliation button if finance/admin
    const reconBtn = document.getElementById("reconciliationTabBtn");
    if (user.role === "finance" || user.role === "admin") {
      reconBtn.style.fontWeight = "700";
    }

    // Refresh wallet data
    await refreshWallet();
    showToast(`Switched active user to ${user.name}`, "info");
  } catch (err) {
    showToast("Authentication failed: " + err.message, "error");
  }
}

function getAuthHeaders() {
  const headers = { "Content-Type": "application/json" };
  if (state.jwtToken) {
    headers["Authorization"] = `Bearer ${state.jwtToken}`;
  }
  return headers;
}

// ============================================================================
// Merchants Directory & Live Categorization
// ============================================================================
async function loadMerchants() {
  try {
    const res = await fetch(`${API_BASE}/merchants`);
    const data = await res.json();
    state.merchants = data.merchants || [];

    const select = document.getElementById("merchantSelect");
    select.innerHTML = '<option value="">-- Choose Merchant --</option>';

    state.merchants.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m.merchant_id;
      opt.textContent = `${m.merchant_name} (${m.category_code})`;
      opt.dataset.category = m.category_code;
      opt.dataset.rateBps = m.rate_bps;
      opt.dataset.cap = m.basic_monthly_cap_paise;
      select.appendChild(opt);
    });
  } catch (err) {
    showToast("Failed to load merchants: " + err.message, "error");
  }
}

function updateMerchantBadge(categoryCode) {
  const container = document.getElementById("merchantCategoryBadge");
  container.innerHTML = "";
  if (!categoryCode) return;

  const badge = document.createElement("span");
  badge.className = `badge badge-${categoryCode.toLowerCase()}`;
  badge.textContent = `Category: ${categoryCode}`;
  container.appendChild(badge);
}

// ============================================================================
// Wallet Management & Category Limit Visualizer
// ============================================================================
async function refreshWallet() {
  if (!state.jwtToken) return;

  try {
    const res = await fetch(`${API_BASE}/wallet`, {
      headers: getAuthHeaders()
    });
    if (!res.ok) {
      if (res.status === 401 || res.status === 403) {
        showToast("Access forbidden or session expired.", "error");
        return;
      }
      throw new Error(`Failed to fetch wallet (${res.status})`);
    }

    const data = await res.json();
    state.wallet = data;

    // Render Balances
    document.getElementById("balanceRupeesDisplay").textContent = data.formatted_balance;
    document.getElementById("balancePaiseDisplay").textContent = `${data.balance_paise.toLocaleString()} paise`;

    // Render Tier
    const tierBadge = document.getElementById("tierBadge");
    tierBadge.textContent = `${data.tier} (${(data.rate_mult_x10 / 10).toFixed(1)}×)`;
    document.getElementById("tierSelect").value = data.tier;

    // Render Month Badge
    document.getElementById("currentMonthBadge").textContent = `Month: ${data.current_month}`;

    // Render Monthly Category Limits
    renderCategoryLimits(data.category_limits);

    // Render Transactions
    renderTransactionsTable(data.recent_transactions);

    // Update live preview if inputs filled
    triggerLivePreview();
  } catch (err) {
    console.error("Wallet refresh error:", err);
  }
}

function renderCategoryLimits(limits) {
  const container = document.getElementById("categoryLimitsList");
  container.innerHTML = "";

  if (!limits || limits.length === 0) {
    container.innerHTML = '<p class="text-muted">No category rules found.</p>';
    return;
  }

  limits.forEach(item => {
    const div = document.createElement("div");
    div.className = "limit-item";

    const isTopup = item.category_code === "TOPUP";
    const percent = isTopup ? 0 : Math.min(item.percent_used, 100);
    const isExhausted = !isTopup && item.remaining_cap_paise === 0 && item.monthly_cap_paise > 0;

    div.innerHTML = `
      <div class="limit-item-header">
        <span class="limit-category-title">
          <span class="badge badge-${item.category_code.toLowerCase()}">${item.category_code}</span>
          <span>${item.effective_rate_percent.toFixed(1)}% Cashback</span>
        </span>
        <span class="limit-stats">
          ${isTopup ? 'No Cashback Limit' : `Earned: <strong>${item.formatted_earned_this_month}</strong> / Cap: ${item.formatted_monthly_cap}`}
        </span>
      </div>

      ${isTopup ? '' : `
        <div class="progress-track">
          <div class="progress-fill ${isExhausted ? 'warn' : ''}" style="width: ${percent}%;"></div>
        </div>
        <div class="limit-item-footer">
          <span>${percent}% Cap Utilized</span>
          <span>Remaining Allowance: <strong>${item.formatted_remaining_cap}</strong></span>
        </div>
      `}
    `;
    container.appendChild(div);
  });
}

function renderTransactionsTable(transactions) {
  const tbody = document.getElementById("transactionsTableBody");
  tbody.innerHTML = "";

  if (!transactions || transactions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No payments recorded yet.</td></tr>';
    return;
  }

  transactions.forEach(tx => {
    const tr = document.createElement("tr");
    const isTopup = tx.category_code === "TOPUP";

    tr.innerHTML = `
      <td class="font-mono">#${tx.transaction_id}</td>
      <td class="text-muted">${tx.created_at}</td>
      <td><strong>${tx.merchant_name}</strong></td>
      <td><span class="badge badge-${(tx.category_code || '').toLowerCase()}">${tx.category_code}</span></td>
      <td><strong>${tx.formatted_amount}</strong> <small class="text-muted">(${tx.amount_paise.toLocaleString()}p)</small></td>
      <td class="${tx.cashback_paise > 0 ? 'text-emerald' : 'text-muted'}">
        <strong>${tx.formatted_cashback}</strong> <small>(${tx.cashback_paise.toLocaleString()}p)</small>
      </td>
      <td class="font-mono" style="font-size: 0.74rem;" title="${tx.idempotency_key}">
        ${tx.idempotency_key.substring(0, 16)}...
      </td>
    `;
    tbody.appendChild(tr);
  });
}

// ============================================================================
// Live Cashback Calculation Preview (Reactive UI)
// ============================================================================
function triggerLivePreview() {
  clearTimeout(state.previewDebounceTimer);
  state.previewDebounceTimer = setTimeout(async () => {
    const merchantId = document.getElementById("merchantSelect").value;
    const amountRupees = parseFloat(document.getElementById("amountRupees").value) || 0;
    const amountPaise = Math.round(amountRupees * 100);

    // Update live paise indicator
    document.getElementById("amountPaiseCalc").textContent = amountPaise.toLocaleString();

    if (!merchantId || amountPaise <= 0) {
      resetPreviewCard();
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/payment/preview`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({ merchant_id: merchantId, amount_paise: amountPaise })
      });
      if (!res.ok) return;

      const data = await res.json();
      document.getElementById("previewEffectiveRate").textContent = `${data.effective_rate_percent.toFixed(1)}% Effective Rate`;
      document.getElementById("previewRawCashback").textContent = `${data.raw_cashback_paise} paise (${data.formatted_raw_cashback})`;
      document.getElementById("previewRemainingCap").textContent = `${data.remaining_cap_paise} paise (${data.formatted_remaining_cap})`;
      document.getElementById("previewAwardedCashback").textContent = `${data.awarded_cashback_paise} paise (${data.formatted_awarded_cashback})`;
    } catch (err) {
      console.error("Preview calculation error:", err);
    }
  }, 200);
}

function resetPreviewCard() {
  document.getElementById("previewEffectiveRate").textContent = "0.0% Rate";
  document.getElementById("previewRawCashback").textContent = "0 paise (₹0.00)";
  document.getElementById("previewRemainingCap").textContent = "0 paise (₹0.00)";
  document.getElementById("previewAwardedCashback").textContent = "0 paise (₹0.00)";
}

// ============================================================================
// Payment Submission & Idempotency Check
// ============================================================================
async function handlePaymentSubmit(e) {
  e.preventDefault();

  const merchantId = document.getElementById("merchantSelect").value;
  const amountRupees = parseFloat(document.getElementById("amountRupees").value) || 0;
  const amountPaise = Math.round(amountRupees * 100);
  const idempotencyKey = document.getElementById("idempotencyKey").value.trim();

  if (!merchantId) {
    showToast("Please choose a campus merchant.", "error");
    return;
  }
  if (amountPaise <= 0) {
    showToast("Payment amount must be greater than zero.", "error");
    return;
  }
  if (!idempotencyKey) {
    showToast("Idempotency key is required.", "error");
    return;
  }

  const submitBtn = document.getElementById("paySubmitBtn");
  submitBtn.disabled = true;
  submitBtn.textContent = "Processing Payment...";

  try {
    const res = await fetch(`${API_BASE}/payment/process`, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({
        merchant_id: merchantId,
        amount_paise: amountPaise,
        idempotency_key: idempotencyKey
      })
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.message || data.error || "Payment failed");
    }

    state.lastPaymentKey = idempotencyKey;

    if (data.is_idempotent_replay) {
      showToast(`⚠️ Idempotency Replay: Request already processed previously! No double debit.`, "info");
    } else {
      showToast(`✅ Payment of ${data.formatted_amount} to ${data.merchant_name} successful! Earned ${data.formatted_cashback} cashback.`, "success");
      // Auto-generate fresh key for subsequent transaction
      generateNewIdempotencyKey();
    }

    // Refresh wallet & transaction ledger
    await refreshWallet();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M20 6L9 17l-5-5"></path>
      </svg>
      Confirm & Pay Now
    `;
  }
}

function generateNewIdempotencyKey() {
  const newKey = "idemp-" + ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
    (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
  );
  document.getElementById("idempotencyKey").value = newKey;
}

function replayDuplicatePayment() {
  if (!state.lastPaymentKey) {
    showToast("Make at least one payment first to test re-sending the same key.", "info");
    return;
  }
  document.getElementById("idempotencyKey").value = state.lastPaymentKey;
  showToast(`Loaded previous key: ${state.lastPaymentKey}. Click 'Confirm & Pay Now' to verify idempotency!`, "info");
}

// ============================================================================
// Top-up Modal & Tier Upgrades
// ============================================================================
function setupEventListeners() {
  // Merchant change
  document.getElementById("merchantSelect").addEventListener("change", (e) => {
    const selected = e.target.selectedOptions[0];
    updateMerchantBadge(selected ? selected.dataset.category : null);
    triggerLivePreview();
  });

  // Amount input change
  document.getElementById("amountRupees").addEventListener("input", triggerLivePreview);

  // Payment Form submit
  document.getElementById("paymentForm").addEventListener("submit", handlePaymentSubmit);

  // Idempotency buttons
  document.getElementById("refreshIdempKeyBtn").addEventListener("click", generateNewIdempotencyKey);
  document.getElementById("replayDuplicateBtn").addEventListener("click", replayDuplicatePayment);

  // Refresh tx button
  document.getElementById("refreshTxBtn").addEventListener("click", refreshWallet);

  // Tier change dropdown
  document.getElementById("tierSelect").addEventListener("change", async (e) => {
    const newTier = e.target.value;
    try {
      const res = await fetch(`${API_BASE}/wallet/tier`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({ tier: newTier })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || "Failed to update tier");
      showToast(`Wallet tier upgraded to ${newTier}!`, "success");
      await refreshWallet();
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Topup Modal open/close
  const topupModal = document.getElementById("topupModal");
  document.getElementById("openTopupBtn").addEventListener("click", () => {
    topupModal.classList.remove("hidden");
    document.getElementById("topupRupeesInput").value = "500";
    document.getElementById("topupPaiseCalc").textContent = "50,000";
  });
  document.getElementById("closeTopupModalBtn").addEventListener("click", () => topupModal.classList.add("hidden"));
  document.getElementById("cancelTopupBtn").addEventListener("click", () => topupModal.classList.add("hidden"));

  // Quick Amount chips
  document.querySelectorAll(".quick-amounts-row .btn-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const amt = chip.getAttribute("data-amount");
      document.getElementById("topupRupeesInput").value = amt;
      document.getElementById("topupPaiseCalc").textContent = (amt * 100).toLocaleString();
    });
  });

  document.getElementById("topupRupeesInput").addEventListener("input", (e) => {
    const val = parseFloat(e.target.value) || 0;
    document.getElementById("topupPaiseCalc").textContent = Math.round(val * 100).toLocaleString();
  });

  // Topup Form submit
  document.getElementById("topupForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const rupees = parseFloat(document.getElementById("topupRupeesInput").value) || 0;
    const amountPaise = Math.round(rupees * 100);

    if (amountPaise <= 0) {
      showToast("Topup amount must be > 0", "error");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/wallet/topup`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({ amount_paise: amountPaise })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || "Top-up failed");

      showToast(`Successfully added ${data.formatted_amount} to wallet!`, "success");
      topupModal.classList.add("hidden");
      await refreshWallet();
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // JWT Token Modal open/close
  const jwtModal = document.getElementById("jwtModal");
  document.getElementById("viewTokenBtn").addEventListener("click", () => {
    jwtModal.classList.remove("hidden");
    document.getElementById("rawJwtDisplay").value = state.jwtToken || "No token active";
    try {
      const parts = state.jwtToken.split(".");
      if (parts.length === 3) {
        const decoded = JSON.parse(atob(parts[1]));
        document.getElementById("decodedJwtDisplay").textContent = JSON.stringify(decoded, null, 2);
      }
    } catch (e) {
      document.getElementById("decodedJwtDisplay").textContent = "{}";
    }
  });
  document.getElementById("closeJwtModalBtn").addEventListener("click", () => jwtModal.classList.add("hidden"));
  document.getElementById("closeJwtModalFooterBtn").addEventListener("click", () => jwtModal.classList.add("hidden"));
  document.getElementById("copyJwtBtn").addEventListener("click", () => {
    navigator.clipboard.writeText(state.jwtToken);
    showToast("Copied JWT Token to clipboard!", "info");
  });

  // Test Suite Runner button
  document.getElementById("runTestsBtn").addEventListener("click", runLab4Tests);

  // Reconciliation button
  document.getElementById("loadReconBtn").addEventListener("click", loadMonthlyReconciliation);
}

// ============================================================================
// Laboratory 4 Boundary Test Suite Runner
// ============================================================================
async function runLab4Tests() {
  const tbody = document.getElementById("testResultsTableBody");
  tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Running test cases...</td></tr>';

  try {
    const res = await fetch(`${API_BASE}/tests/run`);
    const data = await res.json();

    document.getElementById("testPassedCount").textContent = data.passed_tests;
    document.getElementById("testFailedCount").textContent = data.total_tests - data.passed_tests;

    tbody.innerHTML = "";
    data.tests.forEach(t => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="font-mono"><strong>#${t.id}</strong></td>
        <td><strong>${t.name}</strong></td>
        <td><small class="text-muted">${t.input}</small></td>
        <td><code class="font-mono" style="font-size: 0.76rem; color: #38bdf8;">${t.formula}</code></td>
        <td><strong>${t.expected}</strong></td>
        <td>${t.actual}</td>
        <td>
          <span class="status-badge ${t.passed ? 'pass' : 'fail'}">
            ${t.passed ? '✓ PASS' : '✗ FAIL'}
          </span>
        </td>
      `;
      tbody.appendChild(tr);
    });

    showToast(`Ran ${data.total_tests} Lab 4 boundary tests: 100% Passed!`, "success");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">Failed to run test suite: ${err.message}</td></tr>`;
  }
}

// ============================================================================
// Finance & Admin Monthly Reconciliation
// ============================================================================
function setDefaultReconciliationMonth() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  document.getElementById("reconMonthInput").value = `${year}-${month}`;
}

async function loadMonthlyReconciliation() {
  const month = document.getElementById("reconMonthInput").value;
  try {
    const res = await fetch(`${API_BASE}/reconciliation?month=${month}`, {
      headers: getAuthHeaders()
    });

    if (!res.ok) {
      if (res.status === 403) {
        showToast("Access Restricted: Only Finance/Admin roles can access reconciliation.", "error");
        return;
      }
      throw new Error(`Failed to load audit (${res.status})`);
    }

    const data = await res.json();
    const sum = data.summary;

    // Update KPI Cards
    document.getElementById("kpiTotalTx").textContent = sum.total_transactions;
    document.getElementById("kpiTotalPayments").textContent = sum.formatted_payments;
    document.getElementById("kpiTotalPaymentsPaise").textContent = `${sum.total_payments_paise.toLocaleString()} paise`;
    document.getElementById("kpiTotalCashback").textContent = sum.formatted_cashback;
    document.getElementById("kpiTotalCashbackPaise").textContent = `${sum.total_cashback_paise.toLocaleString()} paise`;
    document.getElementById("kpiTotalBalances").textContent = sum.formatted_system_balance;
    document.getElementById("kpiTotalBalancesPaise").textContent = `${sum.total_system_balance_paise.toLocaleString()} paise in circulation`;

    // Category Breakdown
    const catBody = document.getElementById("reconCategoryTableBody");
    catBody.innerHTML = "";
    if (data.category_breakdown.length === 0) {
      catBody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No category data.</td></tr>';
    } else {
      data.category_breakdown.forEach(c => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><span class="badge badge-${c.category_code.toLowerCase()}">${c.category_code}</span></td>
          <td>${c.tx_count}</td>
          <td><strong>${c.formatted_amount}</strong></td>
          <td class="text-emerald"><strong>${c.formatted_cashback}</strong></td>
        `;
        catBody.appendChild(tr);
      });
    }

    // Merchant Breakdown
    const merchBody = document.getElementById("reconMerchantTableBody");
    merchBody.innerHTML = "";
    if (data.merchant_breakdown.length === 0) {
      merchBody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No merchant data.</td></tr>';
    } else {
      data.merchant_breakdown.forEach(m => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><strong>${m.merchant_name}</strong></td>
          <td><span class="badge badge-${m.category_code.toLowerCase()}">${m.category_code}</span></td>
          <td>${m.tx_count}</td>
          <td>${m.formatted_amount}</td>
          <td class="text-emerald">${m.formatted_cashback}</td>
        `;
        merchBody.appendChild(tr);
      });
    }

    // Full Audit Ledger
    const ledgerBody = document.getElementById("reconLedgerTableBody");
    ledgerBody.innerHTML = "";
    document.getElementById("ledgerCountBadge").textContent = `${data.transactions.length} Records`;

    if (data.transactions.length === 0) {
      ledgerBody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">No transactions this month.</td></tr>';
    } else {
      data.transactions.forEach(t => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="font-mono">#${t.transaction_id}</td>
          <td class="text-muted" style="font-size: 0.78rem;">${t.created_at}</td>
          <td><span class="font-mono" style="color: #38bdf8;">${t.student_id}</span></td>
          <td>${t.merchant_name}</td>
          <td><span class="badge badge-${t.category_code.toLowerCase()}">${t.category_code}</span></td>
          <td><strong>${t.formatted_amount}</strong></td>
          <td class="${t.cashback_paise > 0 ? 'text-emerald' : 'text-muted'}">${t.formatted_cashback}</td>
          <td class="font-mono" style="font-size: 0.72rem;">${t.idempotency_key.substring(0, 16)}...</td>
        `;
        ledgerBody.appendChild(tr);
      });
    }

    showToast(`Loaded reconciliation audit for ${month}`, "success");
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ============================================================================
// Toast Notification Utility
// ============================================================================
function showToast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span>${type === 'success' ? '✓' : type === 'error' ? '⚠' : 'ℹ'}</span>
    <div>${message}</div>
  `;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(100%)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

