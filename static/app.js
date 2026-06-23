'use strict';

// ── State ──────────────────────────────────────────────────────────────────
let currentJobId = null;
let pollTimer = null;

// ── DOM refs ───────────────────────────────────────────────────────────────
const stepUpload   = document.getElementById('step-upload');
const stepProgress = document.getElementById('step-progress');
const stepResults  = document.getElementById('step-results');

const dropZone     = document.getElementById('drop-zone');
const fileInput    = document.getElementById('file-input');
const fileNameEl   = document.getElementById('file-name');
const uploadError  = document.getElementById('upload-error');

const detectedCols = document.getElementById('detected-cols');
const progressBar  = document.getElementById('progress-bar');
const progressText = document.getElementById('progress-text');

const totalUsd     = document.getElementById('total-usd');
const totalVnd     = document.getElementById('total-vnd');
const exchangeRate = document.getElementById('exchange-rate');
const notFoundBox  = document.getElementById('not-found-box');
const notFoundList = document.getElementById('not-found-list');
const resultsBody  = document.getElementById('results-body');
const previewNote  = document.getElementById('preview-note');
const btnDownload  = document.getElementById('btn-download');

// ── Upload / drag-drop ────────────────────────────────────────────────────
// Skip fileInput.click() when clicking the <label> — the label already triggers it natively
dropZone.addEventListener('click', (e) => {
  if (e.target.closest('label')) return;
  fileInput.click();
});
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) handleFile(fileInput.files[0]);
});

async function handleFile(file) {
  // Cancel any in-progress job and clear previous results
  if (pollTimer) clearInterval(pollTimer);
  currentJobId = null;
  resultsBody.innerHTML = '';
  notFoundList.innerHTML = '';
  detectedCols.textContent = '';
  hide(notFoundBox);
  hide(stepResults);
  hide(stepProgress);
  show(stepUpload);

  showError(uploadError, '');
  fileNameEl.textContent = file.name;

  const formData = new FormData();
  formData.append('file', file);

  let data;
  try {
    const resp = await fetch('/api/upload', { method: 'POST', body: formData });
    data = await resp.json();
    if (!resp.ok) {
      showError(uploadError, data.detail || 'Upload failed.');
      fileNameEl.textContent = '';
      return;
    }
  } catch {
    showError(uploadError, 'Network error. Please try again.');
    fileNameEl.textContent = '';
    return;
  }

  currentJobId = data.job_id;

  // Show which columns were auto-detected
  detectedCols.textContent =
    `Auto-detected — Part Number: "${data.detected_part_col}"  ·  Quantity: "${data.detected_qty_col}"`;

  // Go straight to progress screen
  show(stepProgress);
  progressBar.style.width = '0%';
  progressText.textContent = `0 / ${data.total} parts processed`;
  startPolling(data.total);
}

// ── Polling ───────────────────────────────────────────────────────────────
function startPolling(total) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => pollJob(total), 2000);
}

async function pollJob(total) {
  let data;
  try {
    const resp = await fetch(`/api/jobs/${currentJobId}`);
    data = await resp.json();
    if (!resp.ok) return;
  } catch { return; }

  const pct = data.progress || 0;
  const done = Math.round(pct / 100 * (data.total || total));
  progressBar.style.width = `${pct}%`;
  progressText.textContent = `${done} / ${data.total || total} parts processed (${pct}%)`;

  if (data.status === 'done') {
    clearInterval(pollTimer);
    hide(stepProgress);
    renderResults(data);
    show(stepResults);
  } else if (data.status === 'error') {
    clearInterval(pollTimer);
    hide(stepProgress);
    showError(uploadError, `Processing error: ${data.error}`);
    show(stepUpload);
  }
}

// ── Results ───────────────────────────────────────────────────────────────
function renderResults(data) {
  totalUsd.textContent     = data.grand_total_usd || '—';
  totalVnd.textContent     = data.grand_total_vnd || '—';
  exchangeRate.textContent = data.usd_to_vnd
    ? `1 USD = ${Number(data.usd_to_vnd).toLocaleString()} VND`
    : '—';

  if (data.not_found_parts && data.not_found_parts.length > 0) {
    notFoundList.innerHTML = data.not_found_parts
      .map(p => `<li>${escHtml(p)}</li>`).join('');
    show(notFoundBox);
  } else {
    hide(notFoundBox);
  }

  resultsBody.innerHTML = '';
  (data.preview || []).forEach(row => {
    let cls;
    if (row.no_part_number) {
      cls = 'row-gray';
    } else {
      const found = row.best_supplier !== 'Not Found';
      const suppliers = [row.mouser, row.digikey, row.lcsc].filter(v => v !== 'N/A');
      cls = !found ? 'row-red' : suppliers.length === 1 ? 'row-yellow' : 'row-green';
    }
    const tr = document.createElement('tr');
    tr.className = cls;
    tr.innerHTML = `
      <td>${row.no_part_number ? '<em>(no part number)</em>' : escHtml(row.part_number)}</td>
      <td>${row.quantity}</td>
      <td>${row.no_part_number ? '<em>No Part Number</em>' : '<strong>' + escHtml(row.best_supplier) + '</strong>'}</td>
      <td>${row.best_unit_price_usd}</td>
      <td>${row.best_unit_price_vnd}</td>
      <td>${row.total_line_usd}</td>
      <td>${row.mouser}</td>
      <td>${row.digikey}</td>
      <td>${row.lcsc}</td>
    `;
    resultsBody.appendChild(tr);
  });

  if ((data.preview || []).length < (data.total || 0)) {
    previewNote.textContent =
      `Showing first ${data.preview.length} of ${data.total} rows. Download Excel for full results.`;
  } else {
    previewNote.textContent = '';
  }
}

// ── Download ──────────────────────────────────────────────────────────────
btnDownload.addEventListener('click', () => {
  window.location.href = `/api/download/${currentJobId}`;
});

// ── Helpers ───────────────────────────────────────────────────────────────
function show(el) { el.hidden = false; }
function hide(el) { el.hidden = true; }

function showError(el, msg) {
  el.textContent = msg;
  el.hidden = !msg;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
