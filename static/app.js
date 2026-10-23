
const $ = (selector) => document.querySelector(selector);
const taskList = $("#task-list");
const chatLog = $("#chat-log");
let toastTimer;
const conversations = [];

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[char]);
}

function formatReply(text) {
  const safe = escapeHtml(text);
  return safe.split("\n").map((line) => {
    if (line.startsWith("- ")) {
      return `<div>• ${line.slice(2)}</div>`;
    }
    return line;
  }).join("<br>");
}

function showToast(message) {
  const toast = $("#toast");
  if (!toast) return;

  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);

  toastTimer = setTimeout(() => {
    toast.classList.remove("show");
  }, 2200);
}

function addMessage(role, text) {
  const welcome = $("#welcome");
  if (welcome) welcome.classList.add("hidden");

  if (!chatLog) return;

  const item = document.createElement("div");
  item.className = `message ${role}`;

  const label = role === "assistant" ? "LifePilot" : "You";

  item.innerHTML = `
    <div class="avatar">${role === "assistant" ? "✦" : "●"}</div>
    <div class="bubble">
      <strong>${label}</strong>
      <p>${formatReply(text)}</p>
    </div>`;

  chatLog.appendChild(item);
  chatLog.scrollTop = chatLog.scrollHeight;
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Request failed");
  }

  return data;
}

async function loadTasks() {
  if (!taskList) {
    console.error("Task list element #task-list was not found.");
    return;
  }

  try {
    const data = await request("/api/tasks");
    const tasks = Array.isArray(data.tasks) ? data.tasks : [];

    // Safely update counters only when their HTML elements exist.
    const taskCount = $("#task-count");
    if (taskCount) {
      taskCount.textContent = tasks.filter(
        (task) => !task.completed
      ).length;
    }

    const docCount = $("#doc-count");
    if (docCount) {
      docCount.textContent = tasks.length;
    }

    const taskSummary = $("#task-summary");
    if (taskSummary) {
      const completedCount = tasks.filter(
        (task) => task.completed
      ).length;

      taskSummary.textContent =
        `${tasks.length} task${tasks.length === 1 ? "" : "s"} · ` +
        `${completedCount} done`;
    }

    if (tasks.length === 0) {
      taskList.innerHTML = `
        <div class="empty-state">
          No tasks yet. Add one here or ask LifePilot in chat.
        </div>`;
      return;
    }

    taskList.innerHTML = tasks.map((task) => `
      <div class="task-item">
        <input
          class="task-check"
          type="checkbox"
          aria-label="Mark task complete"
          data-complete="${escapeHtml(task.id)}"
          ${task.completed ? "checked" : ""}
        >

        <div class="task-info">
          <div class="task-title ${task.completed ? "done" : ""}">
            ${escapeHtml(task.title)}
          </div>

          <div class="task-meta">
            <span class="priority ${escapeHtml(task.priority)}">
              ${escapeHtml(task.priority)}
            </span>
            ${task.due_date
        ? `<span>Due ${escapeHtml(task.due_date)}</span>`
        : "<span>No due date</span>"
      }
          </div>
        </div>

        <button
          class="delete-task"
          data-delete="${escapeHtml(task.id)}"
          aria-label="Delete task"
        >×</button>
      </div>
    `).join("");

  } catch (error) {
    taskList.innerHTML = `
      <div class="empty-state">
        Could not load tasks: ${escapeHtml(error.message)}
      </div>`;
    console.error("Failed to load tasks:", error);
  }
}

async function sendChat(message) {
  const trimmed = message.trim();
  if (!trimmed) return;

  addMessage("user", trimmed);

  const chatInput = $("#chat-input");
  if (chatInput) chatInput.value = "";

  const pageTitle = $("#page-title");
  if (pageTitle) {
    pageTitle.textContent =
      trimmed.length > 28 ? trimmed.slice(0, 28) + "…" : trimmed;
  }

  const sendButton = $("#chat-form .send-button");
  if (sendButton) sendButton.disabled = true;

  try {
    const data = await request("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message: trimmed })
    });

    addMessage("assistant", data.reply);
    await loadTasks();

  } catch (error) {
    addMessage(
      "assistant",
      `Sorry, something went wrong: ${error.message}`
    );
  } finally {
    if (sendButton) sendButton.disabled = false;
    if (chatInput) chatInput.focus();
  }
}

const chatForm = $("#chat-form");
if (chatForm) {
  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const chatInput = $("#chat-input");
    if (chatInput) await sendChat(chatInput.value);
  });
}

const chatInput = $("#chat-input");
if (chatInput) {
  chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      const form = $("#chat-form");
      if (form) form.requestSubmit();
    }
  });
}

const taskForm = $("#task-form");
if (taskForm) {
  taskForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const titleInput = $("#task-title");
    const priorityInput = $("#task-priority");

    if (!titleInput || !priorityInput) return;

    const title = titleInput.value.trim();
    const priority = priorityInput.value;

    if (!title) return;

    try {
      await request("/api/tasks", {
        method: "POST",
        body: JSON.stringify({ title, priority })
      });

      titleInput.value = "";
      await loadTasks();
      showToast("Task added");

    } catch (error) {
      showToast(error.message);
    }
  });
}

if (taskList) {
  taskList.addEventListener("change", async (event) => {
    const id = event.target.dataset.complete;
    if (!id) return;

    try {
      await request(`/api/tasks/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          completed: event.target.checked
        })
      });

      await loadTasks();

    } catch (error) {
      showToast(error.message);
      await loadTasks();
    }
  });

  taskList.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-delete]");
    if (!button) return;

    try {
      await request(`/api/tasks/${button.dataset.delete}`, {
        method: "DELETE"
      });

      await loadTasks();
      showToast("Task deleted");

    } catch (error) {
      showToast(error.message);
    }
  });
}

function showTab(tab) {
  const docs = tab === "documents";

  const chatView = $("#chat-view");
  const documentsView = $("#documents-view");
  const tabChat = $("#tab-chat");
  const tabDocuments = $("#tab-documents");
  const pageTitle = $("#page-title");

  if (chatView) chatView.classList.toggle("hidden", docs);
  if (documentsView) {
    documentsView.classList.toggle("hidden", !docs);
  }

  if (tabChat) tabChat.classList.toggle("active", !docs);
  if (tabDocuments) {
    tabDocuments.classList.toggle("active", docs);
  }

  if (pageTitle) {
    pageTitle.textContent = docs ? "Documents" : "New chat";
  }

  if (docs) loadTasks();
}

const tabChat = $("#tab-chat");
if (tabChat) {
  tabChat.addEventListener("click", () => showTab("chat"));
}

const tabDocuments = $("#tab-documents");
if (tabDocuments) {
  tabDocuments.addEventListener("click", () => showTab("documents"));
}

const backToChat = $("#back-to-chat");
if (backToChat) {
  backToChat.addEventListener("click", () => showTab("chat"));
}

const newChat = $("#new-chat");
if (newChat) {
  newChat.addEventListener("click", () => {
    if (chatLog) chatLog.innerHTML = "";

    const welcome = $("#welcome");
    if (welcome) welcome.classList.remove("hidden");

    if (chatInput) chatInput.value = "";

    const pageTitle = $("#page-title");
    if (pageTitle) pageTitle.textContent = "New chat";

    showTab("chat");
    if (chatInput) chatInput.focus();
  });
}

const sidebarToggle = $("#sidebar-toggle");
if (sidebarToggle) {
  sidebarToggle.addEventListener("click", () => {
    document.body.classList.toggle("sidebar-collapsed");
  });
}

const buttonMessages = [
  ["#settings-button", "Settings are coming soon."],
  ["#more-button", "More workspace tools coming soon."],
  ["#model-button", "LifePilot AI is the current prototype assistant."],
  ["#mode-button", "Assistant mode selected."],
  ["#attach-button", "Attachments are not enabled in this prototype."],
  ["#web-button", "Web search is not connected yet."],
  ["#voice-button", "Voice input is coming soon."]
];

buttonMessages.forEach(([selector, message]) => {
  const button = $(selector);
  if (button) {
    button.addEventListener("click", () => showToast(message));
  }
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    sendChat(button.dataset.prompt);
  });
});

loadTasks();
