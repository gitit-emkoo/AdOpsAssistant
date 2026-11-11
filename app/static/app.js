const chatForm = document.getElementById("chatForm");
const chatLog = document.getElementById("chatLog");
const questionEl = document.getElementById("question");
const refreshMetricsEl = document.getElementById("refreshMetrics");
const refreshBtn = document.getElementById("refreshBtn");
const metricDateEl = document.getElementById("metricDate");
const loadDateBtn = document.getElementById("loadDateBtn");
const metricsHint = document.getElementById("metricsHint");
const tokenModal = document.getElementById("tokenModal");
const shortTokenInput = document.getElementById("shortTokenInput");
const extendTokenBtn = document.getElementById("extendTokenBtn");
const extendResult = document.getElementById("extendResult");
function renderMetrics(items, meta = {}) {
  const body = document.getElementById("metricsBody");
  if (!body) return;
  if (!items || !items.length) {
    body.innerHTML =
      '<tr><td colspan="7" class="muted">선택한 날짜 데이터가 없습니다. API 새로고침을 눌러보세요.</td></tr>';
  } else {
    body.innerHTML = items
      .map((m) => {
        const installs = Number(m.installs || 0);
        const clicks = Number(m.clicks || 0);
        const spend = Number(m.spend || 0);
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
              : "-";
        return `<tr>
          <td>${m.platform}</td>
          <td>${m.metric_date}</td>
          <td>${Math.round(spend).toLocaleString()}</td>
          <td>${clicks}</td>
          <td>${Math.round(installs).toLocaleString()}</td>
          <td>${installRate == null ? "-" : `${installRate}%`}</td>
          <td>${cpi}</td>
        </tr>`;
      })
      .join("");
  }
  if (metricsHint) {
    const source = meta.source === "live" ? "API 실시간 수집" : "저장 데이터";
    const dateLabel = meta.metric_date || metricDateEl?.value || "";
    metricsHint.textContent = `${dateLabel} 조회 (${source})`;
  }
}

async function loadMetricsByDate({ refresh = false } = {}) {
  const dateValue = metricDateEl?.value;
  if (!dateValue) return;
  const url = refresh
    ? `/api/metrics/refresh?date=${encodeURIComponent(dateValue)}`
    : `/api/metrics?date=${encodeURIComponent(dateValue)}`;
  const res = await fetch(url, { method: refresh ? "POST" : "GET" });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || "조회 실패");
  }
  // 캐시에 없으면 자동으로 API 수집
  if (!refresh && (!data.items || data.items.length === 0)) {
    return loadMetricsByDate({ refresh: true });
  }
  renderMetrics(data.items || [], {
    metric_date: data.metric_date || dateValue,
    source: data.source || (refresh ? "live" : "cache"),
  });
}

function appendBubble(role, content) {
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  div.innerHTML = `<div class="meta">${role}</div><div class="content"></div>`;
  div.querySelector(".content").textContent = content;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function openTokenModal() {
  if (!tokenModal) return;
  tokenModal.hidden = false;
}

function closeTokenModal() {
  if (!tokenModal) return;
  tokenModal.hidden = true;
}

document.getElementById("openTokenGuide")?.addEventListener("click", openTokenModal);
document.getElementById("closeTokenModal")?.addEventListener("click", closeTokenModal);
document.querySelectorAll(".open-guide").forEach((btn) => {
  btn.addEventListener("click", openTokenModal);
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
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        refresh_metrics: Boolean(refreshMetricsEl?.checked),
      }),
    });
    const data = await res.json();
    const bubbles = chatLog.querySelectorAll(".bubble.assistant");
    const last = bubbles[bubbles.length - 1];
    if (last) last.querySelector(".content").textContent = data.answer || "응답 없음";
  } catch (err) {
    const bubbles = chatLog.querySelectorAll(".bubble.assistant");
    const last = bubbles[bubbles.length - 1];
    if (last) last.querySelector(".content").textContent = `오류: ${err}`;
  }
});

refreshBtn?.addEventListener("click", async () => {
  refreshBtn.disabled = true;
  refreshBtn.textContent = "수집 중...";
  try {
    await loadMetricsByDate({ refresh: true });
  } catch (err) {
    if (metricsHint) metricsHint.textContent = `오류: ${err}`;
  } finally {
    refreshBtn.disabled = false;
    refreshBtn.textContent = "API 새로고침";
  }
});

loadDateBtn?.addEventListener("click", async () => {
  loadDateBtn.disabled = true;
  try {
    await loadMetricsByDate({ refresh: false });
  } catch (err) {
    if (metricsHint) metricsHint.textContent = `오류: ${err}`;
  } finally {
    loadDateBtn.disabled = false;
  }
});

metricDateEl?.addEventListener("change", async () => {
  try {
    await loadMetricsByDate({ refresh: false });
  } catch (err) {
    if (metricsHint) metricsHint.textContent = `오류: ${err}`;
  }
});

extendTokenBtn?.addEventListener("click", async () => {
  extendTokenBtn.disabled = true;
  extendResult.textContent = "교환 중...";
  try {
    const shortToken = shortTokenInput?.value.trim() || null;
    const res = await fetch("/api/integrations/meta/extend", {
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
        ? '<span class="muted">완료</span>'
        : `<button type="button" data-complete-id="${ev.id}" data-occurrence="${ev.occurrence_date}">완료</button>`;
      return `<li class="event-row">
        <div>
          <strong>[${ev.category}]</strong> ${ev.title}
          <span class="muted">${badge}</span>
        </div>
        ${done}
      </li>`;
    })
    .join("");
}

async function loadCalendar(year, month) {
  const res = await fetch(`/api/tasks/calendar?year=${year}&month=${month}`);
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

dayEventsList?.addEventListener("click", async (event) => {
  const btn = event.target.closest("[data-complete-id]");
  if (!btn) return;
  const id = btn.dataset.completeId;
  const occurrence = btn.dataset.occurrence;
  await fetch(`/api/tasks/${id}/done`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ occurrence_date: occurrence }),
  });
  await loadCalendar(calendarState.year, calendarState.month);
  if (calendarState.selectedDate) showDayEvents(calendarState.selectedDate);
});

monthlyToggle?.addEventListener("change", () => {
  const monthly = Boolean(monthlyToggle.checked);
  if (oneTimeFields) oneTimeFields.hidden = monthly;
  if (monthlyFields) monthlyFields.hidden = !monthly;
  if (taskRecurrence) taskRecurrence.value = monthly ? "monthly" : "none";
  if (monthly) {
    if (taskDueDate) taskDueDate.value = "";
  } else if (taskRecurDay) {
    taskRecurDay.value = "";
  }
});

if (taskCalendar) {
  loadCalendar(calendarState.year, calendarState.month);
}
