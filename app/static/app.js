const chatForm = document.getElementById("chatForm");
const chatLog = document.getElementById("chatLog");
const questionEl = document.getElementById("question");
const refreshMetricsEl = document.getElementById("refreshMetrics");
const refreshBtn = document.getElementById("refreshBtn");
const metricDateEl = document.getElementById("metricDate");
const metricStartEl = document.getElementById("metricStart");
const metricEndEl = document.getElementById("metricEnd");
const loadDateBtn = document.getElementById("loadDateBtn");
const loadRangeBtn = document.getElementById("loadRangeBtn");
const metricsDayRow = document.getElementById("metricsDayRow");
const metricsRangeRow = document.getElementById("metricsRangeRow");
const metricsHint = document.getElementById("metricsHint");
const metricsModeState = { mode: "recent" };
const tokenModal = document.getElementById("tokenModal");
const shortTokenInput = document.getElementById("shortTokenInput");
const extendTokenBtn = document.getElementById("extendTokenBtn");
const extendResult = document.getElementById("extendResult");
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function apiFetch(url, options) {
  const res = await fetch(url, options);
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("login required");
  }
  return res;
}

function formatCollectErrors(errors) {
  if (!errors || !errors.length) return "";
  const hints = [];
  for (const note of errors) {
    const text = String(note || "");
    const lower = text.toLowerCase();
    if (
      text.includes("Session has expired") ||
      lower.includes("access token") ||
      lower.includes("oauthexception")
    ) {
      hints.push("Meta 토큰이 만료됐습니다. 연동 설정에서 Meta를 다시 연결하세요.");
    } else if (lower.includes("google")) {
      hints.push(`Google 수집 실패: ${text.slice(0, 160)}`);
    } else if (lower.includes("meta")) {
      hints.push(`Meta 수집 실패: ${text.slice(0, 160)}`);
    } else {
      hints.push(text.slice(0, 180));
    }
  }
  return [...new Set(hints)].join(" · ");
}

function setMetricsHint(message, { isError = false } = {}) {
  if (!metricsHint) return;
  metricsHint.textContent = message;
  metricsHint.classList.toggle("hint-error", Boolean(isError));
}

function platformBadge(platform) {
  const key = String(platform || "").toLowerCase();
  if (key === "google_ads" || key === "google") {
    return '<span class="platform-badge google">Google</span>';
  }
  if (key === "meta" || key === "facebook") {
    return '<span class="platform-badge meta">Meta</span>';
  }
  return `<span class="platform-badge">${platform || "—"}</span>`;
}

function updateMetricsKpis(items) {
  let spend = 0;
  let clicks = 0;
  let installs = 0;
  for (const m of items || []) {
    spend += Number(m.spend || 0);
    clicks += Number(m.clicks || 0);
    installs += Number(m.installs || 0);
  }
  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };
  setText("kpiSpend", Math.round(spend).toLocaleString());
  setText("kpiClicks", Math.round(clicks).toLocaleString());
  setText("kpiInstalls", Math.round(installs).toLocaleString());
  setText(
    "kpiCpi",
    installs ? Math.round(spend / installs).toLocaleString() : "—"
  );
}

function renderMetrics(items, meta = {}) {
  const body = document.getElementById("metricsBody");
  if (!body) return;
  updateMetricsKpis(items);
  if (!items || !items.length) {
    body.innerHTML =
      '<tr><td colspan="8" class="empty-row">선택한 날짜 데이터가 없습니다. 새로고침을 눌러보세요.</td></tr>';
  } else {
    body.innerHTML = items
      .map((m) => {
        const installs = Number(m.installs || 0);
        const clicks = Number(m.clicks || 0);
        const spend = Number(m.spend || 0);
        const name = m.entity_name || m.entity_id || "—";
        const installRate =
          m.install_rate != null
            ? Number(m.install_rate).toFixed(1)
            : clicks
              ? ((installs / clicks) * 100).toFixed(1)
              : null;
        const cpi =
          m.cpi != null && Number(m.cpi) > 0
            ? Math.round(Number(m.cpi)).toLocaleString()
            : installs
              ? Math.round(spend / installs).toLocaleString()
              : "—";
        return `<tr>
          <td>${platformBadge(m.platform)}</td>
          <td>${escapeHtml(String(name))}</td>
          <td class="date-cell">${m.metric_date}</td>
          <td class="num">${Math.round(spend).toLocaleString()}</td>
          <td class="num">${clicks}</td>
          <td class="num">${Math.round(installs).toLocaleString()}</td>
          <td class="num">${installRate == null ? "—" : `${installRate}%`}</td>
          <td class="num">${cpi}</td>
        </tr>`;
      })
      .join("");
  }
  const source = meta.source === "live" ? "실시간" : "저장 데이터";
  const dateLabel = meta.metric_date || metricDateEl?.value || "";
  const errorText = formatCollectErrors(meta.errors);
  if (errorText) {
    const base = items?.length
      ? `${dateLabel} · 일부만 갱신됨`
      : `${dateLabel} · 수집 실패`;
    setMetricsHint(`${base} — ${errorText}`, { isError: true });
  } else {
    setMetricsHint(`${dateLabel} · ${source}`, { isError: false });
  }
}

function setMetricsMode(mode) {
  metricsModeState.mode = mode;
  document.querySelectorAll("#metricsModes .mode-btn").forEach((btn) => {
    const active = btn.dataset.mode === mode;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  if (metricsDayRow) metricsDayRow.hidden = mode !== "day";
  if (metricsRangeRow) metricsRangeRow.hidden = mode !== "range";
}

function currentMetricsQuery({ refresh = false } = {}) {
  const mode = metricsModeState.mode || "recent";
  if (mode === "day") {
    const dateValue = metricDateEl?.value;
    if (!dateValue) throw new Error("조회 날짜를 선택하세요.");
    const q = `date=${encodeURIComponent(dateValue)}`;
    return {
      url: refresh ? `/api/metrics/refresh?${q}` : `/api/metrics?${q}`,
      method: refresh ? "POST" : "GET",
      label: dateValue,
    };
  }
  if (mode === "range") {
    const start = metricStartEl?.value;
    const end = metricEndEl?.value;
    if (!start || !end) throw new Error("시작일과 끝일을 선택하세요.");
    const q = `start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
    return {
      url: refresh ? `/api/metrics/refresh?${q}` : `/api/metrics?${q}`,
      method: refresh ? "POST" : "GET",
      label: `${start} ~ ${end}`,
    };
  }
  return {
    url: refresh
      ? `/api/metrics/refresh?start=${encodeURIComponent(metricStartEl?.value || "")}&end=${encodeURIComponent(metricEndEl?.value || metricDateEl?.value || "")}`
      : "/api/metrics?days=3",
    method: refresh ? "POST" : "GET",
    label: "최근 3일",
  };
}

async function loadMetricsByDate({ refresh = false } = {}) {
  const query = currentMetricsQuery({ refresh });
  // 최근 3일 새로고침은 start/end 비면 기본 최근 3일로
  let url = query.url;
  if (
    refresh &&
    metricsModeState.mode === "recent" &&
    (!metricStartEl?.value || !metricEndEl?.value)
  ) {
    const end = metricDateEl?.value;
    if (end) {
      const endDate = new Date(`${end}T00:00:00`);
      const startDate = new Date(endDate);
      startDate.setDate(endDate.getDate() - 2);
      const start = startDate.toISOString().slice(0, 10);
      url = `/api/metrics/refresh?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
    } else {
      url = "/api/metrics?days=3";
      refresh = false;
    }
  }
  const res = await apiFetch(url, { method: refresh ? "POST" : query.method });
  const raw = await res.text();
  let data = null;
  try {
    data = raw ? JSON.parse(raw) : null;
  } catch {
    throw new Error(
      res.ok
        ? "서버 응답을 읽지 못했습니다."
        : `서버 오류 (${res.status}). Meta 토큰 만료나 수집 실패일 수 있습니다.`
    );
  }
  if (!res.ok) {
    const detail = data?.detail || data?.message || data?.errors?.join?.(" / ");
    throw new Error(detail || `조회 실패 (${res.status})`);
  }
  // 일별이고 캐시 없으면 자동 수집
  if (
    !refresh &&
    metricsModeState.mode === "day" &&
    (!data.items || data.items.length === 0)
  ) {
    return loadMetricsByDate({ refresh: true });
  }
  renderMetrics(data.items || [], {
    metric_date: data.metric_date || query.label,
    source: data.source || (refresh ? "live" : "cache"),
    errors: data.errors || [],
  });
  if (refresh && data.errors?.length && !(data.items || []).length) {
    throw new Error(formatCollectErrors(data.errors) || "수집 실패");
  }
}

function appendBubble(role, content) {
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  div.innerHTML = `<div class="meta">${role}</div><div class="content"></div>`;
  div.querySelector(".content").textContent = content;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function openTokenModal(focus) {
  if (!tokenModal) return;
  tokenModal.hidden = false;
  const targetId =
    focus === "google" ? "guide-google" : focus === "meta" ? "guide-meta" : null;
  if (targetId) {
    requestAnimationFrame(() => {
      tokenModal.querySelector(`#${targetId}`)?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  }
}

function closeTokenModal() {
  if (!tokenModal) return;
  tokenModal.hidden = true;
}

document.getElementById("openTokenGuide")?.addEventListener("click", () =>
  openTokenModal()
);
document.getElementById("closeTokenModal")?.addEventListener("click", closeTokenModal);
document.querySelectorAll(".open-guide").forEach((btn) => {
  btn.addEventListener("click", () => openTokenModal(btn.dataset.focus));
});

document.querySelectorAll("[data-dismiss-alert]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const alertEl = btn.closest(".alert");
    const key = alertEl?.dataset?.alertKey;
    if (key) sessionStorage.setItem(`dismissed-alert:${key}`, "1");
    alertEl?.remove();
    if (!document.querySelector(".alerts .alert")) {
      document.querySelector(".alerts")?.remove();
    }
  });
});

document.querySelectorAll(".alert[data-alert-key]").forEach((alertEl) => {
  const key = alertEl.dataset.alertKey;
  if (key && sessionStorage.getItem(`dismissed-alert:${key}`) === "1") {
    alertEl.remove();
  }
});
if (!document.querySelector(".alerts .alert")) {
  document.querySelector(".alerts")?.remove();
}

tokenModal?.addEventListener("click", (event) => {
  if (event.target === tokenModal) closeTokenModal();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeTokenModal();
});

chatForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionEl.value.trim();
  if (!question) return;

  appendBubble("user", question);
  questionEl.value = "";
  appendBubble("assistant", "생각 중...");

  try {
    const res = await apiFetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        refresh_metrics: Boolean(refreshMetricsEl?.checked),
      }),
    });
    const raw = await res.text();
    let data = null;
    try {
      data = raw ? JSON.parse(raw) : null;
    } catch {
      throw new Error(
        res.ok
          ? "서버 응답을 읽지 못했습니다."
          : `서버 오류 (${res.status}). Meta 토큰 만료나 수집 실패일 수 있습니다.`
      );
    }
    if (!res.ok) {
      throw new Error(data?.detail || data?.message || `요청 실패 (${res.status})`);
    }
    const bubbles = chatLog.querySelectorAll(".bubble.assistant");
    const last = bubbles[bubbles.length - 1];
    if (last) last.querySelector(".content").textContent = data.answer || "응답 없음";
  } catch (err) {
    const bubbles = chatLog.querySelectorAll(".bubble.assistant");
    const last = bubbles[bubbles.length - 1];
    if (last) last.querySelector(".content").textContent = `오류: ${err.message || err}`;
  }
});

document.querySelectorAll("#metricsModes .mode-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    setMetricsMode(btn.dataset.mode || "recent");
    try {
      await loadMetricsByDate({ refresh: false });
    } catch (err) {
      setMetricsHint(`오류: ${err.message || err}`, { isError: true });
    }
  });
});
setMetricsMode("recent");

refreshBtn?.addEventListener("click", async () => {
  refreshBtn.disabled = true;
  refreshBtn.textContent = "수집 중...";
  setMetricsHint("API에서 수집 중...", { isError: false });
  try {
    await loadMetricsByDate({ refresh: true });
  } catch (err) {
    setMetricsHint(`오류: ${err.message || err}`, { isError: true });
  } finally {
    refreshBtn.disabled = false;
    refreshBtn.textContent = "API 새로고침";
  }
});

loadDateBtn?.addEventListener("click", async () => {
  loadDateBtn.disabled = true;
  try {
    setMetricsMode("day");
    await loadMetricsByDate({ refresh: false });
  } catch (err) {
    setMetricsHint(`오류: ${err.message || err}`, { isError: true });
  } finally {
    loadDateBtn.disabled = false;
  }
});

loadRangeBtn?.addEventListener("click", async () => {
  loadRangeBtn.disabled = true;
  try {
    setMetricsMode("range");
    await loadMetricsByDate({ refresh: false });
  } catch (err) {
    setMetricsHint(`오류: ${err.message || err}`, { isError: true });
  } finally {
    loadRangeBtn.disabled = false;
  }
});

metricDateEl?.addEventListener("change", async () => {
  if (metricsModeState.mode !== "day") return;
  try {
    await loadMetricsByDate({ refresh: false });
  } catch (err) {
    setMetricsHint(`오류: ${err.message || err}`, { isError: true });
  }
});

extendTokenBtn?.addEventListener("click", async () => {
  extendTokenBtn.disabled = true;
  extendResult.textContent = "교환 중...";
  try {
    const shortToken = shortTokenInput?.value.trim() || null;
    const res = await apiFetch("/api/integrations/meta/extend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ short_token: shortToken }),
    });
    const data = await res.json();
    if (!data.ok) {
      extendResult.textContent = `실패: ${data.error || "알 수 없는 오류"}`;
      return;
    }
    const days = data.expires_in_days != null ? `${data.expires_in_days}일` : "확인됨";
    extendResult.textContent = `${data.message} (유효기간: ${days})`;
    if (shortTokenInput) shortTokenInput.value = "";
  } catch (err) {
    extendResult.textContent = `오류: ${err}`;
  } finally {
    extendTokenBtn.disabled = false;
  }
});

// 모달은 자동으로 열지 않음. 상단 알림/토큰 안내 버튼에서만 연다.

const TASK_CATEGORY_LABELS = {
  finance: "재무",
  tax: "세무",
  ads: "광고",
  general: "일반",
};

function categoryLabel(category) {
  const key = (category || "general").toLowerCase();
  return TASK_CATEGORY_LABELS[key] || category || "일반";
}

function categoryClass(category) {
  const key = (category || "general").toLowerCase();
  return TASK_CATEGORY_LABELS[key] ? `cat-${key}` : "cat-general";
}

const taskCalendar = document.getElementById("taskCalendar");
const calGrid = document.getElementById("calGrid");
const calLabel = document.getElementById("calLabel");
const calPrev = document.getElementById("calPrev");
const calNext = document.getElementById("calNext");
const dayEventsTitle = document.getElementById("dayEventsTitle");
const dayEventsList = document.getElementById("dayEventsList");
const monthlyToggle = document.getElementById("monthlyToggle");
const oneTimeFields = document.getElementById("oneTimeFields");
const monthlyFields = document.getElementById("monthlyFields");
const taskRecurrence = document.getElementById("taskRecurrence");
const taskDueDate = document.getElementById("taskDueDate");
const taskRecurDay = document.getElementById("taskRecurDay");

let calendarState = {
  year: Number(taskCalendar?.dataset.year || new Date().getFullYear()),
  month: Number(taskCalendar?.dataset.month || new Date().getMonth() + 1),
  selectedDate: null,
  data: null,
};

function renderCalendar(data) {
  calendarState.data = data;
  calendarState.year = data.year;
  calendarState.month = data.month;
  if (calLabel) calLabel.textContent = data.label;
  if (!calGrid) return;
  calGrid.innerHTML = data.cells
    .map((cell) => {
      if (!cell.date) return '<div class="cal-cell empty"></div>';
      const chips = (cell.events || [])
        .slice(0, 2)
        .map((ev) => {
          const cls = [
            "cal-chip",
            categoryClass(ev.category),
            ev.completed ? "done" : "",
            ev.is_recurring ? "recur" : "",
          ]
            .filter(Boolean)
            .join(" ");
          return `<span class="${cls}">${ev.title}</span>`;
        })
        .join("");
      const more =
        (cell.events || []).length > 2
          ? `<span class="cal-more">+${cell.events.length - 2}</span>`
          : "";
      const selected = calendarState.selectedDate === cell.date ? "selected" : "";
      return `<button type="button" class="cal-cell ${cell.is_today ? "today" : ""} ${
        cell.events?.length ? "has-events" : ""
      } ${selected}" data-date="${cell.date}">
        <span class="cal-day">${cell.day}</span>
        ${chips}${more}
      </button>`;
    })
    .join("");
}

function showDayEvents(dateStr) {
  calendarState.selectedDate = dateStr;
  const events =
    (calendarState.data?.events || []).filter((e) => e.occurrence_date === dateStr) ||
    [];
  if (dayEventsTitle) dayEventsTitle.textContent = `${dateStr} 할 일`;
  if (!dayEventsList) return;
  if (!events.length) {
    dayEventsList.innerHTML = '<li class="muted">이 날짜 할 일이 없습니다.</li>';
    return;
  }
  dayEventsList.innerHTML = events
    .map((ev) => {
      const badge = ev.is_recurring ? "매달" : "하루";
      const done = ev.completed
        ? '<span class="muted">완료됨</span>'
        : `<button type="button" class="btn-sm" data-complete-id="${ev.id}" data-occurrence="${ev.occurrence_date}">완료</button>`;
      return `<li class="event-row ${ev.completed ? "is-done" : ""}">
        <div>
          <span class="cat-badge ${categoryClass(ev.category)}">${categoryLabel(ev.category)}</span>
          <strong>${ev.title}</strong>
          <span class="muted">${badge}</span>
        </div>
        <div class="event-actions">
          ${done}
          <button type="button" class="ghost btn-sm" data-edit-id="${ev.id}">수정</button>
          <button type="button" class="ghost btn-sm" data-delete-id="${ev.id}">삭제</button>
        </div>
      </li>`;
    })
    .join("");
}

async function loadCalendar(year, month) {
  const res = await apiFetch(`/api/tasks/calendar?year=${year}&month=${month}`);
  const data = await res.json();
  renderCalendar(data);
  if (calendarState.selectedDate) showDayEvents(calendarState.selectedDate);
}

calPrev?.addEventListener("click", () => {
  const prev = calendarState.data?.prev;
  if (!prev) return;
  loadCalendar(prev.year, prev.month);
});

calNext?.addEventListener("click", () => {
  const next = calendarState.data?.next;
  if (!next) return;
  loadCalendar(next.year, next.month);
});

calGrid?.addEventListener("click", (event) => {
  const cell = event.target.closest("[data-date]");
  if (!cell) return;
  showDayEvents(cell.dataset.date);
  calGrid.querySelectorAll(".cal-cell.selected").forEach((el) => el.classList.remove("selected"));
  cell.classList.add("selected");
});

const taskForm = document.getElementById("taskForm");
const taskEditId = document.getElementById("taskEditId");
const taskTitle = document.getElementById("taskTitle");
const taskCategory = document.getElementById("taskCategory");
const taskSubmitBtn = document.getElementById("taskSubmitBtn");
const taskCancelEdit = document.getElementById("taskCancelEdit");

function setMonthlyMode(monthly) {
  if (monthlyToggle) monthlyToggle.checked = monthly;
  if (oneTimeFields) oneTimeFields.hidden = monthly;
  if (monthlyFields) monthlyFields.hidden = !monthly;
  if (taskRecurrence) taskRecurrence.value = monthly ? "monthly" : "none";
}

function resetTaskForm() {
  if (taskEditId) taskEditId.value = "";
  if (taskTitle) taskTitle.value = "";
  if (taskCategory) taskCategory.value = "finance";
  if (taskDueDate) taskDueDate.value = "";
  if (taskRecurDay) taskRecurDay.value = "";
  setMonthlyMode(false);
  if (taskSubmitBtn) taskSubmitBtn.textContent = "추가";
  if (taskCancelEdit) taskCancelEdit.hidden = true;
}

async function fillTaskForm(taskId) {
  const res = await apiFetch(`/api/tasks/${taskId}`);
  const data = await res.json();
  if (!data.ok || !data.item) {
    alert(data.error || "할 일을 불러오지 못했습니다.");
    return;
  }
  const task = data.item;
  if (taskEditId) taskEditId.value = String(task.id);
  if (taskTitle) taskTitle.value = task.title || "";
  if (taskCategory) taskCategory.value = task.category || "general";
  const monthly = (task.recurrence || "none") === "monthly";
  setMonthlyMode(monthly);
  if (monthly) {
    if (taskRecurDay) taskRecurDay.value = task.recur_day || "";
    if (taskDueDate) taskDueDate.value = "";
  } else {
    if (taskDueDate) taskDueDate.value = task.due_date || "";
    if (taskRecurDay) taskRecurDay.value = "";
  }
  if (taskSubmitBtn) taskSubmitBtn.textContent = "수정 저장";
  if (taskCancelEdit) taskCancelEdit.hidden = false;
  taskTitle?.focus();
}

dayEventsList?.addEventListener("click", async (event) => {
  const completeBtn = event.target.closest("[data-complete-id]");
  if (completeBtn) {
    const id = completeBtn.dataset.completeId;
    const occurrence = completeBtn.dataset.occurrence;
    await apiFetch(`/api/tasks/${id}/done`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ occurrence_date: occurrence }),
    });
    await loadCalendar(calendarState.year, calendarState.month);
    if (calendarState.selectedDate) showDayEvents(calendarState.selectedDate);
    return;
  }

  const editBtn = event.target.closest("[data-edit-id]");
  if (editBtn) {
    await fillTaskForm(editBtn.dataset.editId);
    return;
  }

  const deleteBtn = event.target.closest("[data-delete-id]");
  if (deleteBtn) {
    const id = deleteBtn.dataset.deleteId;
    if (!confirm("이 할 일을 삭제할까요? (반복 일정이면 앞으로 일정도 함께 삭제됩니다)")) {
      return;
    }
    await apiFetch(`/api/tasks/${id}`, { method: "DELETE" });
    if (taskEditId?.value === String(id)) resetTaskForm();
    await loadCalendar(calendarState.year, calendarState.month);
    if (calendarState.selectedDate) showDayEvents(calendarState.selectedDate);
  }
});

monthlyToggle?.addEventListener("change", () => {
  const monthly = Boolean(monthlyToggle.checked);
  setMonthlyMode(monthly);
  if (monthly) {
    if (taskDueDate) taskDueDate.value = "";
  } else if (taskRecurDay) {
    taskRecurDay.value = "";
  }
});

taskCancelEdit?.addEventListener("click", () => {
  resetTaskForm();
});

taskForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const title = taskTitle?.value.trim();
  if (!title) return;
  const monthly = Boolean(monthlyToggle?.checked);
  const payload = {
    title,
    category: taskCategory?.value || "general",
    recurrence: monthly ? "monthly" : "none",
    due_date: monthly ? null : taskDueDate?.value || null,
    recur_day: monthly ? Number(taskRecurDay?.value || 0) || null : null,
  };
  if (monthly && !payload.recur_day) {
    alert("매달 반복이면 날짜(1-31)를 입력하세요.");
    return;
  }

  const editId = taskEditId?.value;
  const res = await apiFetch(editId ? `/api/tasks/${editId}` : "/api/tasks", {
    method: editId ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    alert(data.error || "저장에 실패했습니다.");
    return;
  }
  resetTaskForm();
  await loadCalendar(calendarState.year, calendarState.month);
  if (calendarState.selectedDate) showDayEvents(calendarState.selectedDate);
});

if (taskCalendar) {
  loadCalendar(calendarState.year, calendarState.month);
}

function classifyAdsError(note) {
  const text = String(note || "");
  const lower = text.toLowerCase();
  if (
    lower.includes("google") ||
    lower.includes("oauth2.googleapis.com") ||
    lower.includes("invalid_grant")
  ) {
    return {
      provider: "google",
      message:
        "Google Ads 연동 오류: Refresh Token이 만료·폐기됐을 수 있습니다. google_ads_oauth.py로 다시 발급하세요.",
    };
  }
  if (
    text.includes("Session has expired") ||
    lower.includes("access token") ||
    lower.includes("oauthexception") ||
    lower.includes("meta")
  ) {
    return {
      provider: "meta",
      message: "Meta 토큰이 만료되어 Meta 캠페인을 못 불러왔습니다.",
    };
  }
  return { provider: "other", message: text.slice(0, 180) };
}

function renderActiveAdsErrors(errors, board) {
  let errorsWrap = document.getElementById("activeAdsErrors");
  if (!errors?.length) {
    errorsWrap?.remove();
    return;
  }
  const classified = [];
  const seen = new Set();
  let hasMeta = false;
  let hasGoogle = false;
  for (const note of errors) {
    const item = classifyAdsError(note);
    if (item.provider === "meta") hasMeta = true;
    if (item.provider === "google") hasGoogle = true;
    if (!seen.has(item.message)) {
      seen.add(item.message);
      classified.push(item);
    }
  }
  if (!errorsWrap) {
    errorsWrap = document.createElement("div");
    errorsWrap.id = "activeAdsErrors";
    errorsWrap.className = "active-ads-error";
    board?.appendChild(errorsWrap);
  }
  const messages = classified
    .map((item) => `<p class="hint-error">${item.message}</p>`)
    .join("");
  const actions = [
    hasMeta
      ? `<button type="button" class="ghost btn-sm open-guide" data-focus="meta">Meta 장기 토큰으로 교환</button>`
      : "",
    hasGoogle
      ? `<button type="button" class="ghost btn-sm open-guide" data-focus="google">Google 해결 방법</button>`
      : "",
  ]
    .filter(Boolean)
    .join("");
  errorsWrap.innerHTML = `${messages}<div class="active-ads-error-actions">${actions}</div>`;
  errorsWrap.querySelectorAll(".open-guide").forEach((btn) => {
    btn.addEventListener("click", () => openTokenModal(btn.dataset.focus));
  });
}

function renderActiveAds(data) {
  const list = document.getElementById("activeAdsList");
  const hint = document.getElementById("activeAdsHint");
  const board = document.getElementById("activeAdsBoard");
  if (!list) return;
  const items = data.items || [];
  const metricDate = data.metric_date || "";
  if (hint) {
    const src =
      data.source === "cache"
        ? " · 캐시"
        : data.source === "stale_cache"
          ? " · 이전 캐시"
          : "";
    hint.textContent = metricDate
      ? `성과 기준일 ${metricDate}${src}`
      : "진행 중 캠페인";
  }
  if (board) board.dataset.metricDate = metricDate;

  renderActiveAdsErrors(data.errors, board);

  if (!items.length) {
    list.innerHTML =
      '<p class="muted">진행 중 광고가 없거나, 연동/토큰을 확인해 주세요.</p>';
    return;
  }

  const escapeHtml = (value) =>
    String(value || "-")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");

  const rows = items
    .map((ad) => {
      const platform = ad.platform === "google_ads" ? "Google" : "Meta";
      const account = escapeHtml(ad.account_name || ad.account_id || "-");
      const period = `${ad.start_date || "?"} ~ ${ad.end_date || "진행중"}`;
      const installRate =
        ad.clicks && ad.install_rate != null
          ? `${Number(ad.install_rate).toFixed(1)}%`
          : "-";
      const cpi =
        ad.installs && Number(ad.cpi) > 0
          ? Math.round(Number(ad.cpi)).toLocaleString()
          : "-";
      const name = escapeHtml(ad.name || "-");
      return `<tr class="campaign-row"
        data-platform="${escapeHtml(ad.platform || "")}"
        data-campaign-id="${escapeHtml(ad.campaign_id || "")}"
        data-account-id="${escapeHtml(ad.account_id || "")}"
        tabindex="0" role="button" title="클릭하면 광고세트 보기">
        <td>${platformBadge(ad.platform)}</td>
        <td class="account-cell">${account}</td>
        <td class="name-cell"><span class="expand-caret">▸</span> ${name}</td>
        <td class="period-cell">${period}</td>
        <td class="num">${Math.round(Number(ad.spend || 0)).toLocaleString()}</td>
        <td class="num">${Number(ad.clicks || 0)}</td>
        <td class="num">${Math.round(Number(ad.installs || 0)).toLocaleString()}</td>
        <td class="num">${installRate}</td>
        <td class="num">${cpi}</td>
      </tr>`;
    })
    .join("");

  list.innerHTML = `<table class="active-ads-table">
    <thead>
      <tr>
        <th>채널</th><th>계정</th><th>광고 이름</th><th>광고기간</th>
        <th class="num">지출</th><th class="num">클릭</th><th class="num">설치</th><th class="num">설치율</th><th class="num">CPI</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>`;
  bindCampaignRowExpanders(list);
}

function metricCells(ad) {
  const installRate =
    ad.clicks && ad.install_rate != null
      ? `${Number(ad.install_rate).toFixed(1)}%`
      : "-";
  const cpi =
    ad.installs && Number(ad.cpi) > 0
      ? Math.round(Number(ad.cpi)).toLocaleString()
      : "-";
  return `
    <td class="num">${Math.round(Number(ad.spend || 0)).toLocaleString()}</td>
    <td class="num">${Number(ad.clicks || 0)}</td>
    <td class="num">${Math.round(Number(ad.installs || 0)).toLocaleString()}</td>
    <td class="num">${installRate}</td>
    <td class="num">${cpi}</td>`;
}

async function toggleCampaignAdsets(row) {
  if (!row) return;
  const table = row.closest("table");
  const tbody = row.parentElement;
  if (!table || !tbody) return;

  const campaignId = row.dataset.campaignId || "";
  const platform = row.dataset.platform || "";
  const accountId = row.dataset.accountId || "";
  const key = `${platform}:${accountId}:${campaignId}`;

  // 이미 열려 있으면 닫기
  if (row.classList.contains("is-open")) {
    row.classList.remove("is-open");
    [...tbody.querySelectorAll(`tr[data-parent="${CSS.escape(key)}"]`)].forEach((el) =>
      el.remove()
    );
    return;
  }

  row.classList.add("is-open");
  const loading = document.createElement("tr");
  loading.className = "adset-loading";
  loading.dataset.parent = key;
  loading.innerHTML =
    '<td colspan="9">광고세트 불러오는 중...</td>';
  row.after(loading);

  try {
    const board = document.getElementById("activeAdsBoard");
    const metricDate = board?.dataset?.metricDate || "";
    const params = new URLSearchParams({
      platform,
      campaign_id: campaignId,
    });
    if (accountId) params.set("account_id", accountId);
    if (metricDate) params.set("date", metricDate);
    const res = await apiFetch(`/api/active-ads/adsets?${params.toString()}`);
    const data = await res.json();
    loading.remove();
    if (!res.ok || data.ok === false) {
      const err = document.createElement("tr");
      err.className = "adset-error";
      err.dataset.parent = key;
      err.innerHTML = `<td colspan="9">오류: ${data.error || res.status}</td>`;
      row.after(err);
      return;
    }
    const items = data.items || [];
    if (!items.length) {
      const empty = document.createElement("tr");
      empty.className = "adset-empty";
      empty.dataset.parent = key;
      empty.innerHTML = '<td colspan="9">광고세트가 없습니다.</td>';
      row.after(empty);
      return;
    }
    let anchor = row;
    items.forEach((ad) => {
      const tr = document.createElement("tr");
      tr.className = "adset-row";
      tr.dataset.parent = key;
      const name = String(ad.name || "-")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
      tr.innerHTML = `
        <td></td>
        <td class="account-cell">광고세트</td>
        <td class="name-cell">↳ ${name}</td>
        <td class="period-cell">${ad.start_date || "?"} ~ ${ad.end_date || "진행중"}</td>
        ${metricCells(ad)}`;
      anchor.after(tr);
      anchor = tr;
    });
  } catch (err) {
    loading.remove();
    const fail = document.createElement("tr");
    fail.className = "adset-error";
    fail.dataset.parent = key;
    fail.innerHTML = `<td colspan="9">오류: ${err.message || err}</td>`;
    row.after(fail);
  }
}

function bindCampaignRowExpanders(root) {
  const scope = root || document;
  scope.querySelectorAll(".campaign-row").forEach((row) => {
    if (row.dataset.boundExpand === "1") return;
    row.dataset.boundExpand = "1";
    row.addEventListener("click", () => toggleCampaignAdsets(row));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggleCampaignAdsets(row);
      }
    });
  });
}

bindCampaignRowExpanders(document.getElementById("activeAdsList"));

document.getElementById("activeAdsRefresh")?.addEventListener("click", async () => {
  const btn = document.getElementById("activeAdsRefresh");
  const hint = document.getElementById("activeAdsHint");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "불러오는 중...";
  }
  if (hint) hint.textContent = "진행 중 캠페인 새로고침 중...";
  try {
    const res = await apiFetch("/api/active-ads?refresh=true");
    const raw = await res.text();
    let data = null;
    try {
      data = raw ? JSON.parse(raw) : null;
    } catch {
      throw new Error(`서버 오류 (${res.status})`);
    }
    if (!res.ok) throw new Error(data?.detail || `요청 실패 (${res.status})`);
    renderActiveAds(data || { items: [], errors: [] });
  } catch (err) {
    if (hint) hint.textContent = `오류: ${err.message || err}`;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "새로고침";
    }
  }
});
