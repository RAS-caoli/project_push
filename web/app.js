const STORAGE_KEYS = {
  activeAccount: "github-push-tool-active-account",
  currentPath: "github-push-tool-current-path",
  remoteUrl: "github-push-tool-remote-url",
  commitMessage: "github-push-tool-commit-message",
};

const elements = {
  currentPath: document.querySelector("#currentPath"),
  accountSwitcher: document.querySelector("#accountSwitcher"),
  nameInput: document.querySelector("#nameInput"),
  emailInput: document.querySelector("#emailInput"),
  patInput: document.querySelector("#patInput"),
  commitMessageInput: document.querySelector("#commitMessageInput"),
  remoteUrlInput: document.querySelector("#remoteUrlInput"),
  saveAccountBtn: document.querySelector("#saveAccountBtn"),
  deleteAccountBtn: document.querySelector("#deleteAccountBtn"),
  selectPathBtn: document.querySelector("#selectPathBtn"),
  clearLogBtn: document.querySelector("#clearLogBtn"),
  logOutput: document.querySelector("#logOutput"),
  repoState: document.querySelector("#repoState"),
  branchState: document.querySelector("#branchState"),
  remoteState: document.querySelector("#remoteState"),
  actionButtons: Array.from(document.querySelectorAll("[data-action]")),
};

let accounts = [];
let currentPath = localStorage.getItem(STORAGE_KEYS.currentPath) || "";

function getActiveAccountId() {
  return localStorage.getItem(STORAGE_KEYS.activeAccount) || "";
}

function setActiveAccountId(id) {
  localStorage.setItem(STORAGE_KEYS.activeAccount, id);
}

function fillAccountForm(accountId) {
  const account = accounts.find((item) => item.id === accountId);
  if (!account) {
    elements.nameInput.value = "";
    elements.emailInput.value = "";
    elements.patInput.value = "";
    return;
  }

  elements.nameInput.value = account.name;
  elements.emailInput.value = account.email;
  elements.patInput.value = account.pat;
}

function renderAccountOptions() {
  const activeId = getActiveAccountId();
  const options = ['<option value="">请选择账号</option>'];

  for (const account of accounts) {
    options.push(
      `<option value="${escapeHtml(account.id)}" ${account.id === activeId ? "selected" : ""}>${escapeHtml(
        `${account.name} (${account.email})`
      )}</option>`
    );
  }

  elements.accountSwitcher.innerHTML = options.join("");
  if (activeId) {
    fillAccountForm(activeId);
  }
}

function getCurrentAccountFromForm() {
  return {
    name: elements.nameInput.value.trim(),
    email: elements.emailInput.value.trim(),
    pat: elements.patInput.value.trim(),
  };
}

function getSelectedAccount() {
  const accountId = elements.accountSwitcher.value;
  const account = accounts.find((item) => item.id === accountId);
  return account || getCurrentAccountFromForm();
}

function setCurrentPath(path) {
  currentPath = path || "";
  elements.currentPath.textContent = currentPath || "未选择项目路径";
  localStorage.setItem(STORAGE_KEYS.currentPath, currentPath);
}

function appendLog(message, type = "info") {
  const time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  const prefix = type === "error" ? "[错误]" : type === "success" ? "[成功]" : "[信息]";
  const currentText = elements.logOutput.textContent.trim();
  const nextBlock = `${prefix} ${time}\n${message}`.trim();
  elements.logOutput.textContent = currentText && currentText !== "等待操作..."
    ? `${nextBlock}\n\n${currentText}`
    : nextBlock;
}

function updateSummary(summary = {}) {
  elements.repoState.textContent = summary.isGitRepo ? "是" : "否";
  elements.branchState.textContent = summary.branch || "-";
  elements.remoteState.textContent = summary.remoteUrl || "-";
  if (summary.projectPath) {
    setCurrentPath(summary.projectPath);
  }
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return response.json();
}

async function loadAccounts() {
  const active = encodeURIComponent(getActiveAccountId());
  const response = await fetch(`/api/accounts?active=${active}`);
  const data = await response.json();
  if (!data.ok) {
    throw new Error(data.message || "账号加载失败。");
  }

  accounts = Array.isArray(data.accounts) ? data.accounts : [];
  const activeId = getActiveAccountId();
  if (activeId && !accounts.some((item) => item.id === activeId)) {
    setActiveAccountId("");
  }
  renderAccountOptions();
  return data;
}

async function saveAccount() {
  const account = getCurrentAccountFromForm();
  try {
    const data = await postJson("/api/accounts/save", account);
    if (!data.ok) {
      appendLog(data.message || "账号保存失败。", "error");
      return;
    }

    accounts = Array.isArray(data.accounts) ? data.accounts : [];
    setActiveAccountId(data.account?.id || account.email.trim().toLowerCase());
    renderAccountOptions();
    appendLog(`${data.message}\n${data.storagePath}`, "success");
  } catch (error) {
    appendLog(error.message || "账号保存失败。", "error");
  }
}

async function deleteCurrentAccount() {
  const accountId = elements.accountSwitcher.value;
  if (!accountId) {
    appendLog("当前没有选中的账号可删除。", "error");
    return;
  }

  try {
    const data = await postJson("/api/accounts/delete", { id: accountId });
    if (!data.ok) {
      appendLog(data.message || "删除账号失败。", "error");
      return;
    }

    accounts = Array.isArray(data.accounts) ? data.accounts : [];
    setActiveAccountId("");
    renderAccountOptions();
    fillAccountForm("");
    appendLog(`${data.message}\n${data.storagePath}`, "success");
  } catch (error) {
    appendLog(error.message || "删除账号失败。", "error");
  }
}

async function selectProjectPath() {
  elements.selectPathBtn.disabled = true;
  try {
    const data = await postJson("/api/select-path", { currentPath });
    if (!data.ok) {
      appendLog(data.message || "项目路径选择失败。", "error");
      return;
    }

    updateSummary(data.summary || {});
    appendLog(`${data.message}\n${data.projectPath}`, "success");
  } catch (error) {
    appendLog(error.message || "项目路径选择失败。", "error");
  } finally {
    elements.selectPathBtn.disabled = false;
  }
}

async function executeAction(action) {
  if (!currentPath) {
    appendLog("请先选择项目路径。", "error");
    return;
  }

  const payload = {
    action,
    projectPath: currentPath,
    account: getSelectedAccount(),
    remoteUrl: elements.remoteUrlInput.value.trim(),
    commitMessage: elements.commitMessageInput.value.trim(),
  };

  elements.actionButtons.forEach((button) => {
    button.disabled = true;
  });

  try {
    const data = await postJson("/api/git-action", payload);
    if (!data.ok) {
      appendLog(data.message || "操作执行失败。", "error");
      return;
    }

    const joinedLogs = Array.isArray(data.logs) ? data.logs.join("\n\n") : data.message;
    appendLog(joinedLogs || data.message || "操作执行成功。", "success");
    updateSummary(data.summary || {});
  } catch (error) {
    appendLog(error.message || "请求失败。", "error");
  } finally {
    elements.actionButtons.forEach((button) => {
      button.disabled = false;
    });
  }
}

function bindEvents() {
  elements.saveAccountBtn.addEventListener("click", saveAccount);
  elements.deleteAccountBtn.addEventListener("click", deleteCurrentAccount);
  elements.selectPathBtn.addEventListener("click", selectProjectPath);
  elements.clearLogBtn.addEventListener("click", () => {
    elements.logOutput.textContent = "等待操作...";
  });

  elements.accountSwitcher.addEventListener("change", (event) => {
    const accountId = event.target.value;
    setActiveAccountId(accountId);
    fillAccountForm(accountId);
    if (accountId) {
      appendLog("已切换账号。", "info");
    }
  });

  elements.actionButtons.forEach((button) => {
    button.addEventListener("click", () => executeAction(button.dataset.action));
  });

  elements.remoteUrlInput.addEventListener("input", () => {
    localStorage.setItem(STORAGE_KEYS.remoteUrl, elements.remoteUrlInput.value);
  });

  elements.commitMessageInput.addEventListener("input", () => {
    localStorage.setItem(STORAGE_KEYS.commitMessage, elements.commitMessageInput.value);
  });
}

async function hydrate() {
  setCurrentPath(currentPath);
  elements.remoteUrlInput.value = localStorage.getItem(STORAGE_KEYS.remoteUrl) || "";
  elements.commitMessageInput.value = localStorage.getItem(STORAGE_KEYS.commitMessage) || "first commit";
  await loadAccounts();
}

bindEvents();
hydrate().catch((error) => {
  appendLog(error.message || "初始化失败。", "error");
});
