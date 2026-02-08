const credentials = { credentials: "include" };

const screenLogin = document.getElementById("screen-login");
const screenSignup = document.getElementById("screen-signup");
const screenDashboard = document.getElementById("screen-dashboard");
const screenDoc = document.getElementById("screen-doc");
const screenProfile = document.getElementById("screen-profile");
const loginForm = document.getElementById("loginForm");
const loginError = document.getElementById("loginError");
const loginSuccess = document.getElementById("loginSuccess");
const signUpForm = document.getElementById("signUpForm");
const signUpError = document.getElementById("signUpError");
const userName = document.getElementById("userName");
const userMenuWrap = document.getElementById("userMenuWrap");
const userMenuDropdown = document.getElementById("userMenuDropdown");
const btnProfile = document.getElementById("btnProfile");
const btnLogout = document.getElementById("btnLogout");
const btnBackFromProfile = document.getElementById("btnBackFromProfile");
const profileForm = document.getElementById("profileForm");
const profileFullNameInput = document.getElementById("profileFullNameInput");
const profileCompanyNameInput = document.getElementById("profileCompanyNameInput");
const profileError = document.getElementById("profileError");
const profileSuccess = document.getElementById("profileSuccess");
const profileAvatar = document.getElementById("profileAvatar");
const profileHeroName = document.getElementById("profileHeroName");
const profileHeroUsername = document.getElementById("profileHeroUsername");
const profileHeroCompany = document.getElementById("profileHeroCompany");
const passwordForm = document.getElementById("passwordForm");
const passwordError = document.getElementById("passwordError");
const passwordSuccess = document.getElementById("passwordSuccess");
const btnNewDoc = document.getElementById("btnNewDoc");
const btnDeleteAll = document.getElementById("btnDeleteAll");
const dashTableBody = document.getElementById("dashTableBody");
const dashEmpty = document.getElementById("dashEmpty");
const modalBackdrop = document.getElementById("modalBackdrop");
const newDocForm = document.getElementById("newDocForm");
const newDocName = document.getElementById("newDocName");
const newDocDesc = document.getElementById("newDocDesc");
const newDocFile = document.getElementById("newDocFile");
const modalCancel = document.getElementById("modalCancel");
const modalSubmit = document.getElementById("modalSubmit");
const btnBackToDashboard = document.getElementById("btnBackToDashboard");

const modalSubmitLabel = document.getElementById("modalSubmitLabel");
const docTable = document.getElementById("docTable");
const docSelect = document.getElementById("docSelect");
const typoList = document.getElementById("typoList");
const typoMeta = document.getElementById("typoMeta");
const downloadLink = document.getElementById("downloadLink");
const reprocessDocBtn = document.getElementById("reprocessDocBtn");
const regeneratePdfBtn = document.getElementById("regeneratePdfBtn");
const openInNewTab = document.getElementById("openInNewTab");
const pdfIframe = document.getElementById("pdfIframe");
const viewerPlaceholder = document.getElementById("viewerPlaceholder");
const prevPageBtn = document.getElementById("prevPageBtn");
const nextPageBtn = document.getElementById("nextPageBtn");
const pageLabel = document.getElementById("pageLabel");
const refreshBtn = document.getElementById("refreshBtn");
const addAllToAllowlistBtn = document.getElementById("addAllToAllowlistBtn");
const typoSelectAll = document.getElementById("typoSelectAll");
const reviewPanelEmpty = document.getElementById("reviewPanelEmpty");
const reviewPanelContent = document.getElementById("reviewPanelContent");
const reviewWord = document.getElementById("reviewWord");
const reviewStatusBadge = document.getElementById("reviewStatusBadge");
const reviewApproveBtn = document.getElementById("reviewApproveBtn");
const reviewApproveAllBtn = document.getElementById("reviewApproveAllBtn");
const reviewFlagBtn = document.getElementById("reviewFlagBtn");
const reviewFlagAllBtn = document.getElementById("reviewFlagAllBtn");
const reviewDescription = document.getElementById("reviewDescription");
const reviewPrevBtn = document.getElementById("reviewPrevBtn");
const reviewNextBtn = document.getElementById("reviewNextBtn");
const reviewNavLabel = document.getElementById("reviewNavLabel");
const reviewInstanceLabel = document.getElementById("reviewInstanceLabel");
const reviewCloseBtn = document.getElementById("reviewCloseBtn");
const reviewPrevWordBtn = document.getElementById("reviewPrevWordBtn");
const reviewNextWordBtn = document.getElementById("reviewNextWordBtn");
const typoListToggleTypos = document.getElementById("typoListToggleTypos");
const typoListToggleNonTypos = document.getElementById("typoListToggleNonTypos");
const typoSelectControls = document.querySelector(".typo-select-controls");
const typoPanelTitle = document.getElementById("typoPanelTitle");

let docs = [];
let currentUserId = null; // set from /api/me for ownership checks
let activeDocId = null;
let activeResult = null;
let hasAnnotatedPdf = false; // from doc info; when false, viewer uses original PDF
let pageNum = 1;
let totalPages = 0;
// Track selected words (group-level selection)
let selectedAllowlistWords = new Set();
let selectedTypoForReview = null;  // { typo, idx } or null
// Toggle between Typos list and Non-typos list (words checked but not flagged)
let showNonTyposList = false;

function escapeHtml(str) {
  return (str || "").replace(/[&<>'"]/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  }[c]));
}

function escapeAttr(str) {
  return (str || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function api(path, opts = {}) {
  const res = await fetch(path, { ...credentials, ...opts });
  if (!res.ok) throw new Error(await res.text());
  return res;
}

function showScreen(id) {
  screenLogin.classList.remove("active");
  if (screenSignup) screenSignup.classList.remove("active");
  screenDashboard.classList.remove("active");
  screenDoc.classList.remove("active");
  const el = document.getElementById("screen-" + id);
  if (el) el.classList.add("active");
}

// Routes: /login, /signup, /dashboard, /doc/:id (and / for login)
function getRoute() {
  const path = (location.pathname || "/").replace(/\/$/, "") || "/";
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "doc" && parts[1]) return { name: "doc", docId: parts[1] };
  if (parts[0] === "signup") return { name: "signup" };
  if (parts[0] === "dashboard") return { name: "dashboard" };
  if (parts[0] === "profile") return { name: "profile" };
  if (parts[0] === "login" || path === "/" || path === "") return { name: "login" };
  return { name: "login" };
}

function getHashDocId() {
  const r = getRoute();
  return r.name === "doc" ? r.docId : null;
}

async function checkAuth() {
  try {
    const res = await fetch("/api/me", credentials);
    const data = res.ok ? await res.json().catch(() => ({})) : {};
    currentUserId = (data && data.user_id) || null;
    return res.ok;
  } catch (_) {
    currentUserId = null;
    return false;
  }
}

// --- Login (#/login) ---
loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  loginError.style.display = "none";
  loginSuccess.style.display = "none";
  const username = document.getElementById("loginUsername").value.trim();
  const password = document.getElementById("loginPassword").value;
  try {
    const res = await fetch("/api/login", {
      ...credentials,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      loginError.style.display = "block";
      return;
    }
    location.href = "/dashboard";
    return;
  } catch (_) {
    loginError.style.display = "block";
  }
});

// --- Sign up (#/signup) ---
signUpForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  signUpError.style.display = "none";
  signUpError.textContent = "";
  const full_name = document.getElementById("signUpFullName")?.value?.trim() || "";
  const company_name = document.getElementById("signUpCompanyName")?.value?.trim() || "";
  const username = document.getElementById("signUpUsername").value.trim();
  const password = document.getElementById("signUpPassword").value;
  const confirm = document.getElementById("signUpPasswordConfirm").value;
  if (password !== confirm) {
    signUpError.textContent = "Passwords do not match.";
    signUpError.style.display = "block";
    return;
  }
  try {
    const res = await fetch("/api/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, full_name, company_name }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      const detail = data.detail;
      signUpError.textContent = typeof detail === "string" ? detail : Array.isArray(detail) ? (detail[0]?.msg || "Registration failed.") : "Registration failed.";
      signUpError.style.display = "block";
      return;
    }
    // Log the user in and go to dashboard
    const loginRes = await fetch("/api/login", {
      ...credentials,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (loginRes.ok) {
      location.href = "/dashboard";
      return;
    } else {
      location.href = "/login";
      return;
    }
  } catch (_) {
    signUpError.textContent = "Registration failed. Try again.";
    signUpError.style.display = "block";
  }
});

// User dropdown
if (userName) {
  userName.addEventListener("click", (e) => {
    e.stopPropagation();
    if (userMenuDropdown) {
      userMenuDropdown.style.display = userMenuDropdown.style.display === "none" ? "block" : "none";
    }
  });
  
  // Close dropdown when clicking outside
  document.addEventListener("click", (e) => {
    if (userMenuWrap && !userMenuWrap.contains(e.target)) {
      if (userMenuDropdown) userMenuDropdown.style.display = "none";
    }
  });
}

if (btnProfile) {
  btnProfile.addEventListener("click", (e) => {
    e.preventDefault();
    if (userMenuDropdown) userMenuDropdown.style.display = "none";
    location.href = "/profile";
  });
}

btnLogout.addEventListener("click", async (e) => {
  e.preventDefault();
  try {
    await fetch("/api/logout", { ...credentials, method: "POST" });
  } catch (_) {}
  location.href = "/login";
});

// --- Dashboard ---
function formatProcessedOn(processedAt) {
  if (processedAt == null || processedAt === undefined) return "—";
  const d = new Date(typeof processedAt === "number" ? processedAt * 1000 : processedAt);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { dateStyle: "medium" });
}

async function loadDashboard() {
  try {
    const meRes = await api("/api/me");
    const meData = await meRes.json();
    currentUserId = meData.user_id || null;
    if (!meData.profile_complete) {
      showProfileCompleteModal(meData.full_name || "", meData.company_name || "");
      return;
    }
  } catch (_) {
    currentUserId = null;
  }
  try {
    const res = await api("/api/docs");
    const data = await res.json();
    docs = data.docs || [];
  } catch (_) {
    docs = [];
  }
  renderDashboardTable();
  const hasRunning = docs.some(d => d.status === "queued" || d.status === "processing");
  if (hasRunning) setTimeout(loadDashboard, 800);
}

function showProfileCompleteModal(fullName, companyName) {
  const backdrop = document.getElementById("profileCompleteBackdrop");
  const fullNameEl = document.getElementById("profileFullName");
  const companyNameEl = document.getElementById("profileCompanyName");
  if (backdrop && fullNameEl && companyNameEl) {
    fullNameEl.value = fullName || "";
    companyNameEl.value = companyName || "";
    document.getElementById("profileCompleteError").textContent = "";
    backdrop.style.display = "flex";
  }
}

function hideProfileCompleteModal() {
  const backdrop = document.getElementById("profileCompleteBackdrop");
  if (backdrop) backdrop.style.display = "none";
}

const profileCompleteForm = document.getElementById("profileCompleteForm");
if (profileCompleteForm) {
  profileCompleteForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errEl = document.getElementById("profileCompleteError");
    const fullName = document.getElementById("profileFullName")?.value?.trim() || "";
    const companyName = document.getElementById("profileCompanyName")?.value?.trim() || "";
    errEl.textContent = "";
    if (!fullName || !companyName) {
      errEl.textContent = "Please enter both full name and company name.";
      return;
    }
    try {
      await api("/api/me", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ full_name: fullName, company_name: companyName }),
      });
      hideProfileCompleteModal();
      loadDashboard();
    } catch (err) {
      errEl.textContent = err.message || "Failed to save profile.";
    }
  });
}

function renderDashboardTable() {
  let html = "";
  for (const d of docs) {
    const name = escapeHtml((d.name || d.filename || "Untitled").slice(0, 50));
    const statusLabel = d.status === "processing" && d.message
      ? statusPill(d.status) + " <span class=\"dash-status-msg\">" + escapeHtml(d.message) + "</span>"
      : statusPill(d.status);
    let resultCell;
    if (d.status === "done" && typeof d.typo_count === "number") {
      resultCell = escapeHtml(String(d.typo_count) + " typos");
    } else if (d.status === "queued" || d.status === "processing") {
      resultCell = `<span class="dash-result-actions"><button type="button" class="dash-result-btn dash-pause-btn" title="Pause processing" data-doc="${escapeAttr(d.doc_id)}" aria-label="Pause">⏸</button><button type="button" class="dash-result-btn dash-cancel-btn" title="Cancel and remove document" data-doc="${escapeAttr(d.doc_id)}" aria-label="Cancel">✕</button></span>`;
    } else if (d.status === "paused") {
      resultCell = `<span class="dash-result-actions"><button type="button" class="dash-result-btn dash-play-btn" title="Resume processing" data-doc="${escapeAttr(d.doc_id)}" aria-label="Resume">▶</button><button type="button" class="dash-result-btn dash-cancel-btn" title="Cancel and remove document" data-doc="${escapeAttr(d.doc_id)}" aria-label="Cancel">✕</button></span>`;
    } else {
      resultCell = "—";
    }
    const progressCell = d.status === "queued" || d.status === "processing"
      ? `<span class="dash-progress-wrap"><span class="dash-progress-track"><span class="dash-progress-bar" style="width:${Math.min(100, Math.max(0, d.progress))}%"></span></span><span class="dash-progress-pct">${d.progress}%</span></span>`
      : `${d.progress}%`;
    const processedBy = escapeHtml((d.processed_by_full_name || d.processed_by || "—").slice(0, 30));
    const processedOn = formatProcessedOn(d.processed_at);
    // Show review status: "In progress" pill when review is happening, "Under Review" when not reviewed yet, or reviewer name when complete
    let reviewedByCell = "—";
    const reviewStatus = d.review_status || {};
    const reviewerId = d.reviewed_by;
    const reviewerName = reviewerId 
      ? escapeHtml((d.reviewed_by_full_name || d.reviewed_by || reviewStatus.reviewed_by || "—").slice(0, 30))
      : (reviewStatus.reviewed_by ? escapeHtml(reviewStatus.reviewed_by.slice(0, 30)) : null);
    
    // Only show review status for documents that are done processing
    if (d.status === "done") {
      if (reviewStatus.is_complete) {
        // Review complete - show reviewer name
        reviewedByCell = reviewerName || "—";
      } else if (reviewStatus.reviewed_count > 0 || reviewerId) {
        // Review in progress - show "In progress" pill
        reviewedByCell = `<span class="dash-status-pill dash-status-processing">In progress</span>`;
        if (reviewerName) {
          reviewedByCell += ` <span class="dash-reviewer-name">${reviewerName}</span>`;
        }
      } else {
        // Not reviewed yet - show "Under Review" pill
        reviewedByCell = `<span class="dash-status-pill dash-status-processing">Under Review</span>`;
      }
    }
    const vis = (d.visibility || "private").toLowerCase();
    const isOwner = currentUserId && d.owner_id === currentUserId;
    const visibilityCell = `<label class="dash-visibility-toggle-switch ${!isOwner ? "dash-visibility-readonly" : ""}" title="${isOwner ? "Toggle visibility" : "Only the owner can change visibility"}">
          <input type="checkbox" class="dash-visibility-toggle-input" data-doc="${escapeAttr(d.doc_id)}" data-current="${vis}" ${vis === "public" ? "checked" : ""} ${!isOwner ? "disabled" : ""}>
          <span class="dash-visibility-toggle-slider">
            <span class="dash-visibility-toggle-label">${vis === "public" ? "public" : "private"}</span>
          </span>
        </label>`;
    const menuCells = isOwner
      ? `<td class="th-menu"><div class="row-menu-wrap"><button type="button" class="row-menu-btn" title="Actions">⋮</button><div class="row-menu-dropdown" style="display:none"><button type="button" class="row-menu-visibility">${vis === "public" ? "Make private" : "Make public"}</button><button type="button" class="row-menu-delete">Delete document</button></div></div></td>`
      : `<td class="th-menu"></td>`;
    html += `<tr data-doc="${escapeAttr(d.doc_id)}">
      <td>${name}</td>
      <td data-col="status">${statusLabel}</td>
      <td class="dash-progress-cell">${progressCell}</td>
      <td data-col="result">${resultCell}</td>
      <td>${processedBy}</td>
      <td>${processedOn}</td>
      <td>${reviewedByCell}</td>
      <td data-col="visibility">${visibilityCell}</td>
      ${menuCells}
    </tr>`;
  }
  dashTableBody.innerHTML = html || "<tr><td colspan='9' class='table-msg'>No documents</td></tr>";
  dashEmpty.style.display = docs.length ? "none" : "block";
  if (btnDeleteAll) btnDeleteAll.style.display = docs.length ? "" : "none";

  if (!dashTableBody._dropdownCloseBound) {
    dashTableBody._dropdownCloseBound = true;
    document.addEventListener("click", function closeRowDropdown(ev) {
      if (!ev.target.closest(".row-menu-wrap")) {
        dashTableBody.querySelectorAll(".row-menu-dropdown").forEach(d => {
          d.style.display = "none";
          d.classList.remove("is-fixed");
          d.style.top = d.style.left = d.style.right = "";
        });
      }
    });
  }

  dashTableBody.querySelectorAll("tr[data-doc]").forEach(tr => {
    const menuWrap = tr.querySelector(".row-menu-wrap");
    const menuBtn = tr.querySelector(".row-menu-btn");
    const dropdown = tr.querySelector(".row-menu-dropdown");
    const deleteBtn = tr.querySelector(".row-menu-delete");
    menuBtn?.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      const open = dropdown.style.display === "block";
      dashTableBody.querySelectorAll(".row-menu-dropdown").forEach(d => {
        d.style.display = "none";
        d.classList.remove("is-fixed");
        d.style.top = d.style.left = d.style.right = "";
      });
      if (!open) {
        const rect = menuBtn.getBoundingClientRect();
        const minW = 140;
        const pad = 12;
        let left = rect.left;
        if (left + minW > window.innerWidth - pad) left = window.innerWidth - minW - pad;
        if (left < pad) left = pad;
        dropdown.classList.add("is-fixed");
        dropdown.style.top = (rect.bottom + 2) + "px";
        dropdown.style.left = left + "px";
        dropdown.style.right = "auto";
        dropdown.style.display = "block";
      }
    });
    deleteBtn?.addEventListener("click", (e) => {
      e.stopPropagation();
      dropdown.style.display = "none";
      const id = tr.getAttribute("data-doc");
      if (!id) return;
      if (!confirm("Delete this document permanently? This cannot be undone.")) return;
      api(`/api/docs/${id}`, { method: "DELETE" }).then(() => loadDashboard()).catch(err => alert(err.message || "Delete failed"));
    });
    const visibilityToggleInput = tr.querySelector(".dash-visibility-toggle-input");
    visibilityToggleInput?.addEventListener("change", (e) => {
      e.stopPropagation();
      const id = tr.getAttribute("data-doc");
      if (!id) return;
      const current = visibilityToggleInput.getAttribute("data-current");
      const next = current === "public" ? "private" : "public";
      visibilityToggleInput.disabled = true;
      api(`/api/docs/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ visibility: next }) })
        .then(() => {
          visibilityToggleInput.setAttribute("data-current", next);
          const label = visibilityToggleInput.closest(".dash-visibility-toggle-switch")?.querySelector(".dash-visibility-toggle-label");
          if (label) label.textContent = next;
          loadDashboard();
        })
        .catch(err => {
          visibilityToggleInput.checked = current === "public";
          alert(err.message || "Update failed");
        })
        .finally(() => {
          visibilityToggleInput.disabled = false;
        });
    });
    const visibilityMenuBtn = dropdown?.querySelector(".row-menu-visibility");
    visibilityMenuBtn?.addEventListener("click", (e) => {
      e.stopPropagation();
      dropdown.style.display = "none";
      const id = tr.getAttribute("data-doc");
      if (!id) return;
      const next = visibilityMenuBtn.textContent.includes("private") ? "private" : "public";
      api(`/api/docs/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ visibility: next }) })
        .then(() => loadDashboard())
        .catch(err => alert(err.message || "Update failed"));
    });
    tr.addEventListener("click", (e) => {
      if (e.target.closest(".row-menu-wrap") || e.target.closest(".dash-result-btn") || e.target.closest(".dash-visibility-toggle-switch")) return;
      const id = tr.getAttribute("data-doc");
      location.href = "/doc/" + id;
    });
    const pauseBtn = tr.querySelector(".dash-pause-btn");
    const playBtn = tr.querySelector(".dash-play-btn");
    pauseBtn?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const id = tr.getAttribute("data-doc");
      if (!id) return;
      pauseBtn.disabled = true;
      api(`/api/docs/${id}/pause`, { method: "POST" }).then(() => loadDashboard()).catch(err => { pauseBtn.disabled = false; alert(err.message || "Pause failed"); });
    });
    playBtn?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const id = tr.getAttribute("data-doc");
      if (!id) return;
      playBtn.disabled = true;
      api(`/api/docs/${id}/resume`, { method: "POST" }).then(() => loadDashboard()).catch(err => { playBtn.disabled = false; alert(err.message || "Resume failed"); });
    });
    const cancelBtn = tr.querySelector(".dash-cancel-btn");
    cancelBtn?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const id = tr.getAttribute("data-doc");
      if (!id) return;
      if (!confirm("Cancel and remove this document? Processing will stop and the document will be deleted. This cannot be undone.")) return;
      cancelBtn.disabled = true;
      api(`/api/docs/${id}/cancel`, { method: "POST" }).then(() => loadDashboard()).catch(err => { cancelBtn.disabled = false; alert(err.message || "Cancel failed"); });
    });
  });
}

function statusPill(status) {
  const cls = status === "done" ? "ok" : (status === "failed" ? "bad" : "");
  return `<span class="pill ${cls}">${escapeHtml(status)}</span>`;
}

btnNewDoc.addEventListener("click", () => {
  newDocForm.reset();
  newDocError.textContent = "";
  modalBackdrop.classList.add("active");
});

btnDeleteAll?.addEventListener("click", async () => {
  if (!docs.length) return;
  if (!confirm("Permanently delete all " + docs.length + " document(s)? This cannot be undone. Any running jobs will be stopped.")) return;
  btnDeleteAll.disabled = true;
  try {
    const res = await api("/api/docs/delete-all", { method: "POST" });
    const data = await res.json();
    await loadDashboard();
  } catch (err) {
    alert(err.message || "Delete all failed");
  } finally {
    btnDeleteAll.disabled = false;
  }
});

modalCancel.addEventListener("click", () => modalBackdrop.classList.remove("active"));
modalBackdrop.addEventListener("click", (e) => {
  if (e.target === modalBackdrop) modalBackdrop.classList.remove("active");
});

const newDocError = document.createElement("p");
newDocError.className = "login-error";
newDocError.style.marginTop = "10px";
newDocForm.appendChild(newDocError);

function setUploadLoading(loading) {
  const hint = document.getElementById("uploadLoadingHint");
  modalSubmit.disabled = loading;
  if (loading) {
    modalSubmit.innerHTML = "<span class=\"upload-spinner\" aria-hidden=\"true\"></span> Uploading…";
    if (hint) hint.textContent = "Adding document… This may take a moment if another file is processing.";
  } else {
    modalSubmit.innerHTML = "<span id=\"modalSubmitLabel\">Upload</span>";
    if (hint) hint.textContent = "";
  }
}

newDocForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  newDocError.textContent = "";
  const name = newDocName.value.trim() || newDocFile.files[0]?.name || "Untitled";
  const description = newDocDesc.value.trim();
  const file = newDocFile.files[0];
  if (!file || !file.name.toLowerCase().endsWith(".pdf")) {
    newDocError.textContent = "Please select a PDF file.";
    return;
  }
  setUploadLoading(true);
  try {
    const fd = new FormData();
    const visibilityEl = document.getElementById("newDocVisibility");
    fd.append("name", name);
    fd.append("description", description);
    fd.append("visibility", visibilityEl ? visibilityEl.value : "private");
    fd.append("file", file);
    await api("/api/docs", { method: "POST", body: fd });
    modalBackdrop.classList.remove("active");
    await loadDashboard();
  } catch (err) {
    newDocError.textContent = err.message || "Upload failed.";
  } finally {
    setUploadLoading(false);
  }
});

// --- Doc view ---
function showDocView(docIdToSelect) {
  showScreen("doc");
  refreshDocs().then(() => {
    if (docIdToSelect) {
      selectDoc(docIdToSelect);
    }
  });
}

async function refreshDocs() {
  try {
    const res = await api("/api/docs");
    const data = await res.json();
    docs = data.docs || [];
  } catch (_) {
    docs = [];
  }
  renderDocs();
  renderDocSelect();
  refreshAllowlistPanel();
  const hasRunning = docs.some(d => d.status === "queued" || d.status === "processing");
  if (hasRunning) setTimeout(refreshDocs, 1500);
}

async function refreshAllowlistPanel() {
  const panel = document.getElementById("allowlistPanel");
  if (!panel) return;
  try {
    const res = await api("/api/allowlist");
    const data = await res.json();
    renderAllowlistPanel(data.words || []);
  } catch (_) {
    panel.innerHTML = "<span class=\"muted\">Could not load allowlist.</span>";
  }
}

function renderAllowlistPanel(words) {
  const panel = document.getElementById("allowlistPanel");
  if (!panel) return;
  if (!words.length) {
    panel.innerHTML = "<span class=\"muted\">No discarded terms yet.</span>";
    return;
  }
  function escapeAttr(s) {
    return (s || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  const reinstateIcon = `<svg class="reinstate-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg"><path d="M3 10h10a5 5 0 0 1 5 5v0"/><path d="M3 10l4-4M3 10l4 4"/></svg>`;
  panel.innerHTML = words.map(w => `
    <div class="allowlist-item" data-word="${escapeAttr(w)}">
      <span class="word">${escapeHtml(w)}</span>
      <button type="button" class="reinstate-btn" title="Reinstate" aria-label="Reinstate">${reinstateIcon}</button>
    </div>
  `).join("");
  panel.querySelectorAll(".allowlist-item .reinstate-btn").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const item = btn.closest(".allowlist-item");
      const word = item?.getAttribute("data-word");
      if (!word) return;
      try {
        await api("/api/allowlist", { method: "DELETE", body: JSON.stringify({ words: [word] }), headers: { "Content-Type": "application/json" } });
        refreshAllowlistPanel();
        await refreshDocs();
        if (activeDocId) {
          const maxWait = 300000;
          const interval = 1500;
          const start = Date.now();
          while (Date.now() - start < maxWait) {
            await new Promise(r => setTimeout(r, interval));
            const infoRes = await api(`/api/docs/${activeDocId}`);
            const info = await infoRes.json();
            if (info.doc.status === "done") {
              const res = await api(`/api/docs/${activeDocId}/result`);
              activeResult = await res.json();
              totalPages = activeResult.pages || 0;
              typoMeta.textContent = `${activeResult.typo_count} typos · ${activeResult.pages} pages · ${activeResult.runtime_sec}s`;
              renderTypoList();
              setPdfView(true);
              await refreshDocs();
              return;
            }
            if (info.doc.status === "failed") {
              await refreshDocs();
              return;
            }
          }
          await refreshDocs();
        }
      } catch (err) {
        alert(err.message || "Reinstate failed");
      }
    });
  });
}

function renderDocs() {
  let html = "";
  for (const d of docs) {
    const label = (d.name || d.filename || "Untitled").slice(0, 32);
    let statusLabel = d.status === "processing" && d.message
      ? statusPill(d.status) + " <span class=\"dash-status-msg\">" + escapeHtml(d.message) + "</span>"
      : statusPill(d.status);
    if (d.status === "queued" || d.status === "processing") {
      const pct = typeof d.progress === "number" ? d.progress : 0;
      statusLabel += " <span class=\"dash-status-msg\">" + pct + "%</span>";
    }
    let resultCell;
    if (d.status === "done" && typeof d.typo_count === "number") {
      resultCell = escapeHtml(String(d.typo_count) + " typos");
    } else if (d.status === "queued" || d.status === "processing") {
      resultCell = `<span class="dash-result-actions"><button type="button" class="dash-result-btn dash-pause-btn" title="Pause processing" data-doc="${escapeAttr(d.doc_id)}" aria-label="Pause">⏸</button><button type="button" class="dash-result-btn dash-cancel-btn" title="Cancel and remove document" data-doc="${escapeAttr(d.doc_id)}" aria-label="Cancel">✕</button></span>`;
    } else if (d.status === "paused") {
      resultCell = `<span class="dash-result-actions"><button type="button" class="dash-result-btn dash-play-btn" title="Resume processing" data-doc="${escapeAttr(d.doc_id)}" aria-label="Resume">▶</button><button type="button" class="dash-result-btn dash-cancel-btn" title="Cancel and remove document" data-doc="${escapeAttr(d.doc_id)}" aria-label="Cancel">✕</button></span>`;
    } else {
      resultCell = "—";
    }
    html += `<tr data-doc="${escapeAttr(d.doc_id)}">
      <td title="${escapeHtml(d.filename)}">${escapeHtml(label)}</td>
      <td>${statusLabel}</td>
      <td data-col="result">${resultCell}</td>
    </tr>`;
  }
  docTable.innerHTML = html || "<tr><td colspan='3' class='muted'>No documents</td></tr>";

  docTable.querySelectorAll("tr[data-doc]").forEach(tr => {
    tr.addEventListener("click", (e) => {
      if (e.target.closest(".dash-result-btn")) return;
      const id = tr.getAttribute("data-doc");
      if (id) location.href = "/doc/" + id;
    });
    const pauseBtn = tr.querySelector(".dash-pause-btn");
    const playBtn = tr.querySelector(".dash-play-btn");
    pauseBtn?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const id = tr.getAttribute("data-doc");
      if (!id) return;
      pauseBtn.disabled = true;
      api(`/api/docs/${id}/pause`, { method: "POST" }).then(() => loadDocs()).catch(err => { pauseBtn.disabled = false; alert(err.message || "Pause failed"); });
    });
    playBtn?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const id = tr.getAttribute("data-doc");
      if (!id) return;
      playBtn.disabled = true;
      api(`/api/docs/${id}/resume`, { method: "POST" }).then(() => loadDocs()).catch(err => { playBtn.disabled = false; alert(err.message || "Resume failed"); });
    });
    const cancelBtn = tr.querySelector(".dash-cancel-btn");
    cancelBtn?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const id = tr.getAttribute("data-doc");
      if (!id) return;
      if (!confirm("Cancel and remove this document? Processing will stop and the document will be deleted. This cannot be undone.")) return;
      cancelBtn.disabled = true;
      api(`/api/docs/${id}/cancel`, { method: "POST" }).then(() => { loadDocs(); if (typeof activeDocId !== "undefined" && activeDocId === id) location.href = "/dashboard"; }).catch(err => { cancelBtn.disabled = false; alert(err.message || "Cancel failed"); });
    });
  });
}

function renderDocSelect() {
  if (!docSelect) return;
  docSelect.innerHTML = `<option value="">Select a document…</option>` + docs.map(d =>
    `<option value="${escapeAttr(d.doc_id)}">${escapeHtml((d.name || d.filename || "").slice(0, 40))} (${escapeHtml(d.status)})</option>`
  ).join("");
  if (activeDocId) docSelect.value = activeDocId;
}

function viewPdfUrl(highlight) {
  // Use original PDF when annotated is not ready so the document is still visible
  if (!hasAnnotatedPdf) {
    return `/api/docs/${activeDocId}/pdf`;
  }
  const base = `/api/docs/${activeDocId}/annotated.pdf`;
  if (highlight && highlight.page && Array.isArray(highlight.bbox_pts) && highlight.bbox_pts.length >= 4) {
    const [hl_left, hl_bottom, hl_right, hl_top] = highlight.bbox_pts.map(Number);
    const q = new URLSearchParams({
      page: String(highlight.page),
      hl_left: String(hl_left),
      hl_bottom: String(hl_bottom),
      hl_right: String(hl_right),
      hl_top: String(hl_top),
    });
    return base + "?" + q.toString();
  }
  return base;
}
function downloadPdfUrl() {
  if (!hasAnnotatedPdf) {
    return `/api/docs/${activeDocId}/pdf`;
  }
  return `/api/docs/${activeDocId}/annotated.pdf?download=true`;
}

function setPdfView(forceReload, opts) {
  // When navigating to a typo (opts with bbox_pts + pageNum), request annotated PDF with highlight overlay and re-load iframe
  const highlight = opts && opts.bbox_pts && opts.pageNum ? { page: opts.pageNum, bbox_pts: opts.bbox_pts } : null;
  const url = viewPdfUrl(highlight);
  let hash = "";
  if (totalPages > 0) {
    hash = `page=${pageNum}`;
    if (opts && opts.zoom) {
      const zoomVal = Math.round(opts.zoom);
      if (opts.bbox_pts && Array.isArray(opts.bbox_pts) && opts.bbox_pts.length >= 4 && opts.pageNum && activeResult && activeResult.page_dimensions) {
        const dims = activeResult.page_dimensions[String(opts.pageNum)];
        const h = dims && dims.height_pts;
        if (typeof h === "number") {
          const [left_pts, bottom_pts, right_pts, top_pts] = opts.bbox_pts.map(Number);
          const viewLeft = left_pts;
          const viewTop = h - top_pts;
          hash += `&zoom=${zoomVal},${Math.round(viewLeft)},${Math.round(viewTop)}`;
        } else {
          hash += `&zoom=${zoomVal}`;
        }
      } else if (opts.bbox && Array.isArray(opts.bbox) && opts.bbox.length >= 4) {
        const [x0, y0] = opts.bbox.map(Number);
        hash += `&zoom=${zoomVal},${Math.round(x0)},${Math.round(y0)}`;
      } else {
        hash += `&zoom=${zoomVal}`;
      }
    }
  }
  const pageOnlyHash = totalPages > 0 ? `page=${pageNum}` : "";
  const withPage = pageOnlyHash ? `${url.split("?")[0]}#${pageOnlyHash}` : url.split("?")[0];
  if (hash && opts && opts.zoom) {
    hash += `&nav=${Date.now()}`;
  }
  const iframeFragment = hash;
  const iframeUrl = iframeFragment ? `${url}#${iframeFragment}` : url;
  // Force reload when we have a highlight so the iframe fetches the PDF with the red box overlay
  // But don't reload if we're just opening the review panel (no highlight change)
  const doReload = forceReload || (highlight && (!pdfIframe.src || !pdfIframe.src.includes(url.split("?")[0])));
  if (doReload || !pdfIframe.src) {
    pdfIframe.src = `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}${iframeFragment ? "#" + iframeFragment : ""}`;
  } else if (iframeFragment && pdfIframe.src) {
    // Just update the hash without reloading if iframe is already loaded
    try {
      if (pdfIframe.contentWindow && pdfIframe.contentWindow.location) {
        pdfIframe.contentWindow.location.hash = iframeFragment;
      }
    } catch (e) {
      // Cross-origin or other error, fall back to reload only if needed
      if (forceReload || highlight) {
        pdfIframe.src = iframeUrl;
      }
    }
  }
  openInNewTab.href = withPage;
  openInNewTab.style.display = "inline-block";
  pageLabel.textContent = totalPages > 0 ? `Page ${pageNum} / ${totalPages}` : "—";
}

function getTypoReviewStatus(t) {
  return (t && t.review && t.review.status) ? t.review.status : "pending";
}

function updateReviewPanel(typo) {
  if (!typo) {
    if (reviewPanelEmpty) reviewPanelEmpty.style.display = "";
    if (reviewPanelContent) reviewPanelContent.style.display = "none";
    selectedTypoForReview = null;
    if (reviewPrevBtn) reviewPrevBtn.style.display = "none";
    if (reviewNextBtn) reviewNextBtn.style.display = "none";
    if (reviewNavLabel) reviewNavLabel.textContent = "";
    if (reviewCloseBtn) reviewCloseBtn.style.display = "none";
    if (reviewPrevWordBtn) reviewPrevWordBtn.style.display = "none";
    if (reviewNextWordBtn) reviewNextWordBtn.style.display = "none";
    if (reviewApproveAllBtn) reviewApproveAllBtn.style.display = "none";
    if (reviewFlagAllBtn) reviewFlagAllBtn.style.display = "none";
    return;
  }
  const typos = (activeResult && activeResult.typos) || [];
  const idx = typos.indexOf(typo);
  selectedTypoForReview = { typo, idx };
  if (reviewPanelEmpty) reviewPanelEmpty.style.display = "none";
  if (reviewPanelContent) reviewPanelContent.style.display = "block";
  if (reviewWord) reviewWord.textContent = typo.word || "";
  const status = getTypoReviewStatus(typo);
  if (reviewStatusBadge) {
    reviewStatusBadge.textContent = status.charAt(0).toUpperCase() + status.slice(1);
    reviewStatusBadge.className = "review-status-badge " + status;
  }
  if (reviewDescription) reviewDescription.value = (typo.review && typo.review.description) || "";
  // Next/prev navigation
  if (reviewPrevBtn) {
    reviewPrevBtn.style.display = "inline-block";
    reviewPrevBtn.disabled = idx <= 0;
  }
  if (reviewNextBtn) {
    reviewNextBtn.style.display = "inline-block";
    reviewNextBtn.disabled = idx < 0 || idx >= typos.length - 1;
  }
  if (reviewNavLabel) reviewNavLabel.textContent = typos.length ? `${idx + 1} / ${typos.length}` : "";
  if (reviewInstanceLabel) reviewInstanceLabel.textContent = (typo.context || "").trim().slice(0, 60) || "";
  const wordOrder = [];
  const seenWords = new Set();
  for (const t of typos) {
    const w = t.word || "";
    if (!seenWords.has(w)) { seenWords.add(w); wordOrder.push(w); }
  }
  const currentWord = typo.word || "";
  const wordIndex = wordOrder.indexOf(currentWord);
  if (reviewCloseBtn) reviewCloseBtn.style.display = "inline-block";
  if (reviewPrevWordBtn) {
    reviewPrevWordBtn.style.display = "inline-block";
    reviewPrevWordBtn.disabled = wordIndex <= 0 || wordOrder.length <= 1;
  }
  if (reviewNextWordBtn) {
    reviewNextWordBtn.style.display = "inline-block";
    reviewNextWordBtn.disabled = wordIndex < 0 || wordIndex >= wordOrder.length - 1;
  }
  const sameWordCount = typos.filter((t) => (t.word || "") === (typo.word || "")).length;
  if (reviewApproveAllBtn) {
    reviewApproveAllBtn.style.display = sameWordCount > 1 ? "inline-block" : "none";
  }
  if (reviewFlagAllBtn) {
    reviewFlagAllBtn.style.display = sameWordCount > 1 ? "inline-block" : "none";
  }
  // Ensure iframe stays visible when review panel opens
  if (pdfIframe && pdfIframe.src) {
    pdfIframe.style.display = "block";
    pdfIframe.style.visibility = "visible";
  }
}

function clearReviewPanel() {
  updateReviewPanel(null);
}

async function submitTypoReview(status, description) {
  if (!activeDocId || !selectedTypoForReview) return;
  const t = selectedTypoForReview.typo;
  try {
    await api(`/api/docs/${activeDocId}/typos/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        page: t.page,
        word: t.word || "",
        bbox_pts: t.bbox_pts || [],
        status,
        description: description || null,
      }),
    });
    const res = await api(`/api/docs/${activeDocId}/result`);
    activeResult = await res.json();
    const found = activeResult.typos.find(
      (x) => x.page === t.page && (x.word || "") === (t.word || "") && JSON.stringify(x.bbox_pts || []) === JSON.stringify(t.bbox_pts || [])
    );
    if (found) updateReviewPanel(found);
    else clearReviewPanel();
    renderTypoList();
    // Force PDF to reload so rejected typo's red box disappears (avoid cached iframe content)
    if (pdfIframe && pdfIframe.src) {
      pdfIframe.src = "";
    }
    setPdfView(true);
  } catch (err) {
    alert(err.message || "Review update failed");
  }
}

function navigateReviewPanel(direction) {
  if (!selectedTypoForReview || !activeResult) return;
  const typos = activeResult.typos;
  const nextIdx = selectedTypoForReview.idx + direction;
  if (nextIdx < 0 || nextIdx >= typos.length) return;
  const t = typos[nextIdx];
  selectedTypoForReview = { typo: t, idx: nextIdx };
  updateReviewPanel(t);
  pageNum = t.page;
  setPdfView(false, { zoom: 200, bbox_pts: t.bbox_pts, bbox: t.bbox, pageNum: t.page });
  renderTypoList();
}

function navigateReviewPanelByWord(direction) {
  if (!selectedTypoForReview || !activeResult) return;
  const typos = activeResult.typos;
  const wordOrder = [];
  const seenWords = new Set();
  for (const t of typos) {
    const w = t.word || "";
    if (!seenWords.has(w)) { seenWords.add(w); wordOrder.push(w); }
  }
  const currentWord = selectedTypoForReview.typo.word || "";
  const wordIndex = wordOrder.indexOf(currentWord);
  const nextWordIndex = wordIndex + direction;
  if (nextWordIndex < 0 || nextWordIndex >= wordOrder.length) return;
  const nextWord = wordOrder[nextWordIndex];
  const firstIdx = typos.findIndex((t) => (t.word || "") === nextWord);
  if (firstIdx < 0) return;
  const t = typos[firstIdx];
  selectedTypoForReview = { typo: t, idx: firstIdx };
  updateReviewPanel(t);
  pageNum = t.page;
  setPdfView(false, { zoom: 200, bbox_pts: t.bbox_pts, bbox: t.bbox, pageNum: t.page });
  renderTypoList();
}

async function submitTypoReviewAll(status, description) {
  if (!activeDocId || !selectedTypoForReview) return;
  const word = (selectedTypoForReview.typo.word || "").trim();
  const typos = (activeResult && activeResult.typos) || [];
  const toUpdate = typos.filter((t) => (t.word || "").trim() === word);
  if (!toUpdate.length) return;
  try {
    await api(`/api/docs/${activeDocId}/typos/review_batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        typos: toUpdate.map((t) => ({ page: t.page, word: t.word || "", bbox_pts: t.bbox_pts || [] })),
        status,
        description: description || null,
      }),
    });
    const res = await api(`/api/docs/${activeDocId}/result`);
    activeResult = await res.json();
    const sameWord = activeResult.typos.filter((t) => (t.word || "").trim() === word);
    if (sameWord.length) {
      const first = sameWord[0];
      const idx = activeResult.typos.indexOf(first);
      updateReviewPanel(first);
      selectedTypoForReview = { typo: first, idx };
    } else {
      clearReviewPanel();
    }
    renderTypoList();
    if (pdfIframe && pdfIframe.src) pdfIframe.src = "";
    setPdfView(true);
  } catch (err) {
    alert(err.message || "Review update failed");
  }
}

async function selectDoc(docId) {
  const isNewDoc = docId !== activeDocId;
  activeDocId = docId;
  hasAnnotatedPdf = false;
  selectedAllowlistWords.clear();
  clearReviewPanel();
  typoList.innerHTML = "";
  typoMeta.textContent = "Loading…";
  downloadLink.style.display = "none";
  if (reprocessDocBtn) reprocessDocBtn.style.display = "none";
  if (regeneratePdfBtn) regeneratePdfBtn.style.display = "none";
  if (openInNewTab) openInNewTab.style.display = "none";
  if (isNewDoc) {
    pdfIframe.style.display = "none";
    pdfIframe.src = "";
    viewerPlaceholder.style.display = "flex";
  }
  activeResult = null;
  pageNum = 1;
  totalPages = 0;

  try {
    const infoRes = await api(`/api/docs/${docId}`);
    const info = await infoRes.json();
    if (info.doc.status !== "done") {
      typoMeta.textContent = `Status: ${info.doc.status} (${info.doc.progress}%)`;
      viewerPlaceholder.textContent = "Document not ready — complete processing first.";
      return;
    }

    hasAnnotatedPdf = !!info.has_annotated;
    const res = await api(`/api/docs/${docId}/result`);
    activeResult = await res.json();
    totalPages = activeResult.pages || 0;
    showNonTyposList = false;
    if (typoListToggleTypos) {
      typoListToggleTypos.classList.add("is-active");
      typoListToggleTypos.setAttribute("aria-pressed", "true");
    }
    if (typoListToggleNonTypos) {
      typoListToggleNonTypos.classList.remove("is-active");
      typoListToggleNonTypos.setAttribute("aria-pressed", "false");
    }
    typoMeta.textContent = `${activeResult.typo_count} typos · ${activeResult.pages} pages · ${activeResult.runtime_sec}s`;

    downloadLink.href = downloadPdfUrl();
    downloadLink.textContent = hasAnnotatedPdf ? "Download annotated PDF" : "Download PDF";
    downloadLink.style.display = "inline-block";
    const isOwner = currentUserId && info.doc && info.doc.owner_id === currentUserId;
    if (reprocessDocBtn) reprocessDocBtn.style.display = isOwner ? "inline-block" : "none";
    if (regeneratePdfBtn) regeneratePdfBtn.style.display = hasAnnotatedPdf ? "inline-block" : "none";
    if (openInNewTab) openInNewTab.style.display = "inline-block";

    viewerPlaceholder.style.display = "none";
    pdfIframe.style.display = "block";
    pdfIframe.style.visibility = "visible";
    setPdfView(true);

    renderTypoList();
  } catch (_) {
    typoMeta.textContent = "Failed to load document.";
  }
}

function showDocProcessingState(progressPct) {
  activeResult = null;
  totalPages = 0;
  if (typoMeta) typoMeta.textContent = typeof progressPct === "number" ? `Processing… ${progressPct}%` : "Processing…";
  if (typoList) typoList.innerHTML = `<div class="typo-meta">Processing… typo list will update when complete.</div>`;
  if (viewerPlaceholder) {
    viewerPlaceholder.textContent = "Document is re-processing — viewer will update when complete.";
    viewerPlaceholder.style.display = "flex";
  }
  if (pdfIframe) {
    pdfIframe.style.display = "none";
    pdfIframe.src = "";
  }
  if (downloadLink) downloadLink.style.display = "none";
  if (reprocessDocBtn) reprocessDocBtn.style.display = "none";
  if (regeneratePdfBtn) regeneratePdfBtn.style.display = "none";
  if (openInNewTab) openInNewTab.style.display = "none";
  if (pageLabel) pageLabel.textContent = "—";
  if (addAllToAllowlistBtn) addAllToAllowlistBtn.style.display = "none";
}

async function addToAllowlistAndRecheck(words) {
  if (!words.length) return;
  try {
    const res = await api("/api/allowlist?prepend=1", { method: "POST", body: JSON.stringify({ words }), headers: { "Content-Type": "application/json" } });
    const data = await res.json();
    refreshAllowlistPanel();
    const queued = data.queued || 0;
    typoMeta.textContent = queued ? `Rechecking ${queued} document(s) with those typos…` : "Allowlist updated.";
    if (queued && activeDocId) showDocProcessingState();
    if (!activeDocId) return;
    const maxWait = 300000; // 5 min
    const interval = 1500;
    const start = Date.now();
    while (Date.now() - start < maxWait) {
      await new Promise(r => setTimeout(r, interval));
      await refreshDocs();
      const infoRes = await api(`/api/docs/${activeDocId}`);
      const info = await infoRes.json();
      if (info.doc.status === "done") {
        refreshAllowlistPanel();
        const res = await api(`/api/docs/${activeDocId}/result`);
        activeResult = await res.json();
        totalPages = activeResult.pages || 0;
        typoMeta.textContent = `${activeResult.typo_count} typos · ${activeResult.pages} pages · ${activeResult.runtime_sec}s`;
        selectedAllowlistWords.clear();
        renderTypoList();
        viewerPlaceholder.style.display = "none";
        pdfIframe.style.display = "block";
        pdfIframe.style.visibility = "visible";
        downloadLink.href = downloadPdfUrl();
        downloadLink.style.display = "inline-block";
        if (reprocessDocBtn) reprocessDocBtn.style.display = "inline-block";
        if (regeneratePdfBtn) regeneratePdfBtn.style.display = "inline-block";
        openInNewTab.style.display = "inline-block";
        setPdfView(true);
        return;
      }
      if (info.doc.status === "failed") {
        typoMeta.textContent = "Recheck failed.";
        return;
      }
      showDocProcessingState(typeof info.doc.progress === "number" ? info.doc.progress : undefined);
    }
    typoMeta.textContent = "Recheck timed out.";
  } catch (err) {
    typoMeta.textContent = "Error: " + (err.message || "failed");
  }
}

function updateTypoSelectionUi() {
  if (!typoList) return;
  const hasSelection = selectedAllowlistWords.size > 0;
  typoList.classList.toggle("has-selection", hasSelection);
  if (addAllToAllowlistBtn) {
    addAllToAllowlistBtn.disabled = !hasSelection && !typoList.querySelector(".typo-item");
    addAllToAllowlistBtn.textContent = hasSelection ? "Add selected to allowlist" : "Add all to allowlist";
  }
  if (typoSelectAll) {
    const wordsInView = new Set(
      Array.from(typoList.querySelectorAll(".typo-item[data-word]")).map(el => el.getAttribute("data-word") || "")
    );
    if (!wordsInView.size) {
      typoSelectAll.checked = false;
      typoSelectAll.indeterminate = false;
      return;
    }
    let selectedCount = 0;
    wordsInView.forEach(w => {
      if (selectedAllowlistWords.has(w)) selectedCount++;
    });
    if (selectedCount === 0) {
      typoSelectAll.checked = false;
      typoSelectAll.indeterminate = false;
    } else if (selectedCount === wordsInView.size) {
      typoSelectAll.checked = true;
      typoSelectAll.indeterminate = false;
    } else {
      typoSelectAll.checked = false;
      typoSelectAll.indeterminate = true;
    }
  }
}

function renderTypoList() {
  if (typoSelectControls) typoSelectControls.style.display = showNonTyposList ? "none" : "flex";
  if (typoPanelTitle) typoPanelTitle.textContent = showNonTyposList ? "Non-typos" : "Typos";

  if (showNonTyposList) {
    const nonTypos = (activeResult && activeResult.non_typos) ? activeResult.non_typos : [];
    if (typoMeta && activeResult) {
      typoMeta.textContent = nonTypos.length
        ? `${nonTypos.length} non-typos (words not flagged) · ${activeResult.pages || 0} pages`
        : `No non-typos list. Reprocess document to see words that were checked but not flagged.`;
    }
    if (!typoList) return;
    if (!nonTypos.length) {
      typoList.innerHTML = `<div class="typo-meta">Reprocess this document to see words that were checked but not flagged as typos.</div>`;
      return;
    }
    const limited = nonTypos.slice(0, 800);
    const groups = [];
    const byWord = new Map();
    limited.forEach((n, idx) => {
      const key = n.word || "";
      let g = byWord.get(key);
      if (!g) {
        g = { word: key, items: [] };
        byWord.set(key, g);
        groups.push(g);
      }
      g.items.push({ n, idx });
    });
    groups.sort((a, b) => (a.word || "").localeCompare(b.word || "", undefined, { sensitivity: "base" }));
    typoList.innerHTML = groups.map((g) => {
      const occurrencesHtml = g.items.map(({ n }) => `
        <div class="typo-occurrence typo-occurrence-nontypo" data-idx="${n.page}" data-page="${n.page}" data-bbox-pts="${escapeAttr(JSON.stringify(n.bbox_pts || []))}">
          <div class="typo-occurrence-main">
            <span class="page">p.${n.page}</span>
            <span class="context">${escapeHtml((n.context || "").slice(0, 90))}</span>
          </div>
        </div>
      `).join("");
      const countLabel = g.items.length > 1 ? ` (${g.items.length})` : "";
      const occurrencesData = escapeAttr(JSON.stringify(g.items.map(({ n }) => ({ page: n.page, word: n.word || "", bbox_pts: n.bbox_pts || [], context: n.context || "" }))));
      return `
        <div class="typo-item typo-item-nontypo" data-word="${escapeAttr(g.word)}" data-occurrences="${occurrencesData}">
          <div class="typo-item-main">
            <div class="typo-main-header typo-nontypo-header" role="button" tabindex="0" aria-expanded="false" title="Click to expand/collapse">
              <div class="typo-word-wrap">
                <span class="word">${escapeHtml(g.word)}</span>
                <span class="typo-count">${countLabel}</span>
              </div>
              <span class="typo-collapse-icon" aria-hidden="true">›</span>
              <button type="button" class="typo-nontypo-add-btn" aria-label="Add all occurrences to typos and PDF" title="Add all occurrences to typos and PDF">×</button>
            </div>
            <div class="typo-occurrence-list">
              ${occurrencesHtml}
            </div>
          </div>
        </div>
      `;
    }).join("");
    typoList.querySelectorAll(".typo-item-nontypo").forEach((item) => {
      const header = item.querySelector(".typo-nontypo-header");
      if (header) {
        const toggle = () => {
          const expanded = item.classList.toggle("is-expanded");
          header.setAttribute("aria-expanded", String(expanded));
        };
        header.addEventListener("click", (e) => {
          e.stopPropagation();
          toggle();
        });
        header.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            e.stopPropagation();
            toggle();
          }
        });
      }
    });
    typoList.querySelectorAll(".typo-occurrence-nontypo").forEach(occ => {
      occ.addEventListener("click", (e) => {
        e.stopPropagation();
        const page = parseInt(occ.getAttribute("data-page"), 10);
        let bboxPts = [];
        try {
          bboxPts = JSON.parse(occ.getAttribute("data-bbox-pts") || "[]");
        } catch (_) {}
        if (page && bboxPts.length >= 4) {
          pageNum = page;
          setPdfView(false, { zoom: 200, bbox_pts: bboxPts, pageNum: page });
        }
      });
    });
    typoList.querySelectorAll(".typo-nontypo-add-btn").forEach(btn => {
      btn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const item = btn.closest(".typo-item-nontypo");
        if (!item || !activeDocId) return;
        let occurrences = [];
        try {
          occurrences = JSON.parse(item.getAttribute("data-occurrences") || "[]");
        } catch (_) {}
        if (!occurrences.length) return;
        try {
          await api(`/api/docs/${activeDocId}/typos/add_from_non_typos`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ occurrences }),
          });
          const res = await api(`/api/docs/${activeDocId}/result`);
          activeResult = await res.json();
          showNonTyposList = false;
          if (typoListToggleTypos) typoListToggleTypos.classList.add("is-active");
          if (typoListToggleNonTypos) typoListToggleNonTypos.classList.remove("is-active");
          renderTypoList();
          if (pdfIframe && pdfIframe.src) pdfIframe.src = "";
          setPdfView(true);
        } catch (err) {
          alert(err.message || "Failed to add to typos");
        }
      });
    });
    return;
  }

  const typos = (activeResult && activeResult.typos) ? activeResult.typos : [];
  const visibleTypos = typos;
  if (addAllToAllowlistBtn) addAllToAllowlistBtn.style.display = visibleTypos.length ? "inline-block" : "none";
  if (typoMeta && activeResult) {
    typoMeta.textContent = `${activeResult.typo_count} typos · ${activeResult.pages || 0} pages · ${activeResult.runtime_sec}s`;
  }
  if (!typoList) return;
  if (!visibleTypos.length) {
    typoList.innerHTML = `<div class="typo-meta">No typos found (or no text layer).</div>`;
    return;
  }
  const limited = visibleTypos.slice(0, 800);
  const groups = [];
  const byWord = new Map();
  limited.forEach((t) => {
    const key = t.word || "";
    const origIdx = activeResult.typos.indexOf(t);
    let g = byWord.get(key);
    if (!g) {
      g = { word: key, items: [] };
      byWord.set(key, g);
      groups.push(g);
    }
    g.items.push({ t, idx: origIdx });
  });

  const wordSort = (a, b) => (a.word || "").localeCompare(b.word || "", undefined, { sensitivity: "base" });
  const pendingGroups = [];
  const approvedGroups = [];
  const rejectedGroups = [];
  groups.forEach((g) => {
    const statuses = g.items.map(({ t }) => getTypoReviewStatus(t));
    const wordStatus = statuses.some((s) => s === "flagged") ? "flagged" : statuses.every((s) => s === "approved") ? "approved" : "pending";
    if (wordStatus === "pending") pendingGroups.push(g);
    else if (wordStatus === "approved") approvedGroups.push(g);
    else rejectedGroups.push(g);
  });
  pendingGroups.sort(wordSort);
  approvedGroups.sort(wordSort);
  rejectedGroups.sort(wordSort);

  function renderTypoGroup(g) {
    const isSelected = selectedAllowlistWords.has(g.word);
    const statuses = g.items.map(({ t }) => getTypoReviewStatus(t));
    const wordStatus = statuses.some((s) => s === "flagged") ? "flagged" : statuses.every((s) => s === "approved") ? "approved" : "pending";
    const statusLabel = wordStatus === "approved" ? "Accepted" : wordStatus === "flagged" ? "Rejected" : "Pending";
    const statusClass = wordStatus === "approved" ? "approved" : wordStatus === "flagged" ? "flagged" : "pending";
    const occurrencesHtml = g.items.map(({ t, idx }) => `
      <div class="typo-occurrence" data-idx="${idx}">
        <div class="typo-occurrence-main">
          <span class="page">p.${t.page}</span>
          <span class="context">${escapeHtml((t.context || "").slice(0, 90))}</span>
        </div>
      </div>
    `).join("");
    const countLabel = g.items.length > 1 ? `(${g.items.length})` : "";
    return `
      <div class="typo-item${isSelected ? " selected" : ""}" data-word="${escapeAttr(g.word)}">
        <div class="typo-item-main">
          <div class="typo-main-header">
            <div class="typo-word-wrap">
              <span class="word">${escapeHtml(g.word)}</span>
              ${countLabel ? `<span class="typo-count">${countLabel}</span>` : ""}
              <span class="typo-review-status-badge typo-review-status-${statusClass}">${statusLabel}</span>
            </div>
            <label class="typo-check-wrap">
              <input type="checkbox" class="typo-parent-checkbox" data-word="${escapeAttr(g.word)}" ${isSelected ? "checked" : ""} aria-label="Select all occurrences of '${escapeAttr(g.word)}' for allowlist" />
            </label>
          </div>
          <div class="typo-occurrence-list">
            ${occurrencesHtml}
          </div>
        </div>
      </div>
    `;
  }

  const sections = [];
  if (pendingGroups.length) {
    sections.push(`<div class="typo-list-section"><div class="typo-list-section-title">Pending</div>${pendingGroups.map(renderTypoGroup).join("")}</div>`);
  }
  if (approvedGroups.length) {
    sections.push(`<div class="typo-list-section"><div class="typo-list-section-title">Approved</div>${approvedGroups.map(renderTypoGroup).join("")}</div>`);
  }
  if (rejectedGroups.length) {
    sections.push(`<div class="typo-list-section"><div class="typo-list-section-title">Rejected</div>${rejectedGroups.map(renderTypoGroup).join("")}</div>`);
  }
  typoList.innerHTML = sections.join("");

  // Wire up parent checkboxes and occurrence navigation.
  typoList.querySelectorAll(".typo-item").forEach(row => {
    const parentCheckbox = row.querySelector(".typo-parent-checkbox");
    const occurrences = Array.from(row.querySelectorAll(".typo-occurrence"));

    if (parentCheckbox) {
      parentCheckbox.addEventListener("click", (e) => {
        e.stopPropagation();
      });
      parentCheckbox.addEventListener("change", (e) => {
        e.stopPropagation();
        const checked = parentCheckbox.checked;
        const word = parentCheckbox.getAttribute("data-word") || "";
        if (checked) {
          selectedAllowlistWords.add(word);
        } else {
          selectedAllowlistWords.delete(word);
        }
        updateTypoSelectionUi();
      });
    }

    // Clicking occurrence row navigates PDF and opens review panel.
    row.querySelectorAll(".typo-occurrence").forEach(occ => {
      occ.addEventListener("click", (e) => {
        e.stopPropagation();
        const idx = parseInt(occ.getAttribute("data-idx"), 10);
        const t = activeResult.typos[idx];
        if (!t) return;
        pageNum = t.page;
        updateReviewPanel(t);
        // Don't force reload when opening review panel - just update view
        setPdfView(false, {
          zoom: 200,
          bbox_pts: t.bbox_pts,
          bbox: t.bbox,
          pageNum: t.page,
        });
      });
    });
  });
  updateTypoSelectionUi();
}

if (addAllToAllowlistBtn) {
  addAllToAllowlistBtn.addEventListener("click", () => {
    const typos = (activeResult && activeResult.typos) ? activeResult.typos : [];
    let words = [];
    if (selectedAllowlistWords.size) {
      words = Array.from(selectedAllowlistWords);
    } else {
      words = [...new Set(typos.map(t => t.word).filter(Boolean))];
    }
    if (words.length) addToAllowlistAndRecheck(words);
  });
}

if (typoListToggleTypos) {
  typoListToggleTypos.addEventListener("click", () => {
    if (showNonTyposList) {
      showNonTyposList = false;
      typoListToggleTypos.classList.add("is-active");
      typoListToggleTypos.setAttribute("aria-pressed", "true");
      if (typoListToggleNonTypos) {
        typoListToggleNonTypos.classList.remove("is-active");
        typoListToggleNonTypos.setAttribute("aria-pressed", "false");
      }
      renderTypoList();
    }
  });
}
if (typoListToggleNonTypos) {
  typoListToggleNonTypos.addEventListener("click", () => {
    if (!showNonTyposList) {
      showNonTyposList = true;
      typoListToggleNonTypos.classList.add("is-active");
      typoListToggleNonTypos.setAttribute("aria-pressed", "true");
      if (typoListToggleTypos) {
        typoListToggleTypos.classList.remove("is-active");
        typoListToggleTypos.setAttribute("aria-pressed", "false");
      }
      clearReviewPanel();
      renderTypoList();
    }
  });
}

if (typoSelectAll) {
  typoSelectAll.addEventListener("change", () => {
    const typos = (activeResult && activeResult.typos) ? activeResult.typos : [];
    if (!typos.length) {
      typoSelectAll.checked = false;
      typoSelectAll.indeterminate = false;
      return;
    }
    if (typoSelectAll.checked) {
      selectedAllowlistWords = new Set(typos.map(t => t.word).filter(Boolean));
    } else {
      selectedAllowlistWords.clear();
    }
    renderTypoList();
  });
}

prevPageBtn.addEventListener("click", () => {
  if (!activeResult || totalPages === 0) return;
  pageNum = Math.max(1, pageNum - 1);
  setPdfView();
});
nextPageBtn.addEventListener("click", () => {
  if (!activeResult || totalPages === 0) return;
  pageNum = Math.min(totalPages, pageNum + 1);
  setPdfView();
});

if (docSelect) {
  docSelect.addEventListener("change", () => {
    if (ignoreDocSelectChange) return;
    const id = docSelect.value;
    if (!id) return;
    selectDoc(id);
  });
}

refreshBtn.addEventListener("click", () => refreshDocs());

if (regeneratePdfBtn) {
  regeneratePdfBtn.addEventListener("click", async () => {
    if (!activeDocId || !hasAnnotatedPdf) return;
    const prevText = regeneratePdfBtn.textContent;
    try {
      regeneratePdfBtn.disabled = true;
      regeneratePdfBtn.textContent = "Updating…";
      await api(`/api/docs/${activeDocId}/regenerate-annotated`, { method: "POST" });
      if (pdfIframe && pdfIframe.src) pdfIframe.src = "";
      setPdfView(true);
    } catch (err) {
      alert(err.message || "Update failed");
    } finally {
      regeneratePdfBtn.disabled = false;
      regeneratePdfBtn.textContent = prevText;
    }
  });
}

if (reprocessDocBtn) {
  reprocessDocBtn.addEventListener("click", async () => {
    if (!activeDocId) return;
    if (!confirm("Reprocess this document and reset all reviews? This will re-run typo detection on the full document.")) return;
    const prevText = reprocessDocBtn.textContent;
    try {
      reprocessDocBtn.disabled = true;
      reprocessDocBtn.textContent = "Reprocessing…";
      await api(`/api/docs/${activeDocId}/reprocess`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reset_reviews: true })
      });
      showDocProcessingState();
      const maxWait = 300000;
      const interval = 1500;
      const start = Date.now();
      while (Date.now() - start < maxWait) {
        await new Promise(r => setTimeout(r, interval));
        await refreshDocs();
        const infoRes = await api(`/api/docs/${activeDocId}`);
        const info = await infoRes.json();
        if (info.doc.status === "done") {
          hasAnnotatedPdf = !!info.has_annotated;
          const res = await api(`/api/docs/${activeDocId}/result`);
          activeResult = await res.json();
          totalPages = activeResult.pages || 0;
          typoMeta.textContent = `${activeResult.typo_count} typos · ${activeResult.pages} pages · ${activeResult.runtime_sec}s`;
          selectedAllowlistWords.clear();
          renderTypoList();
          if (viewerPlaceholder) viewerPlaceholder.style.display = "none";
          if (pdfIframe) {
            pdfIframe.style.display = "block";
            pdfIframe.style.visibility = "visible";
          }
          if (downloadLink) {
            downloadLink.href = downloadPdfUrl();
            downloadLink.style.display = "inline-block";
          }
          const isOwner = currentUserId && info.doc && info.doc.owner_id === currentUserId;
          if (reprocessDocBtn) reprocessDocBtn.style.display = isOwner ? "inline-block" : "none";
          if (regeneratePdfBtn) regeneratePdfBtn.style.display = hasAnnotatedPdf ? "inline-block" : "none";
          if (openInNewTab) openInNewTab.style.display = "inline-block";
          setPdfView(true);
          return;
        }
        if (info.doc.status === "failed") {
          typoMeta.textContent = "Reprocess failed.";
          return;
        }
        showDocProcessingState(typeof info.doc.progress === "number" ? info.doc.progress : undefined);
      }
      typoMeta.textContent = "Reprocess timed out.";
    } catch (err) {
      typoMeta.textContent = "Error: " + (err.message || "failed");
    } finally {
      reprocessDocBtn.disabled = false;
      reprocessDocBtn.textContent = prevText;
    }
  });
}

btnBackToDashboard.addEventListener("click", (e) => {
  e.preventDefault();
  location.href = "/dashboard";
});

if (reviewApproveBtn) {
  reviewApproveBtn.addEventListener("click", () => {
    const desc = reviewDescription ? reviewDescription.value.trim() : "";
    submitTypoReview("approved", desc || null);
  });
}
if (reviewApproveAllBtn) {
  reviewApproveAllBtn.addEventListener("click", () => {
    const desc = reviewDescription ? reviewDescription.value.trim() : "";
    submitTypoReviewAll("approved", desc || null);
  });
}
if (reviewFlagBtn) {
  reviewFlagBtn.addEventListener("click", () => {
    const desc = reviewDescription ? reviewDescription.value.trim() : "";
    submitTypoReview("flagged", desc || null);
  });
}
if (reviewFlagAllBtn) {
  reviewFlagAllBtn.addEventListener("click", () => {
    const desc = reviewDescription ? reviewDescription.value.trim() : "";
    submitTypoReviewAll("flagged", desc || null);
  });
}
if (reviewPrevBtn) {
  reviewPrevBtn.addEventListener("click", () => navigateReviewPanel(-1));
}
if (reviewNextBtn) {
  reviewNextBtn.addEventListener("click", () => navigateReviewPanel(1));
}
if (reviewCloseBtn) {
  reviewCloseBtn.addEventListener("click", () => clearReviewPanel());
}
if (reviewPrevWordBtn) {
  reviewPrevWordBtn.addEventListener("click", () => navigateReviewPanelByWord(-1));
}
if (reviewNextWordBtn) {
  reviewNextWordBtn.addEventListener("click", () => navigateReviewPanelByWord(1));
}

// --- Routing ---
function applyRoute(route, isAuth) {
  if (route.name === "dashboard" || route.name === "doc") {
    if (!isAuth) {
      location.href = "/login";
      return;
    }
  }

  if (route.name === "login") {
    if (isAuth) {
      location.href = "/dashboard";
      return;
    }
    showScreen("login");
    return;
  }
  if (route.name === "signup") {
    showScreen("signup");
    return;
  }
  if (route.name === "dashboard") {
    showScreen("dashboard");
    loadDashboard();
    return;
  }
  if (route.name === "profile") {
    if (!isAuth) {
      location.href = "/login";
      return;
    }
    showScreen("profile");
    loadProfile();
    return;
  }
  if (route.name === "doc" && route.docId) {
    showDocView(route.docId);
    return;
  }
  showScreen("login");
}

// --- Boot (path-based routes: /login, /signup, /dashboard, /doc/:id) ---
(async () => {
  const route = getRoute();
  const isAuth = await checkAuth();

  if (route.name === "login" || route.name === "signup") {
    applyRoute(route, isAuth);
    return;
  }
  if (route.name === "dashboard" || route.name === "doc" || route.name === "profile") {
    if (!isAuth) {
      location.href = "/login";
      return;
    }
    applyRoute(route, true);
    return;
  }
  applyRoute(route, isAuth);
})();

// --- User Info & Profile ---
async function loadUserInfo() {
  try {
    const res = await api("/api/me");
    const data = await res.json();
    if (userName) {
      userName.textContent = data.full_name || data.user || "User";
    }
    return data;
  } catch (err) {
    if (userName) userName.textContent = "User";
    return null;
  }
}

function updateProfileHero(data) {
  if (!data) return;
  const fullName = (data.full_name || "").trim();
  const company = (data.company_name || "").trim();
  const username = data.user || "";
  const displayName = fullName || username || "User";
  const initial = (displayName.charAt(0) || "?").toUpperCase();
  if (profileAvatar) profileAvatar.textContent = initial;
  if (profileHeroName) profileHeroName.textContent = displayName;
  if (profileHeroUsername) profileHeroUsername.textContent = username ? "@" + username : "";
  if (profileHeroCompany) {
    profileHeroCompany.textContent = company || "";
    profileHeroCompany.style.display = company ? "inline-block" : "none";
  }
}

async function loadProfile() {
  try {
    const data = await loadUserInfo();
    if (data && profileFullNameInput && profileCompanyNameInput) {
      profileFullNameInput.value = data.full_name || "";
      profileCompanyNameInput.value = data.company_name || "";
    }
    updateProfileHero(data);
  } catch (err) {
    if (profileError) profileError.textContent = "Failed to load profile";
  }
}

if (profileForm) {
  profileForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (profileError) profileError.textContent = "";
    if (profileSuccess) profileSuccess.textContent = "";
    try {
      const res = await api("/api/me", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: profileFullNameInput.value.trim(),
          company_name: profileCompanyNameInput.value.trim(),
        }),
      });
      const data = await res.json();
      if (profileSuccess) profileSuccess.textContent = data.message || "Profile updated successfully";
      await loadUserInfo(); // Update name in header
      try {
        const meRes = await api("/api/me");
        const meData = await meRes.json();
        updateProfileHero(meData);
      } catch (_) {}
    } catch (err) {
      if (profileError) profileError.textContent = err.message || "Failed to update profile";
    }
  });
}

if (passwordForm) {
  passwordForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (passwordError) passwordError.textContent = "";
    if (passwordSuccess) passwordSuccess.textContent = "";
    const newPwd = document.getElementById("newPassword").value;
    const confirmPwd = document.getElementById("confirmPassword").value;
    if (newPwd !== confirmPwd) {
      if (passwordError) passwordError.textContent = "New password and confirmation do not match";
      return;
    }
    try {
      const res = await api("/api/me/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          old_password: document.getElementById("oldPassword").value,
          new_password: newPwd,
          confirm_password: confirmPwd,
        }),
      });
      const data = await res.json();
      if (passwordSuccess) passwordSuccess.textContent = data.message || "Password changed successfully";
      passwordForm.reset();
    } catch (err) {
      if (passwordError) passwordError.textContent = err.message || "Failed to change password";
    }
  });
}

if (btnBackFromProfile) {
  btnBackFromProfile.addEventListener("click", (e) => {
    e.preventDefault();
    location.href = "/dashboard";
  });
}

// Load user info on page load if authenticated
(async () => {
  const isAuth = await checkAuth();
  if (isAuth) {
    await loadUserInfo();
  }
})();
