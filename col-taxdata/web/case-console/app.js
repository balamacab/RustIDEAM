import { buildRequest, buildViewModels } from "./app-core.mjs";

const form = document.querySelector("#case-form");
const problemText = document.querySelector("#problem-text");
const asOfDate = document.querySelector("#as-of-date");
const clientReference = document.querySelector("#client-reference");
const callerMetadata = document.querySelector("#caller-metadata");
const fixtureSelect = document.querySelector("#fixture-select");
const loadFixtureButton = document.querySelector("#load-fixture");
const submitButton = document.querySelector("#submit-case");
const requestState = document.querySelector("#request-state");
const elapsed = document.querySelector("#elapsed");
const contractBadge = document.querySelector("#contract-badge");
const viewPanels = new Map(
  [...document.querySelectorAll("[data-view-panel]")].map((node) => [
    node.dataset.viewPanel,
    node,
  ]),
);

let contract;
let fixtures = [];
let timerId = null;
let startedAt = 0;

function setText(node, value) {
  node.textContent = value;
}

function showState(message, kind = "idle") {
  requestState.dataset.kind = kind;
  setText(requestState, message);
}

function renderJson(panel, value, emptyMessage) {
  panel.replaceChildren();
  if (
    value === null ||
    value === undefined ||
    (Array.isArray(value) && value.length === 0)
  ) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = emptyMessage;
    panel.append(empty);
    return;
  }
  const pre = document.createElement("pre");
  pre.className = "json";
  pre.textContent = JSON.stringify(value, null, 2);
  panel.append(pre);
}

function renderViews(payload) {
  const views = buildViewModels(payload);
  renderJson(viewPanels.get("result"), views.result, "No result.");
  renderJson(viewPanels.get("intake"), views.intake, "No intake data exposed.");
  renderJson(viewPanels.get("research"), views.research, "No research data exposed.");
  renderJson(viewPanels.get("evidence"), views.evidence, "No public evidence data exposed.");
  renderJson(
    viewPanels.get("evaluations"),
    views.evaluations,
    "No deterministic evaluations or calculations exposed.",
  );
  renderJson(
    viewPanels.get("unresolved"),
    views.unresolved,
    "No unresolved items exposed.",
  );
  renderJson(
    viewPanels.get("diagnostics"),
    views.diagnostics,
    "No public diagnostics exposed.",
  );
  renderJson(viewPanels.get("raw"), views.raw, "No response.");
}

function startElapsed() {
  startedAt = performance.now();
  setText(elapsed, "0.0 s");
  timerId = window.setInterval(() => {
    setText(elapsed, `${((performance.now() - startedAt) / 1000).toFixed(1)} s`);
  }, 100);
}

function stopElapsed() {
  if (timerId !== null) {
    window.clearInterval(timerId);
    timerId = null;
  }
  setText(elapsed, `${((performance.now() - startedAt) / 1000).toFixed(1)} s`);
}

function activateTab(name) {
  for (const button of document.querySelectorAll("[data-view]")) {
    const selected = button.dataset.view === name;
    button.setAttribute("aria-selected", selected ? "true" : "false");
  }
  for (const [panelName, panel] of viewPanels) {
    panel.hidden = panelName !== name;
  }
}

for (const button of document.querySelectorAll("[data-view]")) {
  button.addEventListener("click", () => activateTab(button.dataset.view));
}

loadFixtureButton.addEventListener("click", () => {
  const fixture = fixtures.find((item) => item.id === fixtureSelect.value);
  if (!fixture) return;
  const request = fixture.request;
  problemText.value = request.problem_text ?? "";
  asOfDate.value = request.as_of_date ?? "";
  clientReference.value = request.client_reference ?? "";
  callerMetadata.value = Object.prototype.hasOwnProperty.call(request, "caller_metadata")
    ? JSON.stringify(request.caller_metadata, null, 2)
    : "";
  showState(`Loaded ${fixture.label}. Review before submitting.`, "idle");
  problemText.focus();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  let request;
  try {
    request = buildRequest(
      problemText.value,
      asOfDate.value,
      clientReference.value,
      callerMetadata.value,
    );
  } catch (error) {
    showState(error.message, "error");
    return;
  }

  submitButton.disabled = true;
  showState("CASE request running…", "running");
  startElapsed();

  try {
    const response = await fetch(contract.proxy_path, {
      method: contract.method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      credentials: "omit",
      cache: "no-store",
    });

    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.includes("application/json")) {
      throw new Error(
        response.ok
          ? "CASE returned a non-JSON response."
          : `CASE backend/proxy unavailable (HTTP ${response.status}).`,
      );
    }

    const payload = await response.json();
    renderViews(payload);
    activateTab("result");

    if (response.ok) {
      showState("Public CASE response received.", "success");
    } else {
      const code =
        payload &&
        payload.error &&
        typeof payload.error.code === "string"
          ? payload.error.code
          : `HTTP ${response.status}`;
      showState(`CASE request failed: ${code}`, "error");
    }
  } catch (error) {
    renderViews({
      api_version: contract.api_version,
      error: {
        code: "CONSOLE_TRANSPORT_ERROR",
        message: error.message,
        retryable: true,
      },
    });
    activateTab("result");
    showState(error.message, "error");
  } finally {
    stopElapsed();
    submitButton.disabled = false;
  }
});

async function initialize() {
  try {
    const [contractResponse, fixtureResponse] = await Promise.all([
      fetch("./public-contract.json", { cache: "no-store" }),
      fetch("./fixtures/index.json", { cache: "no-store" }),
    ]);
    if (!contractResponse.ok || !fixtureResponse.ok) {
      throw new Error("Console contract resources could not be loaded.");
    }
    contract = await contractResponse.json();
    const fixtureDocument = await fixtureResponse.json();
    fixtures = fixtureDocument.fixtures ?? [];

    setText(contractBadge, `${contract.contract_name} · ${contract.api_version}`);
    fixtureSelect.replaceChildren();
    for (const fixture of fixtures) {
      const option = document.createElement("option");
      option.value = fixture.id;
      option.textContent = fixture.label;
      fixtureSelect.append(option);
    }
    loadFixtureButton.disabled = fixtures.length === 0;
    submitButton.disabled = false;
    showState("Ready. No request has been submitted.", "idle");
  } catch (error) {
    showState(error.message, "error");
  }
}

activateTab("result");
initialize();
