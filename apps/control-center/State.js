.pragma library

function contains(values, name) { return (values || []).indexOf(name) !== -1; }
function bytes(value) {
    if (value === null || value === undefined) return "Unavailable";
    const units = ["B", "KiB", "MiB", "GiB"];
    let size = Number(value), unit = 0;
    while (Math.abs(size) >= 1024 && unit < units.length - 1) { size /= 1024; ++unit; }
    return size.toFixed(unit === 0 ? 0 : 1) + " " + units[unit];
}
function stateLabel(value) {
    const names = {queued: "Queued", starting: "Starting", running: "Working", planned: "Planned",
        preparing: "Preparing packages", downloaded: "Packages verified", snapshot_pending: "Creating recovery snapshot",
        snapshot_created: "Recovery snapshot ready", applying: "Applying packages", validating: "Checking the system",
        awaiting_boot: "Restart required", succeeded: "Verified complete", failed: "Failed",
        rollback_required: "Offline recovery required", rolled_back: "Rollback verified", rejected: "Request rejected"};
    return names[value] || value || "Not observed";
}
function operationLabel(operation) {
    const transaction = operation.transaction || {};
    return stateLabel(transaction.state || operation.state);
}
function observation(value) {
    if (value === null || value === undefined) return "Unavailable";
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (typeof value === "object") return JSON.stringify(value, null, 2);
    return String(value);
}
function message(value) {
    return "<span>" + String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/\n/g, "<br>") + "</span>";
}
function observations(value) {
    if (value === null || value === undefined) return ["Unavailable"];
    if (Array.isArray(value)) return value.map(function(check) {
        if (typeof check !== "object" || check === null) return String(check);
        return (check.name || check.id || "Check") + ": " + (check.status || check.state || "Unknown")
            + (check.detail ? " · " + check.detail : "");
    });
    if (typeof value !== "object") return [observation(value)];
    return Object.keys(value).filter(function(key) { return key !== "schema_version"; }).map(function(key) {
        const label = key.replace(/_/g, " ").replace(/^./, function(letter) { return letter.toUpperCase(); });
        if (value[key] !== null && typeof value[key] === "object")
            return label + ": " + observations(value[key]).join("; ");
        return label + ": " + observation(value[key]);
    });
}
function changeLabel(change) {
    const kind = change.kind || change.action || "change";
    if (kind === "upgrade") return "Upgrade " + change.name + ": " + change.from + " → " + change.to;
    if (kind === "remove") return "Remove " + change.name + " " + (change.version || "");
    return "Install " + change.name + " " + (change.version || "");
}
function configurationChanges(plan) {
    const management = plan.management;
    if (!management) return [];
    const before = (management.before || {}).applied || {};
    const after = (management.after || {}).applied || {};
    let changes = [];
    ["packages", "gaming"].forEach(function(key) {
        const previous = before[key] || [], next = after[key] || [];
        next.forEach(function(name) { if (previous.indexOf(name) === -1) changes.push("Add " + (key === "gaming" ? "feature bundle: " : "explicit package: ") + name); });
        previous.forEach(function(name) { if (next.indexOf(name) === -1) changes.push("Remove " + (key === "gaming" ? "feature bundle: " : "explicit package choice: ") + name); });
    });
    const oldProviders = before.providers || {}, newProviders = after.providers || {};
    Object.keys(Object.assign({}, oldProviders, newProviders)).forEach(function(name) {
        if (oldProviders[name] !== newProviders[name]) changes.push("Provider for " + name + ": " + (oldProviders[name] || "not selected") + " → " + (newProviders[name] || "not selected"));
    });
    return changes;
}
function reasonChanges(plan) {
    const management = plan.management || {};
    const before = management.reasons_before || {}, after = management.reasons_after || {};
    return Object.keys(after).filter(function(name) { return before[name] && before[name] !== after[name]; })
        .map(function(name) { return name + ": " + before[name] + " → " + after[name]; });
}
function packageGroups(plan) {
    const after = (plan.management || {}).after || {};
    const explicit = (after.applied || {}).packages || [];
    const owned = after.packages || {};
    const groups = [
        {id: "requested", title: "Requested installations", changes: []},
        {id: "dependencies", title: "Required dependencies", changes: []},
        {id: "updates", title: "Synchronized updates", changes: []},
        {id: "removals", title: "Removals", changes: []},
        {id: "other", title: "Other resolved changes", changes: []}
    ];
    ((plan.packages || {}).changes || []).forEach(function(change) {
        let group = 4;
        if (change.kind === "remove") group = 3;
        else if (change.kind === "upgrade") group = 2;
        else if (change.kind === "install") {
            const receipt = owned[change.name];
            if (contains(explicit, change.name) || (receipt && (receipt.owners || []).length)) group = 0;
            else if (receipt && Array.isArray(receipt.owners) && !receipt.owners.length) group = 1;
        }
        groups[group].changes.push(change);
    });
    return groups.filter(function(group) { return group.changes.length > 0; });
}
function canApply(status, plan, busy, active, validated) {
    const inner = plan.plan || {}, boot = inner.boot || {}, packages = inner.packages || {};
    if ((packages.changes || []).length && (inner.snapshot_required !== true || boot.regenerate_uki !== true)) return false;
    return status.live === false && !status.reboot_required && plan.executable === true
        && !status.recovery_required && status.configuration_available !== false
        && !!plan.plan_id && !busy && !active && validated === true;
}
