import QtQuick
import QtTest
import "../State.js" as State

TestCase {
    id: testCase
    name: "ControlCenter"
    when: windowShown
    property var app: null
    QtObject {
        id: fake
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
        signal planReady()
        signal submitted()
        function refresh() {}
        function installed() {}
        function clearError() { error = ""; }
        function review() { ++reviews; planReady(); }
        function apply() { ++applications; }
        function discard() { dirty = false; }
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
    }
    function test_applyRequiresInstalledIdleReviewedSystem() {
        app.section = 4;
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
        app.section = 4;
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
        compare(app.section, 4);
    }
    function test_labelsPreservePendingAndUnknownStates() {
        compare(State.stateLabel("awaiting_boot"), "Restart required");
        compare(State.stateLabel("succeeded"), "Verified complete");
        compare(State.observation(null), "Unavailable");
        verify(!State.canApply({}, fake.plan, false, false, true));
        compare(State.bytes(-2048), "-2.0 KiB");
    }
    function test_populatedPagesRender() {
        fake.status = {schema_version: 1, live: false, reboot_required: false, drift: [], configuration: {packages: ["kate", "nano"]}, health: {state: "passed", required_services: "running"}, security: {secure_boot: true, policy: "owner keys"}};
        fake.features = [{id: "core", title: "Steam Core", supported: true, packages: ["steam", "steam-devices"]}, {id: "heroic", title: "Heroic", supported: false, packages: []}];
        fake.packages = [{name: "kate", version: "26.08.1-1", repository: "extra", installed_version: "26.08.1-1", description: "Advanced text editor", protected: false}];
        fake.history = [{id: 7, state: "awaiting_boot"}];
        fake.plan = installPlanFixture;
        for (let section = 0; section < 5; ++section) {
            app.section = section;
            verify(waitForPolish(app));
            waitForRendering(app.contentItem);
            const image = grabImage(app.contentItem);
            verify(image.width >= 760);
            image.save(testOutputDirectory + "/control-center-page-" + section + ".png");
        }
    }
}
