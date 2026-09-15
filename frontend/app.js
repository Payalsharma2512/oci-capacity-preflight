const API_BASE = window.location.port === "8080" ? "http://localhost:8000" : "";
const DEMO_MODE = new URLSearchParams(window.location.search).get("demo");

const result = document.querySelector("#result");
const runButton = document.querySelector("#run");
const serviceSelect = document.querySelector("#service");
const limitSelect = document.querySelector("#limit");
const capabilityRows = document.querySelector("#capabilityRows");
const capabilityMessage = document.querySelector("#capabilityMessage");
const decisionMetric = document.querySelector("#decisionMetric");
const availableMetric = document.querySelector("#availableMetric");
const requestedMetric = document.querySelector("#requestedMetric");
const targetRegionMetric = document.querySelector("#targetRegionMetric");
const quotaRegionMetric = document.querySelector("#quotaRegionMetric");
const statusLabel = document.querySelector("#statusLabel");
const regionLabel = document.querySelector("#regionLabel");
const adLabel = document.querySelector("#adLabel");
const compartmentLabel = document.querySelector("#compartmentLabel");
const serviceLabel = document.querySelector("#serviceLabel");
const limitLabel = document.querySelector("#limitLabel");
const requestedLabel = document.querySelector("#requestedLabel");

let capabilities = [];

function field(id) {
  return document.querySelector(`#${id}`).value.trim();
}

function formatValue(value) {
  return value === null || value === undefined ? "-" : value;
}

function regionShortName(region) {
  if (!region) {
    return "-";
  }
  const parts = region.split("-");
  return parts.length >= 2 ? parts[1].toUpperCase() : region.toUpperCase();
}

function selectedCapability() {
  return capabilities.find((item) => item.service === field("service") && item.limit_name === field("limit"));
}

function unitLabel(unit) {
  return unit || selectedCapability()?.unit || "units";
}

function capabilityMessageFor(capability) {
  if (!capability) {
    return "<strong>No capability selected</strong><span>Select a service and limit.</span>";
  }
  if (capability.capability === "FULL_PREFLIGHT") {
    return "<strong>Full Preflight</strong><span>This limit has a verified adapter and can evaluate planned operations.</span>";
  }
  if (capability.capability === "MONITOR_ONLY") {
    return "<strong>Monitoring Only</strong><span>This limit can currently be monitored, but this prototype does not yet translate the planned deployment into a reliable capacity request.</span>";
  }
  if (capability.capability === "DISCOVERY_ONLY") {
    return "<strong>Discovery Only</strong><span>This limit is visible from OCI discovery, but current usage or availability is not reliable enough for preflight.</span>";
  }
  return "<strong>Unsupported</strong><span>Required OCI information is unavailable or this integration is not implemented.</span>";
}

function syncFormSummary() {
  const capability = selectedCapability();
  targetRegionMetric.textContent = regionShortName(field("region"));
  quotaRegionMetric.textContent = regionShortName(field("quotaRegion"));
  regionLabel.textContent = field("region") || "-";
  adLabel.textContent = field("availabilityDomain") || "-";
  requestedMetric.textContent = field("requested") || "-";
  serviceLabel.textContent = field("service") || "-";
  limitLabel.textContent = field("limit") || "-";
  requestedLabel.childNodes[0].nodeValue = `Requested ${unitLabel(capability?.unit)} `;
  runButton.disabled = capability?.capability !== "FULL_PREFLIGHT";
  capabilityMessage.innerHTML = capabilityMessageFor(capability);
}

function classifyUnknown(reasons) {
  const text = reasons.join(" ").toLowerCase();
  if (text.includes("no full_preflight adapter") || text.includes("not full_preflight")) {
    return {
      title: "Unable To Validate",
      summary: "This service is discoverable, but it does not have a verified preflight adapter yet.",
      nextAction: "Use the capability matrix to find FULL_PREFLIGHT limits. Do not treat this as a PASS.",
    };
  }
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
      nextAction: "Use the full AD name for the selected region.",
    };
  }
  return {
    title: "Unable To Validate",
    summary: "The app could not fully evaluate the requested capacity.",
    nextAction: "Review the details below, correct the input or access issue, and run the check again.",
  };
}

function displayDecision(decision, reasons) {
  return decision === "UNKNOWN" ? classifyUnknown(reasons).title : decision;
}

function renderCapabilityRows() {
  capabilityRows.innerHTML = capabilities.map((item) => `
    <tr>
      <td>${item.service}</td>
      <td>${item.limit_name}</td>
      <td>${formatValue(item.scope_type)}</td>
      <td>${formatValue(item.available)}</td>
      <td><span class="badge ${item.capability.toLowerCase()}">${item.capability}</span></td>
    </tr>
  `).join("");
}

function populateServices() {
  const services = [...new Set(capabilities.map((item) => item.service))].sort();
  serviceSelect.innerHTML = services.map((service) => `<option value="${service}">${service}</option>`).join("");
  if (services.includes("compute")) {
    serviceSelect.value = "compute";
  }
  populateLimits();
}

function populateLimits() {
  const serviceLimits = capabilities.filter((item) => item.service === field("service"));
  limitSelect.innerHTML = serviceLimits.map((item) => `<option value="${item.limit_name}">${item.limit_name} (${item.capability})</option>`).join("");
  const full = serviceLimits.find((item) => item.capability === "FULL_PREFLIGHT");
  if (full) {
    limitSelect.value = full.limit_name;
  }
  syncFormSummary();
}

function renderResult(data) {
  const decision = data.decision || "UNKNOWN";
  const className = decision.toLowerCase();
  const checks = data.checks || [];
  const reasons = data.unknown_reasons || [];
  const recommendations = data.recommendations || [];
  const firstCheck = checks[0];
  const unit = firstCheck?.unit || firstCheck?.metric || unitLabel();
  const requested = Object.values(data.operation?.requested_delta || {})[0] ?? field("requested");
  const unknownState = decision === "UNKNOWN" ? classifyUnknown(reasons) : null;
  const headline = displayDecision(decision, reasons);

  decisionMetric.textContent = headline;
  availableMetric.textContent = formatValue(data.effective_available_capacity);
  requestedMetric.textContent = requested;
  targetRegionMetric.textContent = regionShortName(data.operation?.region || field("region"));
  quotaRegionMetric.textContent = regionShortName(field("quotaRegion"));
  statusLabel.textContent = headline;
  regionLabel.textContent = data.operation?.region || field("region") || "-";
  adLabel.textContent = data.operation?.availability_domain || field("availabilityDomain") || "-";
  compartmentLabel.textContent = data.operation?.compartment_name || "Production";

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
      <dt>Available</dt><dd>${formatValue(data.effective_available_capacity)} ${unit}</dd>
      <dt>Blocking</dt><dd>${blocking}</dd>
      <dt>Requested</dt><dd>${requested} ${unit}</dd>
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
  const requested = kind === "block" ? 500 : 20;
  return {
    confidence: kind === "validate" ? "LOW" : "HIGH",
    advisory: true,
    operation: {
      service: "compute",
      resource_type: "instance",
      region: "us-ashburn-1",
      availability_domain: "Example-AD-A",
      compartment_id: "Example Compartment",
      compartment_name: "Production",
      requested_delta: { ocpus: requested },
    },
    evaluated_at: new Date().toISOString(),
    recommendations: kind === "block" ? [{ action: "REQUEST_LIMIT_INCREASE", reason: "Reduce requested capacity, select another region, or request a service limit increase." }] : [],
    unknown_reasons: kind === "validate" ? ["Invalid parameter availabilityDomain"] : [],
    decision: kind === "block" ? "BLOCK" : kind === "validate" ? "UNKNOWN" : "PASS",
    effective_available_capacity: kind === "validate" ? null : 295,
    primary_blocking_constraint: kind === "block" ? "SERVICE_LIMIT" : null,
    checks: kind === "validate" ? [] : [{
      constraint_type: "SERVICE_LIMIT",
      service: "compute",
      limit_name: "standard-e4-core-count",
      scope: "us-ashburn-1",
      metric: "ocpus",
      unit: "ocpus",
      current: 5,
      maximum: 300,
      available: 295,
      requested_delta: requested,
      projected: 5 + requested,
      status: kind === "block" ? "WOULD_EXCEED" : "OK",
      shortfall: kind === "block" ? 205 : null,
    }],
  };
}

async function loadCapabilities() {
  if (DEMO_MODE) {
    capabilities = [
      { service: "compute", service_description: "Compute", limit_name: "standard-e4-core-count", scope_type: "REGION", available: 295, capability: "FULL_PREFLIGHT", unit: "ocpus" },
      { service: "block-storage", service_description: "Block Storage", limit_name: "discovered-from-oci", scope_type: "REGION", available: "-", capability: "DISCOVERY_ONLY", unit: null },
      { service: "network-load-balancer", service_description: "Network Load Balancer", limit_name: "discovered-from-oci", scope_type: "REGION", available: "-", capability: "DISCOVERY_ONLY", unit: null },
    ];
  } else {
    const params = new URLSearchParams();
    if (field("compartment")) {
      params.set("compartment_id", field("compartment"));
    }
    if (field("availabilityDomain")) {
      params.set("availability_domain", field("availabilityDomain"));
    }
    const response = await fetch(`${API_BASE}/capacity?${params.toString()}`);
    const data = await response.json();
    capabilities = data.capacity || [];
  }
  renderCapabilityRows();
  populateServices();
}

async function runPreflight() {
  syncFormSummary();
  const capability = selectedCapability();
  if (capability?.capability !== "FULL_PREFLIGHT") {
    renderResult({
      decision: "UNKNOWN",
      confidence: "LOW",
      advisory: true,
      operation: {
        service: field("service"),
        resource_type: field("resource"),
        region: field("region"),
        availability_domain: field("availabilityDomain"),
        compartment_id: field("compartment"),
        compartment_name: "Production",
        requested_delta: {},
      },
      effective_available_capacity: null,
      primary_blocking_constraint: null,
      checks: [],
      recommendations: [{ action: "SELECT_FULL_PREFLIGHT_LIMIT", reason: "This selected limit is not yet supported for operation-level preflight." }],
      unknown_reasons: ["Selected service or limit is not FULL_PREFLIGHT."],
      evaluated_at: new Date().toISOString(),
    });
    return;
  }

  runButton.disabled = true;
  result.className = "";
  result.innerHTML = "<h2>Running</h2><p>Checking OCI capacity and quotas...</p>";

  if (DEMO_MODE) {
    renderResult(demoResult(DEMO_MODE));
    runButton.disabled = false;
    return;
  }

  const payload = {
    quota_region: field("quotaRegion"),
    operation: {
      service: field("service"),
      resource_type: field("resource"),
      region: field("region"),
      availability_domain: field("availabilityDomain"),
      compartment_id: field("compartment"),
      compartment_name: "Production",
      requested: {
        ocpus: Number(field("requested")),
      },
    },
  };

  try {
    const response = await fetch(`${API_BASE}/preflight`, {
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
    result.innerHTML = `<h2>Cannot Reach Preflight API</h2><p>The browser could not call the backend service.</p><div class="notice"><strong>Next action</strong><span>Make sure the backend is running and your SSH tunnel points to ${API_BASE || "/"}.</span></div><details><summary>Technical Details</summary><ul><li>${error.message}</li></ul></details>`;
  } finally {
    runButton.disabled = false;
    syncFormSummary();
  }
}

serviceSelect.addEventListener("change", populateLimits);
limitSelect.addEventListener("change", syncFormSummary);
runButton.addEventListener("click", runPreflight);
["region", "quotaRegion", "availabilityDomain", "requested", "compartment"].forEach((id) => {
  document.querySelector(`#${id}`).addEventListener("input", syncFormSummary);
});

loadCapabilities()
  .then(() => runPreflight())
  .catch((error) => {
    result.className = "unknown";
    result.innerHTML = `<h2>Cannot Load OCI Discovery</h2><p>The browser could not load the service capability matrix.</p><details><summary>Technical Details</summary><ul><li>${error.message}</li></ul></details>`;
  });
