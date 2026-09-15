const API_URL = window.location.port === "8080" ? "http://localhost:8000/preflight" : "/preflight";
const DEMO_MODE = new URLSearchParams(window.location.search).get("demo");

const result = document.querySelector("#result");
const runButton = document.querySelector("#run");
const decisionMetric = document.querySelector("#decisionMetric");
const availableMetric = document.querySelector("#availableMetric");
const requestedMetric = document.querySelector("#requestedMetric");
const statusLabel = document.querySelector("#statusLabel");
const compartmentLabel = document.querySelector("#compartmentLabel");

function field(id) {
  return document.querySelector(`#${id}`).value.trim();
}

function setStatus(text, className = "") {
  result.className = className;
  result.innerHTML = text;
  statusLabel.textContent = className ? className.toUpperCase() : "Running";
}

function formatValue(value) {
  return value === null || value === undefined ? "-" : value;
}

function classifyUnknown(reasons) {
  const text = reasons.join(" ").toLowerCase();
  if (text.includes("notauthenticated") || text.includes("401")) {
    return {
      title: "Authentication Failed",
      summary: "The app could not authenticate to OCI for this check.",
      nextAction: "Confirm the service is running on the OCI instance with Instance Principal enabled, then rerun the validation command.",
    };
  }
  if (text.includes("notauthorizedornotfound") || text.includes("not authorized") || text.includes("authorization failed")) {
    return {
      title: "Missing OCI Permission",
      summary: "The instance principal can reach OCI, but it is not authorized to read one of the required APIs.",
      nextAction: "Confirm the dynamic group policy allows inspect limits and inspect quotas in the tenancy.",
    };
  }
  if (text.includes("home region") || text.includes("quota operations")) {
    return {
      title: "Quota Region Mismatch",
      summary: "OCI quota APIs must be called in the tenancy home region.",
      nextAction: "Set Quota Region to the tenancy home region and run the check again.",
    };
  }
  if (text.includes("availabilitydomain") || text.includes("availability domain") || text.includes("invalid parameter")) {
    return {
      title: "Invalid Availability Domain",
      summary: "OCI rejected the availability domain for this region.",
      nextAction: "Use the full AD name for the selected region, for example <VALID_AD>.",
    };
  }
  return {
    title: "Unable To Validate Capacity",
    summary: "The app could not fully evaluate the requested capacity.",
    nextAction: "Review the details below, correct the input or access issue, and run the check again.",
  };
}

function displayDecision(decision, reasons) {
  if (decision === "UNKNOWN") {
    return classifyUnknown(reasons).title;
  }
  return decision;
}

function renderResult(data) {
  const decision = data.decision || "UNKNOWN";
  const className = decision.toLowerCase();
  const checks = data.checks || [];
  const reasons = data.unknown_reasons || [];
  const recommendations = data.recommendations || [];
  const requested = data.operation?.requested_delta?.ocpus ?? field("ocpus");
  const unknownState = decision === "UNKNOWN" ? classifyUnknown(reasons) : null;
  const headline = displayDecision(decision, reasons);

  decisionMetric.textContent = headline;
  availableMetric.textContent = formatValue(data.effective_available_capacity);
  requestedMetric.textContent = requested;
  statusLabel.textContent = headline;
  compartmentLabel.textContent = "Production";

  const checkRows = checks.map((check) => `
    <tr>
      <td>${check.constraint_type}</td>
      <td>${check.limit_name}</td>
      <td>${check.status}</td>
      <td>${formatValue(check.current)}</td>
      <td>${formatValue(check.maximum)}</td>
      <td>${formatValue(check.available)}</td>
      <td>${formatValue(check.requested_delta)}</td>
      <td>${formatValue(check.projected)}</td>
    </tr>
  `).join("");

  const reasonList = reasons.map((reason) => `<li>${reason}</li>`).join("");
  const actionList = recommendations.map((item) => `<li>${item.action}: ${item.reason}</li>`).join("");
  const blocking = data.primary_blocking_constraint || "-";

  result.className = className;
  result.innerHTML = `
    <h2>${headline}</h2>
    <p>${decision === "PASS" ? "No known capacity constraint detected." : decision === "BLOCK" ? "This request is expected to exceed an OCI capacity constraint." : unknownState.summary}</p>
    <dl>
      <dt>Raw Decision</dt><dd>${decision}</dd>
      <dt>Available</dt><dd>${formatValue(data.effective_available_capacity)} OCPUs</dd>
      <dt>Blocking</dt><dd>${blocking}</dd>
      <dt>Requested</dt><dd>${requested} OCPUs</dd>
      <dt>Evaluated</dt><dd>${new Date(data.evaluated_at).toLocaleString()}</dd>
      <dt>Advisory</dt><dd>${data.advisory ? "true" : "false"}</dd>
    </dl>
    ${unknownState ? `<div class="notice"><strong>Next action</strong><span>${unknownState.nextAction}</span></div>` : ""}
    ${checkRows ? `<table><thead><tr><th>Type</th><th>Name</th><th>Status</th><th>Current Usage</th><th>Limit/Quota</th><th>Available</th><th>Requested</th><th>Projected</th></tr></thead><tbody>${checkRows}</tbody></table>` : ""}
    ${reasonList ? `<details><summary>Technical Details</summary><ul>${reasonList}</ul></details>` : ""}
    ${actionList ? `<h3>Recommended Actions</h3><ul>${actionList}</ul>` : ""}
  `;
}

function demoResult(kind) {
  const base = {
    confidence: "HIGH",
    advisory: true,
    operation: {
      service: "compute",
      resource_type: "instance",
      region: "us-ashburn-1",
      availability_domain: "Example-AD-1",
      compartment_id: "Example Compartment",
      compartment_name: "Production",
      requested_delta: { ocpus: kind === "block" ? 500 : 20 },
    },
    evaluated_at: new Date().toISOString(),
    recommendations: [],
    unknown_reasons: [],
  };

  if (kind === "block") {
    return {
      ...base,
      decision: "BLOCK",
      effective_available_capacity: 295,
      primary_blocking_constraint: "SERVICE_LIMIT",
      checks: [{
        constraint_type: "SERVICE_LIMIT",
        service: "compute",
        limit_name: "standard-e4-core-count",
        scope: "us-ashburn-1",
        metric: "ocpus",
        current: 5,
        maximum: 300,
        available: 295,
        requested_delta: 500,
        projected: 505,
        status: "WOULD_EXCEED",
        shortfall: 205,
      }],
      recommendations: [{ action: "REQUEST_LIMIT_INCREASE", reason: "Reduce requested capacity, select another region, or request a service limit increase." }],
    };
  }

  if (kind === "validate") {
    return {
      ...base,
      decision: "UNKNOWN",
      confidence: "LOW",
      effective_available_capacity: null,
      primary_blocking_constraint: null,
      checks: [{
        constraint_type: "SERVICE_LIMIT",
        service: "compute",
        limit_name: "standard-e4-core-count",
        scope: "us-ashburn-1",
        metric: "ocpus",
        current: null,
        maximum: null,
        available: null,
        requested_delta: 20,
        projected: null,
        status: "UNKNOWN",
        reason: "Invalid parameter availabilityDomain",
      }],
      unknown_reasons: ["Invalid parameter availabilityDomain"],
    };
  }

  return {
    ...base,
    decision: "PASS",
    effective_available_capacity: 295,
    primary_blocking_constraint: null,
    checks: [{
      constraint_type: "SERVICE_LIMIT",
      service: "compute",
      limit_name: "standard-e4-core-count",
      scope: "us-ashburn-1",
      metric: "ocpus",
      current: 5,
      maximum: 300,
      available: 295,
      requested_delta: 20,
      projected: 25,
      status: "OK",
    }],
  };
}

async function runPreflight() {
  runButton.disabled = true;
  setStatus("<h2>Running</h2><p>Checking OCI capacity and quotas...</p>");

  if (DEMO_MODE) {
    renderResult(demoResult(DEMO_MODE));
    runButton.disabled = false;
    return;
  }

  const payload = {
    quota_region: field("quotaRegion"),
    operation: {
      service: field("service").toLowerCase(),
      resource_type: field("resource").toLowerCase(),
      region: field("region"),
      availability_domain: field("availabilityDomain"),
      compartment_id: field("compartment"),
      compartment_name: "Production",
      requested_delta: {
        ocpus: Number(field("ocpus")),
      },
    },
  };

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(`API returned HTTP ${response.status}`);
    }
    renderResult(await response.json());
  } catch (error) {
    decisionMetric.textContent = "ERROR";
    availableMetric.textContent = "-";
    statusLabel.textContent = "Error";
    result.className = "unknown";
    result.innerHTML = `<h2>Cannot Reach Preflight API</h2><p>The browser could not call the backend service.</p><div class="notice"><strong>Next action</strong><span>Make sure the backend is running and your SSH tunnel points to ${API_URL}.</span></div><details><summary>Technical Details</summary><ul><li>${error.message}</li></ul></details>`;
  } finally {
    runButton.disabled = false;
  }
}

runButton.addEventListener("click", runPreflight);
runPreflight();
