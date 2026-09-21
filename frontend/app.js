const API_BASE = window.location.port === "8080" ? "http://localhost:8000" : "";
const PAGE_PARAMS = new URLSearchParams(window.location.search);
const DEMO_MODE = PAGE_PARAMS.get("demo");
const FORM_STORAGE_PREFIX = "capacity-readiness-form";
const CAPACITY_ROW_RENDER_LIMIT = 200;

const els = {
  service: document.querySelector("#service"),
  operation: document.querySelector("#operation"),
  form: document.querySelector("#dynamicForm"),
  run: document.querySelector("#run"),
  result: document.querySelector("#result"),
  operationCapability: document.querySelector("#operationCapability"),
  capabilityRows: document.querySelector("#capabilityRows"),
  capacityRowStatus: document.querySelector("#capacityRowStatus"),
  decisionMetric: document.querySelector("#decisionMetric"),
  availableMetric: document.querySelector("#availableMetric"),
  requestedMetric: document.querySelector("#requestedMetric"),
  targetRegionMetric: document.querySelector("#targetRegionMetric"),
  serviceLabel: document.querySelector("#serviceLabel"),
  operationLabel: document.querySelector("#operationLabel"),
  modeBanner: document.querySelector("#modeBanner"),
  modeLabel: document.querySelector("#modeLabel"),
  modeContext: document.querySelector("#modeContext"),
  capabilityLabel: document.querySelector("#capabilityLabel"),
  scopeLabel: document.querySelector("#scopeLabel"),
  compartmentLabel: document.querySelector("#compartmentLabel"),
  statusLabel: document.querySelector("#statusLabel"),
  cacheStatus: document.querySelector("#cacheStatus"),
  servicesDiscovered: document.querySelector("#servicesDiscovered"),
  limitsDiscovered: document.querySelector("#limitsDiscovered"),
  fullCount: document.querySelector("#fullCount"),
  monitorCount: document.querySelector("#monitorCount"),
  discoveryCount: document.querySelector("#discoveryCount"),
  unsupportedCount: document.querySelector("#unsupportedCount"),
  criticalCount: document.querySelector("#criticalCount"),
  warningCount: document.querySelector("#warningCount"),
  watchCount: document.querySelector("#watchCount"),
  healthyCount: document.querySelector("#healthyCount"),
  unknownCount: document.querySelector("#unknownCount"),
  cacheAge: document.querySelector("#cacheAge"),
  cacheState: document.querySelector("#cacheState"),
  cacheRefreshed: document.querySelector("#cacheRefreshed"),
  cacheAgeDetail: document.querySelector("#cacheAgeDetail"),
  cacheStateDetail: document.querySelector("#cacheStateDetail"),
  refreshCapacity: document.querySelector("#refreshCapacity"),
  dataNotice: document.querySelector("#dataNotice"),
  coverageRows: document.querySelector("#coverageRows"),
};

let operationCatalog = [];
let capabilities = [];
let shapes = [];
let capacityMeta = {};
let runtimeStatus = {};
let shapeLoadTimer = null;

const capabilityRank = {
  FULL_PREFLIGHT: 4,
  MONITOR_ONLY: 3,
  DISCOVERY_ONLY: 2,
  UNSUPPORTED: 1,
};

function field(id) {
  return document.querySelector(`#field-${id}`)?.value.trim() || "";
}

function storageKey(service, operation, name) {
  return `${FORM_STORAGE_PREFIX}:${service || "global"}:${operation || "operation"}:${name}`;
}

function savedFieldValue(operation, item) {
  const service = selectedService()?.service;
  const operationName = operation?.operation;
  const scoped = localStorage.getItem(storageKey(service, operationName, item.name));
  if (scoped !== null) return scoped;
  const global = localStorage.getItem(storageKey("target", "default", item.name));
  if (global !== null && ["region", "compartment_id", "availability_domain"].includes(item.name)) return global;
  return item.default;
}

function saveFieldValue(operation, item) {
  const name = item.id.replace("field-", "");
  const value = item.value.trim();
  const service = selectedService()?.service;
  const operationName = operation?.operation;
  localStorage.setItem(storageKey(service, operationName, name), value);
  if (["region", "compartment_id", "availability_domain"].includes(name)) {
    localStorage.setItem(storageKey("target", "default", name), value);
  }
}

function selectedService() {
  return operationCatalog.find((item) => item.service === els.service.value);
}

function selectedOperation() {
  return selectedService()?.operations.find((item) => item.operation === els.operation.value);
}

function formatValue(value) {
  return value === null || value === undefined || value === "" ? "-" : value;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  })[char]);
}

function titleizeService(service) {
  return String(service || "").replaceAll("-", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function serviceId(item) {
  return String(item?.service || item?.name || item?.id || "").trim();
}

function serviceLabel(item) {
  const id = serviceId(item);
  return String(item?.display_name || item?.displayName || item?.description || item?.label || id || "Unnamed service").trim();
}

function renderServiceOptions(selectedValue = els.service.value) {
  els.service.innerHTML = operationCatalog
    .filter((item) => serviceId(item))
    .map((item) => {
      const id = serviceId(item);
      return `<option value="${escapeHtml(id)}">${escapeHtml(serviceLabel(item) || titleizeService(id))}</option>`;
    })
    .join("");
  if (selectedValue && operationCatalog.some((item) => serviceId(item) === selectedValue)) {
    els.service.value = selectedValue;
  }
}

function regionShortName(region) {
  if (!region) return "-";
  const parts = region.split("-");
  return parts.length >= 2 ? parts[1].toUpperCase() : region.toUpperCase();
}

function capabilityText(capability) {
  return (capability || "UNKNOWN").replace("_", " ");
}

function statusText(status) {
  if (!status) return "-";
  return status.charAt(0).toUpperCase() + status.slice(1).toLowerCase();
}

function maskedTenancy(value) {
  if (!value) return "not configured";
  if (value.startsWith("...")) return value;
  return value.length > 12 ? `...${value.slice(-12)}` : value;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || seconds === "") return "-";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.round(seconds % 60);
  return remaining ? `${minutes}m ${remaining}s` : `${minutes}m`;
}

function capabilityExplanation(operation) {
  if (!operation) return "";
  if (operation.capability === "FULL_PREFLIGHT") {
    return "This operation can be checked against verified service-limit and quota constraints.";
  }
  if (operation.capability === "MONITOR_ONLY") {
    return "This service/operation can currently be monitored, but this prototype cannot reliably translate your planned operation into capacity consumption.";
  }
  if (operation.capability === "DISCOVERY_ONLY") {
    return "We can discover this limit, but cannot currently evaluate usage or availability sufficiently for preflight.";
  }
  return "Required OCI information is unavailable or the integration is incomplete.";
}

function demoOperations() {
  return {
    services: [
      {
        service: "compute",
        display_name: "Compute",
        operations: [{
          operation: "create_instances",
          display_name: "Create Instances",
          capability: "FULL_PREFLIGHT",
          coverage: "shape-aware OCPU and memory service limits plus applicable compartment quota",
          monitor_only: ["physical host availability"],
          form: [
            { name: "region", label: "Region", type: "text", default: "us-ashburn-1", required: true },
            { name: "compartment_id", label: "Compartment OCID", type: "text", default: "<COMPARTMENT_OCID>", required: true },
            { name: "availability_domain", label: "Availability Domain", type: "text", default: "<VALID_AD>", required: true },
            { name: "shape", label: "Shape", type: "compute_shape", required: true },
            { name: "instance_count", label: "Number of instances", type: "number", default: 5, min: 1, required: true },
            { name: "ocpus_per_instance", label: "OCPUs per instance", type: "number", default: 4, min: 0, step: 0.1 },
            { name: "memory_gb_per_instance", label: "Memory per instance GB", type: "number", default: 32, min: 0, step: 0.1 },
          ],
        }],
      },
      {
        service: "block-storage",
        display_name: "Block Volume",
        operations: [{
          operation: "create_volumes",
          display_name: "Create Volumes",
          capability: "FULL_PREFLIGHT",
          coverage: "volume count and total storage GB",
          monitor_only: ["backup count", "replica storage unless requested"],
          form: [
            { name: "region", label: "Region", type: "text", default: "us-ashburn-1", required: true },
            { name: "compartment_id", label: "Compartment OCID", type: "text", default: "<COMPARTMENT_OCID>", required: true },
            { name: "availability_domain", label: "Availability Domain", type: "text", default: "<VALID_AD>", required: true },
            { name: "volume_count", label: "Number of volumes", type: "number", default: 5, min: 1, required: true },
            { name: "size_gb_each", label: "Size per volume GB", type: "number", default: 2048, min: 1, required: true },
          ],
        }],
      },
      {
        service: "network-load-balancer-api",
        display_name: "Network Load Balancer",
        operations: [{
          operation: "create_network_load_balancers",
          display_name: "Create Network Load Balancers",
          capability: "FULL_PREFLIGHT",
          coverage: "NLB count only",
          monitor_only: ["backend sets", "backends", "throughput", "connections"],
          form: [
            { name: "region", label: "Region", type: "text", default: "us-ashburn-1", required: true },
            { name: "compartment_id", label: "Compartment OCID", type: "text", default: "<COMPARTMENT_OCID>", required: true },
            { name: "nlb_count", label: "Number of NLBs", type: "number", default: 5, min: 1, required: true },
          ],
        },
        { operation: "backend_sets", display_name: "Backend Sets", capability: "MONITOR_ONLY", coverage: "Monitoring only", form: [] },
        { operation: "throughput_connections", display_name: "Throughput And Connections", capability: "MONITOR_ONLY", coverage: "Monitoring only", form: [] },
        { operation: "unmapped_discovered_limits", display_name: "Other Discovered Limits", capability: "DISCOVERY_ONLY", coverage: "Discovery only", form: [] }],
      },
    ],
  };
}

function demoCapacity() {
  const rows = [
    { service: "compute", limit_name: "standard-e5-core-count", scope_type: "AD", current_usage: 1, limit_value: 244, available: 243, risk_state: "HEALTHY", capability: "FULL_PREFLIGHT" },
    { service: "block-storage", limit_name: "total-storage-gb", scope_type: "AD", current_usage: 147, limit_value: 60372, available: 60225, risk_state: "HEALTHY", capability: "FULL_PREFLIGHT" },
    { service: "network-load-balancer-api", limit_name: "max-nlb-flexible-count", scope_type: "REGION", current_usage: 0, limit_value: 8, available: 8, risk_state: "HEALTHY", capability: "FULL_PREFLIGHT" },
    { service: "load-balancer", limit_name: "backend-sets-per-lb-count", scope_type: "REGION", current_usage: null, limit_value: 16, available: null, risk_state: "UNKNOWN", capability: "MONITOR_ONLY" },
  ];
  return {
    capacity: rows,
    summary: { services_discovered: 128, limits_discovered: 1032, capability_counts: { FULL_PREFLIGHT: 24, MONITOR_ONLY: 1008 } },
    cache: { status: "synthetic", age_seconds: 0, ttl_seconds: 300, last_refreshed: Date.now() / 1000 },
  };
}

async function loadRuntimeStatus() {
  if (DEMO_MODE) {
    runtimeStatus = { mode: "demo", tenancy_configured: false, region: "us-ashburn-1" };
    renderModeBanner();
    return;
  }
  try {
    runtimeStatus = await (await fetch(`${API_BASE}/health`)).json();
  } catch (_error) {
    runtimeStatus = { mode: "unknown", tenancy_configured: false };
  }
  renderModeBanner();
}

async function loadOperations() {
  const data = DEMO_MODE ? demoOperations() : await (await fetch(`${API_BASE}/operations`)).json();
  operationCatalog = (data.services || []).map((item) => ({ ...item, service: serviceId(item), display_name: serviceLabel(item) }));
  renderServiceOptions("");
  const requestedService = PAGE_PARAMS.get("service");
  if (requestedService && operationCatalog.some((item) => serviceId(item) === requestedService)) {
    els.service.value = requestedService;
  }
  syncOperations({ resetResult: false });
}

function mergeDiscoveredServicesIntoCatalog() {
  if (!capabilities.length) return;
  const catalogByService = new Map(operationCatalog.map((item) => [serviceId(item), item]).filter(([service]) => service));
  const rowsByService = new Map();
  for (const row of capabilities) {
    if (!row.service) continue;
    rowsByService.set(row.service, (rowsByService.get(row.service) || []).concat(row));
  }
  for (const [service, rows] of rowsByService.entries()) {
    if (catalogByService.has(service)) {
      const item = catalogByService.get(service);
      if (!item.operations.some((operation) => operation.operation === "check_discovered_limit")) {
        const generic = genericLimitOperation(service, rows);
        if (generic) item.operations.push(generic);
      }
      continue;
    }
    const capability = rows.reduce((best, row) => (capabilityRank[row.capability] || 0) > (capabilityRank[best] || 0) ? row.capability : best, "DISCOVERY_ONLY");
    const serviceDescription = rows.find((row) => row.service_description)?.service_description;
    const readableName = serviceDescription || titleizeService(service);
    const visibleLimitCount = rows.length;
    const availableRows = rows.filter((row) => row.resource_availability_supported).length;
    const operations = [{
      operation: "discovered_limits",
      display_name: "Discovered Limits",
      capability,
      coverage: `${visibleLimitCount} discovered limit${visibleLimitCount === 1 ? "" : "s"}; ${availableRows} with current usage or availability.`,
      monitor_only: ["operation-level preflight is not verified for this service"],
      form: [],
    }];
    const generic = genericLimitOperation(service, rows);
    if (generic) operations.unshift(generic);
    catalogByService.set(service, {
      service,
      display_name: readableName,
      operations,
    });
  }
  operationCatalog = [...catalogByService.values()].sort((a, b) => {
    const aFull = a.operations.some((item) => item.capability === "FULL_PREFLIGHT");
    const bFull = b.operations.some((item) => item.capability === "FULL_PREFLIGHT");
    if (aFull !== bFull) return aFull ? -1 : 1;
    return serviceLabel(a).localeCompare(serviceLabel(b));
  });
  const selected = els.service.value;
  renderServiceOptions(selected);
}

function genericLimitOperation(service, rows) {
  const availableRows = rows
    .filter((row) => row.resource_availability_supported && row.available !== null && row.available !== undefined && row.limit_name)
    .sort((a, b) => String(a.limit_name).localeCompare(String(b.limit_name)));
  if (!availableRows.length) return null;
  return {
    operation: "check_discovered_limit",
    display_name: "Check Discovered Limit",
    capability: "FULL_PREFLIGHT",
    coverage: `${availableRows.length} live limit${availableRows.length === 1 ? "" : "s"} with OCI usage/availability can be checked manually.`,
    monitor_only: ["operation-specific service semantics", "physical capacity placement", "non-limit prerequisites"],
    form: [
      { name: "region", label: "Region", type: "text", default: runtimeStatus.region || "us-ashburn-1", required: true },
      { name: "compartment_id", label: "Compartment OCID", type: "text", required: true },
      { name: "availability_domain", label: "Availability Domain", type: "text" },
      { name: "limit_name", label: "Limit", type: "limit_select", options: availableRows.map((row) => ({ value: row.limit_name, label: `${row.limit_name}${row.limit_description ? " - " + row.limit_description : ""}` })) },
      { name: "requested_units", label: "Requested units", type: "number", default: 1, min: 0, step: 1, required: true },
    ],
    generic_limit_check: true,
  };
}

function mergeServicesIntoCatalog(services) {
  if (!services?.length) return;
  const catalogByService = new Map(operationCatalog.map((item) => [serviceId(item), item]).filter(([service]) => service));
  for (const item of services) {
    const service = serviceId(item);
    if (!service || catalogByService.has(service)) continue;
    const readableName = serviceLabel(item) || titleizeService(service);
    catalogByService.set(service, {
      service,
      display_name: readableName,
      operations: [{
        operation: "discovered_limits",
        display_name: "Discovered Limits",
        capability: "DISCOVERY_ONLY",
        coverage: "Service discovered from OCI. Limit details load in the capacity inventory.",
        monitor_only: ["operation-level preflight is not verified for this service"],
        form: [],
      }],
    });
  }
  operationCatalog = [...catalogByService.values()].sort((a, b) => {
    const aFull = a.operations.some((operation) => operation.capability === "FULL_PREFLIGHT");
    const bFull = b.operations.some((operation) => operation.capability === "FULL_PREFLIGHT");
    if (aFull !== bFull) return aFull ? -1 : 1;
    return serviceLabel(a).localeCompare(serviceLabel(b));
  });
  const selected = els.service.value;
  renderServiceOptions(selected);
  syncOperations({ resetResult: false });
  renderCoverage();
}

async function loadDiscoveredServices() {
  if (DEMO_MODE) return;
  try {
    const data = await (await fetch(`${API_BASE}/services`)).json();
    mergeServicesIntoCatalog(data.services || []);
  } catch (_error) {
    // Capacity inventory still exposes discovered services if this lightweight call fails.
  }
}

function syncOperations({ resetResult = true } = {}) {
  const service = selectedService();
  els.operation.innerHTML = (service?.operations || []).map((item) => `<option value="${item.operation}">${item.display_name || item.operation}</option>`).join("");
  const requestedOperation = PAGE_PARAMS.get("operation");
  if (requestedOperation && (service?.operations || []).some((item) => item.operation === requestedOperation)) {
    els.operation.value = requestedOperation;
  }
  renderOperation({ resetResult });
}

function renderOperation({ resetResult = true } = {}) {
  const service = selectedService();
  const operation = selectedOperation();
  els.serviceLabel.textContent = service?.display_name || service?.service || "-";
  els.operationLabel.textContent = operation?.display_name || operation?.operation || "-";
  els.capabilityLabel.textContent = capabilityText(operation?.capability);
  els.scopeLabel.textContent = operation?.coverage || "-";
  els.run.disabled = operation?.capability !== "FULL_PREFLIGHT";
  els.operationCapability.innerHTML = `
    <strong>Capability: ${capabilityText(operation?.capability)}</strong>
    <span>${capabilityExplanation(operation)}</span>
    ${operation?.monitor_only?.length ? `<small>Not included in this preflight: ${operation.monitor_only.join(", ")}.</small>` : ""}
    ${selectedServiceInventory(service?.service)}
  `;
  renderForm(operation);
  syncSummary();
  if (resetResult) {
    resetPreflightResult("Operation changed. Run preflight to evaluate the selected request.");
  }
}

function selectedServiceInventory(serviceName) {
  if (!serviceName) return "";
  const rows = capabilities.filter((item) => item.service === serviceName);
  if (!rows.length) {
    return `<div class="selected-inventory"><strong>Live inventory</strong><p>Service discovery succeeded. Limit details are still loading from OCI; click Refresh inventory if this stays empty.</p></div>`;
  }
  const visibleRows = rows.slice(0, 8).map((item) => `
    <tr>
      <td><strong>${item.limit_name}</strong><br><small>${item.limit_description || "-"}</small></td>
      <td>${formatValue(item.current_usage)}</td>
      <td>${formatValue(item.limit_value)}</td>
      <td>${formatValue(item.available)}</td>
      <td>${formatValue(item.risk_state)}</td>
      <td><span class="badge ${item.capability.toLowerCase()}">${capabilityText(item.capability)}</span></td>
    </tr>
  `).join("");
  const hiddenCount = rows.length - Math.min(rows.length, 8);
  return `
    <div class="selected-inventory">
      <strong>Live inventory for ${serviceName}</strong>
      <table>
        <thead><tr><th>Limit</th><th>Usage</th><th>Limit</th><th>Available</th><th>Risk</th><th>Capability</th></tr></thead>
        <tbody>${visibleRows}</tbody>
      </table>
      ${hiddenCount > 0 ? `<small>${hiddenCount} more limit${hiddenCount === 1 ? "" : "s"} below in OCI Tenancy Capacity. Type ${serviceName} in the Service filter to see all.</small>` : ""}
    </div>
  `;
}

function renderForm(operation) {
  els.form.innerHTML = (operation?.form || []).map((field) => {
    if (field.type === "compute_shape") {
      return `<label>${field.label}<select id="field-${field.name}"><option value="">Enter target details to load shapes</option></select></label>`;
    }
    if (field.type === "limit_select") {
      const saved = savedFieldValue(operation, field);
      const options = (field.options || []).map((option) => `<option value="${escapeHtml(option.value)}"${saved === option.value ? " selected" : ""}>${escapeHtml(option.label || option.value)}</option>`).join("");
      return `<label>${field.label}<select id="field-${field.name}">${options}</select></label>`;
    }
    const step = field.step ? ` step="${field.step}"` : "";
    const min = field.min !== undefined ? ` min="${field.min}"` : "";
    const saved = savedFieldValue(operation, field);
    const value = saved !== undefined && saved !== null ? ` value="${escapeHtml(saved)}"` : "";
    return `<label>${field.label}<input id="field-${field.name}" type="${field.type === "number" ? "number" : "text"}"${value}${min}${step}></label>`;
  }).join("");
  if (operation?.form?.some((field) => field.type === "compute_shape")) {
    loadShapes().catch(() => populateShapes([]));
  }
  els.form.querySelectorAll("input,select").forEach((item) => {
    const handleFieldChange = () => {
      saveFieldValue(operation, item);
      syncSummary();
      resetPreflightResult("Inputs changed. Run preflight to evaluate the selected request.");
      if (operation?.form?.some((field) => field.type === "compute_shape") && ["field-region", "field-compartment_id", "field-availability_domain"].includes(item.id)) {
        scheduleShapeLoad();
      }
    };
    item.addEventListener("input", handleFieldChange);
    item.addEventListener("change", handleFieldChange);
  });
}

async function loadShapes() {
  if (DEMO_MODE) {
    populateShapes([
      { name: "VM.Standard.E5.Flex", is_flex: true },
      { name: "VM.Standard.E5.4", is_flex: false, ocpus: 4, memory_gb: 64 },
    ]);
    return;
  }
  const params = new URLSearchParams();
  const region = field("region");
  const compartmentId = field("compartment_id");
  if (!region || !compartmentId) {
    populateShapes([]);
    return;
  }
  params.set("region", region);
  params.set("compartment_id", compartmentId);
  if (field("availability_domain")) params.set("availability_domain", field("availability_domain"));
  const data = await (await fetch(`${API_BASE}/compute/shapes?${params.toString()}`)).json();
  populateShapes(data.shapes || []);
}

function scheduleShapeLoad() {
  clearTimeout(shapeLoadTimer);
  shapeLoadTimer = setTimeout(() => {
    loadShapes().catch(() => populateShapes([]));
  }, 400);
}

function populateShapes(items) {
  const seen = new Set();
  shapes = (items || []).filter((shape) => shape?.name && !seen.has(shape.name) && seen.add(shape.name));
  const select = document.querySelector("#field-shape");
  if (!select) return;
  const previous = select.value || savedFieldValue(selectedOperation(), { name: "shape" });
  if (!shapes.length) {
    select.innerHTML = '<option value="">No shapes loaded for this target</option>';
    syncSummary();
    return;
  }
  select.innerHTML = shapes.map((shape) => `<option value="${shape.name}">${shape.name}${shape.is_flex ? " (Flex)" : ""}</option>`).join("");
  if (previous && shapes.some((shape) => shape.name === previous)) {
    select.value = previous;
  }
  if (select.value) {
    saveFieldValue(selectedOperation(), select);
  }
  syncSummary();
}

function requestedSummary() {
  const operation = selectedOperation();
  if (!operation) return "-";
  if (operation.operation === "create_instances") {
    const count = Number(field("instance_count") || 0);
    const ocpus = Number(field("ocpus_per_instance") || 0);
    const memory = Number(field("memory_gb_per_instance") || 0);
    return `${count * ocpus || "-"} OCPUs, ${count * memory || "-"} GB`;
  }
  if (operation.operation === "create_volumes") {
    const count = Number(field("volume_count") || 0);
    const size = Number(field("size_gb_each") || 0);
    return `${count} volumes, ${count * size || "-"} GB`;
  }
  if (operation.operation === "create_network_load_balancers") {
    return `${field("nlb_count") || "-"} NLBs`;
  }
  if (operation.operation === "check_discovered_limit") {
    return `${field("requested_units") || "-"} units`;
  }
  return "-";
}

function syncSummary() {
  const service = selectedService();
  const operation = selectedOperation();
  const serviceRows = capabilities.filter((item) => item.service === service?.service);
  const availableRows = serviceRows.filter((item) => item.available !== null && item.available !== undefined);
  els.requestedMetric.textContent = operation?.capability === "FULL_PREFLIGHT" ? requestedSummary() : `${serviceRows.length || "-"} limits`;
  els.availableMetric.textContent = operation?.capability === "FULL_PREFLIGHT" ? els.availableMetric.textContent : `${availableRows.length || "-"} with availability`;
  els.targetRegionMetric.textContent = regionShortName(field("region"));
  els.compartmentLabel.textContent = field("compartment_id") || "-";
  renderModeBanner();
}

function resetPreflightResult(message = "Select a supported operation and run preflight.") {
  els.decisionMetric.textContent = "Not run";
  els.availableMetric.textContent = "-";
  els.statusLabel.textContent = "Ready";
  els.result.className = "empty-state";
  els.result.innerHTML = `<h2>Precheck Result</h2><p>${message}</p>`;
}

function buildPayload() {
  const service = selectedService();
  const operation = selectedOperation();
  const base = {
    operation: operation.operation,
    region: field("region"),
    compartment_id: field("compartment_id"),
  };
  if (field("availability_domain")) base.availability_domain = field("availability_domain");
  if (operation.operation === "create_instances") {
    base.resource_type = "instance";
    base.workload = {
      shape: field("shape"),
      instance_count: Number(field("instance_count")),
      ocpus_per_instance: Number(field("ocpus_per_instance")),
      memory_gb_per_instance: Number(field("memory_gb_per_instance")),
    };
  }
  if (operation.operation === "create_volumes") {
    base.resource_type = "volume";
    base.workload = {
      volume_count: Number(field("volume_count")),
      size_gb_each: Number(field("size_gb_each")),
    };
  }
  if (operation.operation === "create_network_load_balancers") {
    base.resource_type = "network_load_balancer";
    base.workload = { nlb_count: Number(field("nlb_count")) };
  }
  if (operation.operation === "check_discovered_limit") {
    base.resource_type = "discovered_limit";
    base.limit_name = field("limit_name");
    base.requested = { units: Number(field("requested_units")) };
  }
  return { service: service.service, operation: base };
}

function friendlyUnknown(reasons) {
  const text = reasons.join(" ").toLowerCase();
  if (text.includes("availability_domain") || text.includes("availability domain") || text.includes("ad-scoped")) {
    return ["The selected Availability Domain could not be evaluated.", "Check the Availability Domain and try again."];
  }
  if (text.includes("permission") || text.includes("notauthorized") || text.includes("403")) {
    return ["A required OCI permission is missing.", "Check the runner dynamic-group policy and try again."];
  }
  if (text.includes("could not reliably map")) {
    return ["The selected operation could not be mapped to a verified OCI limit.", "Use a supported operation or review the capability matrix."];
  }
  return ["We could not safely determine whether this request fits.", "Review the technical details and try again."];
}

function renderResult(data) {
  const decision = data.decision || "UNKNOWN";
  const display = decision === "UNKNOWN" ? "UNABLE TO VALIDATE" : decision;
  const checks = data.checks || [];
  const blockers = checks.filter((check) => check.status === "WOULD_EXCEED");
  const reasons = data.unknown_reasons || [];
  const [unknownReason, unknownAction] = friendlyUnknown(reasons);
  const firstBlocker = blockers[0];
  const firstCheck = firstBlocker || checks[0] || {};
  const recommendations = data.recommendations || [];
  const evaluatedServiceLimit = checks.some((check) => check.constraint_type === "SERVICE_LIMIT");
  const evaluatedQuota = checks.some((check) => check.constraint_type === "COMPARTMENT_QUOTA");
  const checkRows = checks.map((check) => `
    <tr>
      <td>${customerConstraint(check.constraint_type)}</td>
      <td>${check.status}</td>
      <td>${formatValue(check.current)}</td>
      <td>${formatValue(check.maximum)}</td>
      <td>${formatValue(check.available)}</td>
      <td>${formatValue(check.requested_delta)}</td>
      <td>${formatValue(check.projected)}</td>
      <td>${formatValue(check.shortfall)}</td>
    </tr>
  `).join("");
  const technicalRows = checks.map((check) => `<li>${check.constraint_type}: ${check.limit_name} (${check.metric})</li>`).join("");
  const reasonRows = reasons.map((reason) => `<li>${reason}</li>`).join("");
  const action = recommendations[0]?.reason || (decision === "BLOCK" ? "Reduce the workload, increase the applicable limit or quota, or deploy to another eligible scope." : "No action required for known service-limit or quota constraints.");

  els.decisionMetric.textContent = display;
  els.availableMetric.textContent = formatValue(data.effective_available_capacity);
  els.statusLabel.textContent = display;
  els.result.className = decision.toLowerCase();
  els.result.innerHTML = `
    <h2>Precheck Result</h2>
    <div class="decision ${decision.toLowerCase()}">${display}</div>
    <p>${decision === "PASS" ? "PASS - no known service-limit or quota constraint was found for this request." : decision === "BLOCK" ? "Your planned workload exceeds a known capacity constraint." : unknownReason}</p>
    <p class="advisory">PASS means no known service-limit/quota constraint was detected. It does not guarantee physical host availability or successful provisioning. Preflight is advisory and does not reserve capacity.</p>
    ${workloadDetails(data.operation?.metadata?.workload)}
    <section class="result-grid">
      <div><span>Current usage</span><strong>${formatValue(firstCheck.current)}</strong></div>
      <div><span>Limit</span><strong>${formatValue(firstCheck.maximum)}</strong></div>
      <div><span>Available</span><strong>${formatValue(firstCheck.available)}</strong></div>
      <div><span>Requested</span><strong>${formatValue(firstCheck.requested_delta)}</strong></div>
      <div><span>Projected</span><strong>${formatValue(firstCheck.projected)}</strong></div>
      <div><span>Blocking constraint</span><strong>${firstBlocker ? customerConstraint(firstBlocker.constraint_type) : "-"}</strong></div>
      <div><span>Shortfall</span><strong>${formatValue(firstCheck.shortfall)}</strong></div>
      <div><span>Recommended action</span><strong>${decision === "UNKNOWN" ? unknownAction : action}</strong></div>
    </section>
    <section class="evaluated">
      <div>
        <h3>Constraints Evaluated</h3>
        <ul>
          <li><span class="checkmark">&#10003;</span> Service limit${evaluatedServiceLimit ? "" : " - no usable service-limit check returned"}</li>
          <li><span class="checkmark">&#10003;</span> Compartment quota${evaluatedQuota ? "" : " - no applicable quota found"}</li>
          <li><span class="checkmark">&#10003;</span> Region / AD scope: ${data.operation?.availability_domain || data.operation?.region || "-"}</li>
        </ul>
      </div>
      <div>
        <h3>Not Evaluated</h3>
        <ul>
          <li><span class="openmark">&#9675;</span> Physical host availability</li>
          <li><span class="openmark">&#9675;</span> Other service-specific constraints</li>
        </ul>
      </div>
    </section>
    ${checkRows ? `<table><thead><tr><th>Constraint</th><th>Status</th><th>Current Usage</th><th>Limit / Quota</th><th>Available</th><th>Requested</th><th>Projected</th><th>Shortfall</th></tr></thead><tbody>${checkRows}</tbody></table>` : ""}
    <details><summary>Technical details</summary><ul>${technicalRows}${reasonRows}</ul></details>
  `;
}

function customerConstraint(value) {
  if (value === "SERVICE_LIMIT") return "Service limit";
  if (value === "COMPARTMENT_QUOTA") return "Compartment quota";
  return formatValue(value);
}

function workloadDetails(workload) {
  if (!workload) return "";
  if (workload.resource === "Block Volume") {
    return `<h3>Planned workload</h3><p>${workload.volume_count} x ${workload.size_gb_each} GB Block Volumes (${workload.total_storage_gb} GB total).</p>`;
  }
  if (workload.resource === "Network Load Balancer") {
    return `<h3>Planned workload</h3><p>${workload.nlb_count} Network Load Balancers. Preflight coverage: ${workload.preflight_coverage}.</p>`;
  }
  if (workload.resource === "Discovered OCI limit") {
    return `<h3>Planned workload</h3><p>${workload.requested_units} units against ${workload.limit_name}. This is a generic live limit check.</p>`;
  }
  return `<h3>Planned workload</h3><p>${workload.instance_count} x ${workload.shape}, ${workload.total_ocpus} OCPUs and ${workload.total_memory_gb} GB memory.</p>`;
}

function demoResult(kind) {
  const operation = selectedOperation();
  const decision = kind === "block" ? "BLOCK" : kind === "validate" ? "UNKNOWN" : "PASS";
  const requested = operation?.operation === "create_network_load_balancers" ? Number(field("nlb_count") || 5) : operation?.operation === "create_volumes" ? Number(field("volume_count") || 5) * Number(field("size_gb_each") || 2048) : 20;
  const workloadByOperation = {
    create_instances: { resource: "Compute Instance", instance_count: 5, shape: "VM.Standard.E5.Flex", total_ocpus: 20, total_memory_gb: 160 },
    create_volumes: { resource: "Block Volume", volume_count: Number(field("volume_count") || 5), size_gb_each: Number(field("size_gb_each") || 2048), total_storage_gb: requested },
    create_network_load_balancers: { resource: "Network Load Balancer", nlb_count: Number(field("nlb_count") || 5), preflight_coverage: operation?.coverage },
  };
  return {
    decision,
    confidence: decision === "UNKNOWN" ? "LOW" : "HIGH",
    advisory: true,
    operation: {
      service: selectedService()?.service,
      region: field("region"),
      availability_domain: field("availability_domain"),
      compartment_id: field("compartment_id"),
      requested_delta: { units: requested },
      metadata: { workload: workloadByOperation[operation?.operation] },
    },
    effective_available_capacity: decision === "UNKNOWN" ? null : kind === "block" ? 4 : 100,
    primary_blocking_constraint: decision === "BLOCK" ? "SERVICE_LIMIT" : null,
    checks: decision === "UNKNOWN" ? [] : [{ constraint_type: "SERVICE_LIMIT", limit_name: "demo-limit", metric: "units", current: 0, maximum: kind === "block" ? 4 : 100, available: kind === "block" ? 4 : 100, requested_delta: requested, projected: requested, status: kind === "block" ? "WOULD_EXCEED" : "OK", shortfall: kind === "block" ? requested - 4 : null }],
    recommendations: decision === "BLOCK" ? [{ action: "REQUEST_LIMIT_INCREASE", reason: "Reduce the workload or increase the applicable limit." }] : [],
    unknown_reasons: decision === "UNKNOWN" ? ["The selected Availability Domain could not be evaluated."] : [],
    evaluated_at: new Date().toISOString(),
  };
}

async function runPreflight() {
  const operation = selectedOperation();
  if (!operation || operation.capability !== "FULL_PREFLIGHT") return;
  els.run.disabled = true;
  els.result.className = "empty-state";
  els.result.innerHTML = "<h2>Precheck Result</h2><p>Checking service-limit and quota capacity...</p>";
  try {
    if (DEMO_MODE) {
      renderResult(demoResult(DEMO_MODE));
    } else {
      const response = await fetch(`${API_BASE}/preflight`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(buildPayload()) });
      renderResult(await response.json());
    }
  } catch (error) {
    renderResult({ decision: "UNKNOWN", checks: [], unknown_reasons: [error.message], operation: buildPayload().operation, recommendations: [] });
  } finally {
    els.run.disabled = selectedOperation()?.capability !== "FULL_PREFLIGHT";
  }
}

async function loadCapacity(refresh = false) {
  const data = DEMO_MODE ? demoCapacity() : await (await fetch(`${API_BASE}${refresh ? "/capacity/refresh" : "/capacity"}`, { method: refresh ? "POST" : "GET" })).json();
  capabilities = data.capacity || [];
  capacityMeta = data;
  mergeDiscoveredServicesIntoCatalog();
  syncOperations({ resetResult: false });
  renderCapacitySummary();
  renderCapabilityRows();
  renderCoverage();
}

function renderModeBanner() {
  const cache = capacityMeta.cache || {};
  const synthetic = DEMO_MODE || cache.status === "synthetic" || capabilities.some((item) => item.data_status === "SYNTHETIC");
  const refreshed = cache.last_refreshed ? new Date(cache.last_refreshed * 1000).toLocaleString() : "-";
  const age = formatDuration(cache.age_seconds);
  const status = statusText(cache.status || runtimeStatus.status);
  const region = field("region") || runtimeStatus.region || runtimeStatus.quota_region || "not selected";
  const tenancy = synthetic ? "demo tenancy" : maskedTenancy(runtimeStatus.tenancy_id || (runtimeStatus.tenancy_configured ? "configured" : ""));
  els.modeBanner.className = `mode-banner ${synthetic ? "demo" : "live"}`;
  els.modeLabel.textContent = synthetic ? "DEMO / SYNTHETIC DATA" : "LIVE OCI DATA";
  els.modeContext.textContent = `Tenancy: ${tenancy} | Region: ${region} | Last refresh: ${refreshed} | Age: ${age} | Status: ${status}`;
}

function renderCapacitySummary() {
  const summary = capacityMeta.summary || {};
  const counts = summary.capability_counts || {};
  const cache = capacityMeta.cache || {};
  els.servicesDiscovered.textContent = formatValue(summary.services_discovered);
  els.limitsDiscovered.textContent = formatValue(summary.limits_discovered);
  els.fullCount.textContent = formatValue(counts.FULL_PREFLIGHT);
  els.monitorCount.textContent = formatValue(counts.MONITOR_ONLY);
  els.discoveryCount.textContent = formatValue(counts.DISCOVERY_ONLY);
  els.unsupportedCount.textContent = formatValue(counts.UNSUPPORTED);
  const risks = summary.risk_counts || {};
  els.criticalCount.textContent = formatValue(risks.CRITICAL);
  els.warningCount.textContent = formatValue(risks.WARNING);
  els.watchCount.textContent = formatValue(risks.WATCH);
  els.healthyCount.textContent = formatValue(risks.HEALTHY);
  els.unknownCount.textContent = formatValue(risks.UNKNOWN);
  const refreshed = cache.last_refreshed ? new Date(cache.last_refreshed * 1000).toLocaleString() : "-";
  const age = formatDuration(cache.age_seconds);
  const status = statusText(cache.status);
  els.cacheAge.textContent = age;
  els.cacheState.textContent = status;
  els.cacheRefreshed.textContent = refreshed;
  els.cacheAgeDetail.textContent = age;
  els.cacheStateDetail.textContent = status;
  els.cacheStatus.textContent = `Status: ${status} | Last refreshed: ${refreshed} | Data age: ${age}`;
  const synthetic = cache.status === "synthetic" || capabilities.some((item) => item.data_status === "SYNTHETIC");
  els.dataNotice.hidden = false;
  els.dataNotice.textContent = synthetic ? "DEMO / SYNTHETIC DATA: capacity values are synthetic and are not OCI tenancy capacity values." : "LIVE OCI DATA: values come from the connected tenancy. Values unavailable from OCI remain explicitly marked Data unavailable.";
  renderModeBanner();
}

function filteredCapabilities() {
  const service = document.querySelector("#filterService").value.trim().toLowerCase();
  const capability = document.querySelector("#filterCapability").value;
  const risk = document.querySelector("#filterRisk").value;
  const region = document.querySelector("#filterRegion").value.trim().toLowerCase();
  const ad = document.querySelector("#filterAd").value.trim().toLowerCase();
  const limitName = document.querySelector("#filterLimitName").value.trim().toLowerCase();
  return capabilities.filter((item) => {
    if (service && !item.service.toLowerCase().includes(service)) return false;
    if (capability && item.capability !== capability) return false;
    if (risk && item.risk_state !== risk) return false;
    if (region && !(item.region || "").toLowerCase().includes(region)) return false;
    if (ad && !(item.availability_domain || "").toLowerCase().includes(ad)) return false;
    if (limitName && !`${item.limit_name || ""} ${item.limit_description || ""}`.toLowerCase().includes(limitName)) return false;
    return true;
  });
}

function renderCapabilityRows() {
  const rows = filteredCapabilities();
  const visibleRows = rows.slice(0, CAPACITY_ROW_RENDER_LIMIT);
  els.capacityRowStatus.textContent = rows.length > CAPACITY_ROW_RENDER_LIMIT
    ? `Showing ${CAPACITY_ROW_RENDER_LIMIT} of ${rows.length} matching limits. Use filters to narrow the list.`
    : `Showing ${rows.length} matching limit${rows.length === 1 ? "" : "s"}.`;
  els.capabilityRows.innerHTML = visibleRows.map((item) => `
    <tr>
      <td>${item.service}</td>
      <td><strong>${item.limit_name}</strong><br><small>${item.limit_description || "-"}</small></td>
      <td>${formatValue(item.scope_type)}</td>
      <td>${formatValue(item.region)}<br><small>${formatValue(item.availability_domain)}</small></td>
      <td>${formatValue(item.limit_value)}</td>
      <td>${formatValue(item.current_usage)}</td>
      <td>${formatValue(item.available)}</td>
      <td>${item.utilization === null || item.utilization === undefined ? "Data unavailable" : `${(item.utilization * 100).toFixed(1)}%`}</td>
      <td>${formatValue(item.risk_state)}</td>
      <td><span class="badge ${item.capability.toLowerCase()}">${capabilityText(item.capability)}</span></td>
      <td>${item.last_refreshed ? new Date(item.last_refreshed * 1000).toLocaleString() : "-"}</td>
      <td>${item.data_status || (item.resource_availability_supported ? "AVAILABLE" : "DATA_UNAVAILABLE")}</td>
    </tr>
  `).join("");
}

function renderCoverage() {
  const serviceStats = new Map();
  for (const row of capabilities) {
    if (!row.service) continue;
    const stats = serviceStats.get(row.service) || {
      limits: 0,
      full: 0,
      monitor: 0,
      discovery: 0,
      unsupported: 0,
    };
    stats.limits += 1;
    if (row.capability === "FULL_PREFLIGHT") stats.full += 1;
    if (row.capability === "MONITOR_ONLY") stats.monitor += 1;
    if (row.capability === "DISCOVERY_ONLY") stats.discovery += 1;
    if (row.capability === "UNSUPPORTED") stats.unsupported += 1;
    serviceStats.set(row.service, stats);
  }
  const operationRows = operationCatalog.flatMap((service) => service.operations.map((operation) => {
    const stats = serviceStats.get(service.service);
    const coverage = stats
      ? `${stats.limits} discovered limits: ${stats.full} FULL_PREFLIGHT, ${stats.monitor} MONITOR_ONLY, ${stats.discovery} DISCOVERY_ONLY, ${stats.unsupported} UNSUPPORTED.`
      : operation.coverage;
    return { service: service.display_name || service.service, ...operation, coverage };
  }));
  const grouped = new Map();
  for (const row of operationRows) grouped.set(row.service, (grouped.get(row.service) || []).concat(row));
  els.coverageRows.innerHTML = [...grouped.entries()].map(([service, rows]) => `<article class="coverage-service"><h3>${service}</h3>${rows.map((row) => `<div><strong>${row.display_name || row.operation}</strong><span class="badge ${row.capability.toLowerCase()}">${capabilityText(row.capability)}</span><p>${row.capability === "FULL_PREFLIGHT" ? row.coverage : "Preflight not currently supported. " + capabilityExplanation(row)}</p></div>`).join("")}</article>`).join("") || "<p>No verified operation adapters are registered. Discovered limits remain visible above.</p>";
}

els.service.addEventListener("change", syncOperations);
els.operation.addEventListener("change", renderOperation);
els.run.addEventListener("click", runPreflight);
["filterService", "filterCapability", "filterRisk", "filterRegion", "filterAd", "filterLimitName"].forEach((id) => {
  document.querySelector(`#${id}`).addEventListener("input", renderCapabilityRows);
  document.querySelector(`#${id}`).addEventListener("change", renderCapabilityRows);
});
els.refreshCapacity.addEventListener("click", async () => {
  els.refreshCapacity.disabled = true;
  try { await loadCapacity(true); } finally { els.refreshCapacity.disabled = false; }
});

Promise.all([loadRuntimeStatus(), loadOperations()])
  .then(() => loadDiscoveredServices())
  .then(() => loadCapacity())
  .then(() => {
    if (DEMO_MODE) {
      renderResult(demoResult(DEMO_MODE));
    }
  })
  .catch((error) => {
    els.result.className = "unknown";
    els.result.innerHTML = `<h2>Precheck Result</h2><div class="decision unknown">UNABLE TO VALIDATE</div><p>Unable to load operation metadata.</p><details><summary>Technical details</summary><ul><li>${error.message}</li></ul></details>`;
  });
