import QtQuick
import QtTest
import "../State.js" as State

TestCase {
    id: testCase
    name: "ControlCenter"
    when: windowShown
    property var app: null
    QtObject {
        id: perf
        property var status: ({schema_version: 1, context: {virtual_machine: true}, baseline_blockers: []})
        property var runs: []
        property var result: ({})
        property var comparison: ({})
        property var sample: ({cpu_busy_percent: null, unavailable: ["Thermal sensors"]})
        property string error: ""
        property string phase: ""
        property bool running: false
        property bool blocked: false
        property bool loading: false
        property int starts: 0
        function refresh() {}
        function observe() {}
        function start(kind) { starts++; running = true; }
        function stop() { running = false; }
        function show(id) {}
        function compare(a, b) {}
        function exportFile(id, url) {}
    }
    QtObject {
        id: fake
        property var performance: perf
        property var status: ({schema_version: 1, live: false, reboot_required: false, drift: [], configuration: {packages: []}})
        property var draft: ({schema_version: 1, packages: [], gaming: [], providers: {}})
        property var plan: installPlanFixture
        property bool planValid: true
        property var operation: ({})
        property var packages: []
        property var features: []
        property var history: []
        property string error: ""
        property string notice: ""
        property string configurationText: ""
        property bool busy: false
        property bool loading: false
        property bool dirty: false
        property bool active: false
        property int reviews: 0
        property int applications: 0
        property string lastPackage: ""
        property bool lastSelected: false
        signal planReady()
        signal submitted()
        signal configurationParsed(string text)
        function refresh() {}
        function installed() {}
        function clearError() { error = ""; }
        function review() { ++reviews; planReady(); }
        function apply() { ++applications; }
        function discard() { dirty = false; }
        function setPackage(name, selected) { lastPackage = name; lastSelected = selected; }
    }
    function initTestCase() {
        const component = Qt.createComponent("../Main.qml");
        compare(component.status, Component.Ready, component.errorString());
        app = component.createObject(null, {backend: fake});
        verify(app !== null, component.errorString());
    }
    function cleanupTestCase() { if (app) app.destroy(); }
    function init() {
        failOnWarning(/.?/);
        fake.status = {schema_version: 1, live: false, reboot_required: false, drift: [], configuration: {packages: []}};
        fake.busy = false; fake.active = false; fake.dirty = false;
        fake.plan = installPlanFixture; fake.planValid = true;
        fake.reviews = 0; fake.applications = 0;
        fake.lastPackage = ""; fake.lastSelected = false;
        perf.running = false; perf.blocked = false; perf.starts = 0;
        perf.status = {schema_version: 1, context: {virtual_machine: true}, baseline_blockers: []};
        fake.packages = [];
        app.editorDirty = false;
        findChild(app, "softwareTabs").currentIndex = 0;
    }
    function test_applyRequiresInstalledIdleReviewedSystem() {
        app.section = 5;
        const button = findChild(app, "applyButton");
        verify(button);
        tryCompare(button, "enabled", true);
        fake.status = {live: true};
        tryCompare(button, "enabled", false);
        fake.status = {live: false, reboot_required: true};
        tryCompare(button, "enabled", false);
        fake.status = {live: false}; fake.active = true;
        tryCompare(button, "enabled", false);
        fake.active = false; fake.busy = true;
        tryCompare(button, "enabled", false);
        fake.busy = false; fake.status = {live: false, configuration_available: false, recovery_required: true};
        tryCompare(button, "enabled", false);
        tryCompare(findChild(app, "reviewButton"), "enabled", false);
        compare(fake.applications, 0);
    }
    function test_inconsistentFlagsNeverEnableAuthentication() {
        app.section = 5;
        const button = findChild(app, "applyButton");
        let invalid = JSON.parse(JSON.stringify(installPlanFixture));
        invalid.plan.snapshot_required = false;
        fake.plan = invalid;
        tryCompare(button, "enabled", false);
        fake.plan = blockedPlanFixture; fake.planValid = false;
        tryCompare(button, "enabled", false);
    }
    function test_reviewIsKeyboardAccessible() {
        app.section = 0;
        const button = findChild(app, "reviewButton");
        verify(button);
        button.forceActiveFocus();
        keyClick(Qt.Key_Space);
        tryCompare(fake, "reviews", 1);
        compare(app.section, 5);
    }
    function test_overviewReviewsUpdatesWithoutDiscardingDrafts() {
        app.section = 0;
        const button = findChild(app, "reviewUpdatesButton");
        verify(button);
        tryCompare(button, "enabled", true);
        fake.dirty = true;
        tryCompare(button, "enabled", false);
        fake.dirty = false; app.editorDirty = true;
        tryCompare(button, "enabled", false);
        app.editorDirty = false;
        tryCompare(button, "enabled", true);
        button.forceActiveFocus();
        keyClick(Qt.Key_Space);
        tryCompare(fake, "reviews", 1);
        compare(fake.applications, 0);
        compare(app.section, 5);
    }
    function test_labelsPreservePendingAndUnknownStates() {
        compare(State.stateLabel("awaiting_boot"), "Restart required");
        compare(State.stateLabel("succeeded"), "Verified complete");
        compare(State.observation(null), "Unavailable");
        verify(!State.canApply({}, fake.plan, false, false, true));
        compare(State.bytes(-2048), "-2.0 KiB");
    }
    function test_reviewGroupsUseResolvedKindsAndRecordedOwnership() {
        const groups = State.packageGroups({management: {after: {
            applied: {packages: ["kate"]},
            packages: {steam: {owners: ["gaming:core"]}, library: {owners: []}}
        }}, packages: {changes: [
            {kind: "install", name: "kate"}, {kind: "install", name: "steam"},
            {kind: "install", name: "library"}, {kind: "upgrade", name: "nano"},
            {kind: "remove", name: "old-app"}, {kind: "install", name: "unknown"}
        ]}});
        compare(groups.map(group => group.id), ["requested", "dependencies", "updates", "removals", "other"]);
        compare(groups[0].changes.map(change => change.name), ["kate", "steam"]);
        compare(groups[1].changes[0].name, "library");
        compare(groups[2].changes[0].name, "nano");
        compare(groups[3].changes[0].name, "old-app");
        compare(groups[4].changes[0].name, "unknown");
        compare(State.packageGroups(installPlanFixture.plan)[0].id, "requested");
    }
    function test_metadataChangesStillExplainVerifiedRestart() {
        app.section = 5;
        fake.plan = metadataPlanFixture;
        verify(findChild(app, "restartExplanation").text.includes("verified restart"));
    }
    function test_validatedTextBecomesCleanWithoutDiscardingLaterEdits() {
        app.section = 2;
        const editor = findChild(app, "configurationEditor");
        editor.text = "invalid TOML";
        compare(app.editorDirty, true);
        fake.error = "Invalid TOML";
        compare(app.editorDirty, true);
        fake.error = "";
        editor.text = "schema_version = 1";
        fake.configurationParsed("schema_version = 1");
        compare(app.editorDirty, false);
        editor.text = "schema_version = 1\npackages = [\"kate\"]";
        fake.configurationParsed("schema_version = 1");
        compare(app.editorDirty, true);
    }
    function findCloseControl(item) {
        if (item.text === "Close" && item.icon && item.icon.name === "dialog-close") return item;
        const children = item.children || [];
        for (let index = 0; index < children.length; ++index) {
            const match = findCloseControl(children[index]);
            if (match) return match;
        }
        return null;
    }
    function test_errorCanReappearAfterDismiss() {
        const message = findChild(app, "errorMessage");
        verify(message);
        fake.error = "First observed error";
        tryCompare(message, "visible", true);
        verify(waitForPolish(app));
        const close = findCloseControl(message);
        verify(close !== null, "actual Kirigami close control found");
        mouseClick(close);
        tryCompare(message, "visible", false);
        tryCompare(fake, "error", "");
        fake.error = "Second observed error";
        tryCompare(message, "visible", true);
        verify(message.text.includes("Second observed error"));
        fake.clearError();
        tryCompare(message, "visible", false);
    }
    function test_existingAppsCanBeSelectedWithoutRemovingProtection() {
        app.section = 1;
        findChild(app, "softwareTabs").currentIndex = 1;
        fake.packages = [
            {name: "nano", protected: true, system_package: false, selectable: true},
            {name: "glibc", protected: true, system_package: true, selectable: false},
            {name: "foreign-app", protected: true, system_package: false, selectable: false}
        ];
        const list = findChild(app, "packageList");
        tryVerify(() => list.itemAtIndex(0) !== null);
        const manual = findChild(list.itemAtIndex(0), "packageChoice-nano");
        verify(manual);
        tryCompare(manual, "enabled", true);
        tryCompare(findChild(list.itemAtIndex(1), "packageChoice-glibc"), "enabled", false);
        tryCompare(findChild(list.itemAtIndex(2), "packageChoice-foreign-app"), "enabled", false);
        manual.forceActiveFocus();
        keyClick(Qt.Key_Space);
        tryCompare(fake, "lastPackage", "nano");
        compare(fake.lastSelected, true);
        fake.busy = true;
        tryCompare(manual, "enabled", false);
    }
    function test_populatedPagesRender() {
        fake.status = {schema_version: 1, live: false, reboot_required: false, drift: [], configuration: {packages: ["kate", "nano"]}, health: {state: "passed", required_services: "running"}, security: {secure_boot: true, policy: "owner keys"}};
        fake.features = [{id: "core", title: "Steam Core", supported: true, packages: ["steam", "steam-devices"]}, {id: "heroic", title: "Heroic", supported: false, packages: []}];
        fake.packages = [{name: "kate", version: "26.08.1-1", repository: "extra", installed_version: "26.08.1-1", description: "Advanced text editor", protected: false, system_package: false, selectable: true}];
        fake.history = [{id: 7, state: "awaiting_boot"}];
        fake.plan = installPlanFixture;
        for (let section = 0; section < 6; ++section) {
            app.section = section;
            verify(waitForPolish(app));
            waitForRendering(app.contentItem);
            const image = grabImage(app.contentItem);
            verify(image.width >= 760);
            image.save(testOutputDirectory + "/control-center-page-" + section + ".png");
        }
    }
    function test_performanceKeyboardStopAndUnavailableMeasurements() {
        app.section = 4;
        const record = findChild(app, "recordPerformance");
        const stop = findChild(app, "stopPerformance");
        verify(findChild(app, "cpuMetric").text.includes("Unavailable"));
        tryCompare(record, "enabled", true);
        record.forceActiveFocus(); keyClick(Qt.Key_Space);
        tryCompare(perf, "starts", 1); tryCompare(stop, "enabled", true);
        stop.forceActiveFocus(); keyClick(Qt.Key_Space); tryCompare(perf, "running", false);
        perf.status = {schema_version: 1, context: {}, baseline_blockers: ["Live session"]};
        tryCompare(findChild(app, "baselinePerformance"), "enabled", false);
        perf.blocked = true; tryCompare(record, "enabled", false);
    }
}
