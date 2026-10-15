pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import org.kde.kirigami as Kirigami
import "State.js" as State

ApplicationWindow {
    id: window
    required property var backend
    property int section: 0
    property var selectedRecord: ({})
    property bool editorDirty: false
    property bool closeConfirmed: false
    readonly property bool editing: !window.backend.busy && !window.backend.active && !!window.backend.draft.schema_version && window.backend.status.configuration_available !== false && !window.backend.status.recovery_required
    readonly property var packagePlan: window.backend.plan.plan ? window.backend.plan.plan.packages || {} : ({})
    visible: true
    width: 1040
    height: 760
    minimumWidth: 760
    minimumHeight: 540
    title: qsTr("Astraeus Control Center")

    Connections {
        target: window.backend
        function onPlanReady() { window.section = 5; }
        function onSubmitted() { window.section = 3; }
        function onConfigurationParsed(text) { if (configurationEditor.text === text) window.editorDirty = false; }
    }
    FileDialog {
        id: importDialog
        title: qsTr("Import a system configuration")
        nameFilters: [qsTr("TOML configuration (*.toml)"), qsTr("All files (*)")]
        onAccepted: window.backend.importFile(selectedFile)
    }
    FileDialog {
        id: exportDialog
        title: qsTr("Export the saved system configuration")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "toml"
        nameFilters: [qsTr("TOML configuration (*.toml)")]
        onAccepted: window.backend.exportFile(selectedFile)
    }
    Dialog {
        id: closeDialog
        objectName: "closeDialog"
        title: qsTr("Discard your draft?")
        anchors.centerIn: parent
        standardButtons: Dialog.Discard | Dialog.Cancel
        Label { text: qsTr("Your changes have not been applied or saved."); wrapMode: Text.WordWrap }
        onDiscarded: { window.closeConfirmed = true; window.close(); }
    }
    onClosing: function(close) {
        if (!window.closeConfirmed && (window.backend.dirty || window.editorDirty) && !window.backend.active) { close.accepted = false; closeDialog.open(); return; }
        if (window.backend.performance.running) window.backend.performance.stop();
    }
    header: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.smallSpacing
            Label { text: qsTr("Astraeus"); font.bold: true; leftPadding: Kirigami.Units.largeSpacing }
            Label { text: qsTr("System management"); Layout.fillWidth: true }
            BusyIndicator { running: window.backend.loading; visible: running; implicitHeight: 28; implicitWidth: 28; Accessible.name: qsTr("Loading system information") }
            ToolButton { text: qsTr("Refresh"); icon.name: "view-refresh"; enabled: !window.backend.loading; onClicked: window.backend.refresh() }
        }
    }
    RowLayout {
        anchors.fill: parent
        spacing: 0
        Pane {
            Layout.fillHeight: true
            Layout.preferredWidth: 175
            ColumnLayout {
                anchors.fill: parent
                spacing: Kirigami.Units.smallSpacing
                Repeater {
                    model: [qsTr("Overview"), qsTr("Software"), qsTr("Configuration"), qsTr("Activity"), qsTr("Performance")]
                    delegate: ItemDelegate {
                        required property string modelData
                        required property int index
                        Layout.fillWidth: true
                        text: modelData
                        highlighted: window.section === index
                        onClicked: window.section = index
                    }
                }
                Item { Layout.fillHeight: true }
                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: window.backend.dirty ? qsTr("You have unapplied changes.") : qsTr("Changes are reviewed before they are applied.")
                    opacity: 0.8
                }
                Button {
                    objectName: "reviewButton"
                    Layout.fillWidth: true
                    text: window.backend.busy ? qsTr("Please wait…") : qsTr("Review changes")
                    enabled: window.editing
                    onClicked: window.backend.review()
                }
                Button { Layout.fillWidth: true; text: qsTr("Discard draft"); visible: window.backend.dirty; enabled: window.editing; onClicked: window.backend.discard() }
            }
        }
        Kirigami.Separator { Layout.fillHeight: true }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: Kirigami.Units.largeSpacing * 2
            spacing: Kirigami.Units.largeSpacing
            Kirigami.InlineMessage {
                objectName: "errorMessage"
                Layout.fillWidth: true
                // Kirigami's close button assigns visible, replacing a direct binding.
                Binding on visible { value: window.backend.error.length > 0 }
                text: State.message(window.backend.error)
                type: Kirigami.MessageType.Error
                showCloseButton: true
                onVisibleChanged: if (!visible && window.backend.error.length) window.backend.clearError()
            }
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: !!window.backend.status.live
                text: qsTr("Live session: you can inspect the system and review a draft. Applying changes requires an installed Astraeus system.")
                type: Kirigami.MessageType.Information
            }
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: !!window.backend.status.reboot_required
                text: qsTr("Restart required. The last change is awaiting a verified boot. Use Plasma’s Restart action when you are ready.")
                type: Kirigami.MessageType.Warning
            }
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: window.backend.notice.length > 0
                text: window.backend.notice
                type: Kirigami.MessageType.Information
            }
            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: window.section

                ScrollView {
                    clip: true
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width
                        spacing: Kirigami.Units.largeSpacing
                        Kirigami.Heading { text: qsTr("Your system"); level: 1 }
                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: qsTr("Manage software and saved configuration with recovery snapshots and verified boot checks.") }
                        Button {
                            objectName: "reviewUpdatesButton"
                            text: qsTr("Review updates")
                            icon.name: "system-software-update"
                            enabled: window.editing && !window.backend.dirty && !window.editorDirty
                            onClicked: window.backend.review()
                        }
                        Label { visible: window.backend.dirty || window.editorDirty; Layout.fillWidth: true; wrapMode: Text.WordWrap; text: qsTr("Finish or discard your draft before reviewing updates.") }
                        GroupBox {
                            title: qsTr("Current state")
                            Layout.fillWidth: true
                            ColumnLayout {
                                width: parent.width
                                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: window.backend.active ? qsTr("A system operation is in progress.") : window.backend.status.schema_version ? qsTr("System information loaded.") : qsTr("Waiting for system information…") }
                                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: qsTr("Configuration drift: ") + ((window.backend.status.drift || []).length ? qsTr("Changes detected outside the saved configuration") : window.backend.status.schema_version ? qsTr("None reported") : qsTr("Unavailable")) }
                                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: qsTr("Saved packages: ") + ((window.backend.status.configuration || {}).packages || []).length }
                            }
                        }
                        GroupBox {
                            title: qsTr("Health observations")
                            Layout.fillWidth: true
                            ColumnLayout {
                                width: parent.width
                                Repeater { model: State.observations(window.backend.status.health); delegate: Label { required property string modelData; Layout.fillWidth: true; wrapMode: Text.WordWrap; text: modelData; textFormat: Text.PlainText } }
                            }
                        }
                        GroupBox {
                            title: qsTr("Security observations")
                            Layout.fillWidth: true
                            ColumnLayout {
                                width: parent.width
                                Repeater { model: State.observations(window.backend.status.security); delegate: Label { required property string modelData; Layout.fillWidth: true; wrapMode: Text.WordWrap; text: modelData; textFormat: Text.PlainText } }
                            }
                        }
                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: qsTr("Package presence does not prove graphics or game compatibility. Physical hardware qualification is separate."); opacity: 0.8 }
                    }
                }

                ColumnLayout {
                    Kirigami.Heading { text: qsTr("Software"); level: 1 }
                    Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: qsTr("Selections build a draft. Nothing is installed or removed until you review and apply it.") }
                    TabBar {
                        id: softwareTabs
                        objectName: "softwareTabs"
                        Layout.fillWidth: true
                        TabButton { text: qsTr("Feature bundles") }
                        TabButton { text: qsTr("Packages"); onClicked: if (!window.backend.packages.length) window.backend.installed() }
                    }
                    StackLayout {
                        currentIndex: softwareTabs.currentIndex
                        Layout.fillHeight: true
                        Layout.fillWidth: true
                        ScrollView {
                            clip: true
                            contentWidth: availableWidth
                            ColumnLayout {
                                width: parent.width
                                Repeater {
                                    model: window.backend.features
                                    delegate: GroupBox {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        ColumnLayout {
                                            width: parent.width
                                            CheckBox {
                                                text: modelData.title || modelData.id
                                                checked: State.contains(window.backend.draft.gaming, modelData.id)
                                                enabled: window.editing && modelData.supported === true
                                                onClicked: window.backend.setFeature(modelData.id, checked)
                                            }
                                            Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: (modelData.packages || []).join(", "); textFormat: Text.PlainText }
                                            Label { visible: modelData.supported !== true; text: qsTr("This feature cannot be managed by Astraeus yet."); wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                        }
                                    }
                                }
                                Label { visible: !window.backend.features.length; text: window.backend.loading ? qsTr("Loading available features…") : qsTr("No feature catalog is available."); wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            }
                        }
                        ColumnLayout {
                            RowLayout {
                                Layout.fillWidth: true
                                TextField { id: searchField; objectName: "packageSearch"; Layout.fillWidth: true; placeholderText: qsTr("Search approved repositories"); Accessible.name: qsTr("Package search"); onAccepted: window.backend.search(text) }
                                Button { text: qsTr("Search"); onClicked: window.backend.search(searchField.text) }
                                Button { text: qsTr("Installed"); onClicked: { searchField.clear(); window.backend.installed(); } }
                            }
                            Label { text: qsTr("Checked packages are explicit choices in your draft. Required dependencies are resolved during review."); wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            ListView {
                                objectName: "packageList"
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                model: window.backend.packages
                                spacing: Kirigami.Units.smallSpacing
                                ScrollBar.vertical: ScrollBar {}
                                delegate: ItemDelegate {
                                    required property var modelData
                                    width: ListView.view.width
                                    contentItem: ColumnLayout {
                                        CheckBox {
                                            objectName: "packageChoice-" + modelData.name
                                            text: modelData.name + (modelData.protected ? qsTr(" (protected)") : "")
                                            checked: State.contains(window.backend.draft.packages, modelData.name)
                                            enabled: window.editing && modelData.selectable === true
                                            onClicked: window.backend.setPackage(modelData.name, checked)
                                        }
                                        Label { visible: modelData.protected === true; Layout.fillWidth: true; wrapMode: Text.WordWrap; text: modelData.selectable === true ? qsTr("Existing app retained when its choice is removed.") : qsTr("Protected system or unmanaged package. It cannot be selected here."); textFormat: Text.PlainText }
                                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: modelData.description || qsTr("No description available"); textFormat: Text.PlainText }
                                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: (modelData.repository || qsTr("Unknown repository")) + " · " + (modelData.version || qsTr("Unknown version")) + " · " + (modelData.installed_version ? qsTr("Installed: ") + modelData.installed_version : qsTr("Not installed")); textFormat: Text.PlainText; opacity: 0.8 }
                                    }
                                }
                                Label { anchors.centerIn: parent; visible: !window.backend.packages.length; text: window.backend.loading ? qsTr("Loading packages…") : qsTr("No packages to show.") }
                            }
                        }
                    }
                }

                ScrollView {
                    clip: true
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width
                        spacing: Kirigami.Units.largeSpacing
                        Kirigami.Heading { text: qsTr("Configuration"); level: 1 }
                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: qsTr("Save your software choices as a configuration. Imported or adopted choices remain a draft until applied.") }
                        Flow {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing
                            Button { text: qsTr("Import TOML…"); enabled: window.editing; onClicked: importDialog.open() }
                            Button { text: qsTr("Export saved configuration…"); enabled: !window.backend.busy; onClicked: exportDialog.open() }
                            Button { text: qsTr("Adopt installed packages"); enabled: window.editing; onClicked: window.backend.adopt() }
                        }
                        GroupBox {
                            Layout.fillWidth: true
                            title: qsTr("Current draft")
                            ColumnLayout {
                                width: parent.width
                                Label { text: qsTr("Packages"); font.bold: true }
                                Label { Layout.fillWidth: true; text: (window.backend.draft.packages || []).join(", ") || qsTr("No explicit packages selected"); wrapMode: Text.WordWrap; textFormat: Text.PlainText }
                                Label { text: qsTr("Feature bundles"); font.bold: true }
                                Label { Layout.fillWidth: true; text: (window.backend.draft.gaming || []).join(", ") || qsTr("No feature bundles selected"); wrapMode: Text.WordWrap; textFormat: Text.PlainText }
                                Label { text: qsTr("Provider choices"); font.bold: true }
                                Label { Layout.fillWidth: true; text: Object.keys(window.backend.draft.providers || {}).map(function(name) { return name + " → " + window.backend.draft.providers[name]; }).join("\n") || qsTr("None required"); wrapMode: Text.WordWrap; textFormat: Text.PlainText }
                            }
                        }
                        GroupBox {
                            Layout.fillWidth: true
                            title: qsTr("Edit or paste TOML")
                            ColumnLayout {
                                width: parent.width
                                TextArea { id: configurationEditor; objectName: "configurationEditor"; Layout.fillWidth: true; Layout.preferredHeight: 180; placeholderText: "schema_version = 1\npackages = []\ngaming = []\n\n[providers]"; selectByMouse: true; wrapMode: TextEdit.WrapAnywhere; Accessible.name: qsTr("TOML configuration editor"); onTextChanged: window.editorDirty = true }
                                RowLayout {
                                    Button { text: qsTr("Load saved text"); enabled: !window.backend.busy; onClicked: { configurationEditor.text = window.backend.configurationText; window.editorDirty = false; } }
                                    Button { text: qsTr("Validate into draft"); enabled: window.editing && configurationEditor.text.length > 0; onClicked: window.backend.parse(configurationEditor.text) }
                                }
                            }
                        }
                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: qsTr("Provider choices belong in the [providers] table. An ambiguous dependency is blocked until you choose an approved provider."); opacity: 0.8 }
                    }
                }

                ColumnLayout {
                    Kirigami.Heading { text: qsTr("Activity"); level: 1 }
                    GroupBox {
                        Layout.fillWidth: true
                        visible: !!window.backend.operation.operation_id
                        title: qsTr("Current operation")
                        ColumnLayout {
                            width: parent.width
                            Label { text: State.operationLabel(window.backend.operation); font.bold: true; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                            ProgressBar { Layout.fillWidth: true; indeterminate: true; visible: window.backend.active; Accessible.name: qsTr("System changes in progress") }
                            Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: window.backend.active ? qsTr("The system worker continues if you close this window. Do not shut down while it is applying changes.") : qsTr("Package changes require boot confirmation before they count as complete.") }
                            Label { Layout.fillWidth: true; wrapMode: Text.WrapAnywhere; visible: !!window.backend.operation.error; text: window.backend.operation.error || ""; textFormat: Text.PlainText }
                        }
                    }
                    SplitView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        orientation: Qt.Vertical
                        ListView {
                            SplitView.preferredHeight: 200
                            SplitView.minimumHeight: 100
                            clip: true
                            model: window.backend.history
                            ScrollBar.vertical: ScrollBar {}
                            delegate: ItemDelegate {
                                required property var modelData
                                width: ListView.view.width
                                text: "#" + modelData.id + " · " + State.stateLabel(modelData.state)
                                onClicked: window.selectedRecord = modelData
                            }
                            Label { visible: !window.backend.history.length; anchors.centerIn: parent; text: qsTr("No transaction history yet.") }
                        }
                        ScrollView {
                            SplitView.fillHeight: true
                            SplitView.minimumHeight: 120
                            TextArea { text: Object.keys(window.selectedRecord).length ? JSON.stringify(window.selectedRecord, null, 2) : qsTr("Choose a transaction to inspect its recorded changes and checks."); readOnly: true; selectByMouse: true; wrapMode: TextEdit.WrapAnywhere; Accessible.name: qsTr("Transaction details") }
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        text: qsTr("Recovery requires trusted offline media. <a href='file:///usr/share/doc/distroctl/offline-recovery.md'>Open the recovery guide</a>.")
                        onLinkActivated: function(link) { Qt.openUrlExternally(link); }
                    }
                }

                PerformancePage { backend: window.backend.performance }

                ScrollView {
                    clip: true
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width
                        spacing: Kirigami.Units.largeSpacing
                        Kirigami.Heading { text: qsTr("Review changes"); level: 1 }
                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: qsTr("Review every package change before continuing. Astraeus checks this plan again under the system lock after authentication.") }
                        Repeater {
                            model: window.backend.plan.blockers || []
                            delegate: Kirigami.InlineMessage { required property var modelData; Layout.fillWidth: true; visible: true; text: State.message(State.observation(modelData)); type: Kirigami.MessageType.Error }
                        }
                        Repeater {
                            model: window.backend.plan.warnings || []
                            delegate: Kirigami.InlineMessage { required property var modelData; Layout.fillWidth: true; visible: true; text: State.message(State.observation(modelData)); type: Kirigami.MessageType.Warning }
                        }
                        GroupBox {
                            Layout.fillWidth: true
                            title: qsTr("Configuration changes")
                            ColumnLayout {
                                width: parent.width
                                Repeater { model: State.configurationChanges(window.backend.plan.plan || {}); delegate: Label { required property string modelData; Layout.fillWidth: true; wrapMode: Text.WordWrap; text: modelData; textFormat: Text.PlainText } }
                                Label { visible: !State.configurationChanges(window.backend.plan.plan || {}).length; text: qsTr("No changes to saved software choices.") }
                            }
                        }
                        Repeater {
                            model: State.packageGroups(window.backend.plan.plan || {})
                            delegate: GroupBox {
                                required property var modelData
                                Layout.fillWidth: true
                                title: modelData.title
                                ColumnLayout {
                                    width: parent.width
                                    Repeater { model: modelData.changes; delegate: Label { required property var modelData; Layout.fillWidth: true; wrapMode: Text.WrapAnywhere; text: State.changeLabel(modelData); textFormat: Text.PlainText } }
                                }
                            }
                        }
                        Label { visible: !(window.packagePlan.changes || []).length; text: qsTr("No package file changes.") }
                        GroupBox {
                            Layout.fillWidth: true
                            title: qsTr("Install reason changes")
                            visible: State.reasonChanges(window.backend.plan.plan || {}).length > 0
                            ColumnLayout {
                                width: parent.width
                                Repeater { model: State.reasonChanges(window.backend.plan.plan || {}); delegate: Label { required property string modelData; Layout.fillWidth: true; wrapMode: Text.WordWrap; text: modelData; textFormat: Text.PlainText } }
                            }
                        }
                        GroupBox {
                            Layout.fillWidth: true
                            title: qsTr("Download and space")
                            ColumnLayout {
                                width: parent.width
                                Label { text: qsTr("Download upper bound: ") + State.bytes(window.packagePlan.download_bytes) }
                                Label { text: qsTr("Installed size change: ") + State.bytes(window.packagePlan.installed_delta_bytes) }
                            }
                        }
                        GroupBox {
                            Layout.fillWidth: true
                            title: qsTr("Package sources")
                            visible: (window.packagePlan.targets || []).length > 0
                            ColumnLayout {
                                width: parent.width
                                Repeater { model: window.packagePlan.targets || []; delegate: Label { required property var modelData; Layout.fillWidth: true; wrapMode: Text.WordWrap; text: modelData.name + " · " + (modelData.repository || qsTr("Repository unavailable")) + " · " + (modelData.version || ""); textFormat: Text.PlainText } }
                            }
                        }
                        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: qsTr("Recovery snapshot: ") + ((window.backend.plan.plan || {}).snapshot_required ? qsTr("Required") : qsTr("Not required by this plan")) }
                        Label { objectName: "restartExplanation"; Layout.fillWidth: true; wrapMode: Text.WordWrap; text: (window.backend.plan.plan || {}).snapshot_required ? qsTr("These changes need a verified restart before they count as complete, including configuration and install-reason changes. Your home files are outside the system snapshot.") : qsTr("This plan does not require a recovery snapshot. Review configuration and install-reason changes above.") }
                        Button {
                            objectName: "applyButton"
                            text: window.backend.busy ? qsTr("Waiting for authentication…") : qsTr("Authenticate and apply")
                            icon.name: "dialog-ok-apply"
                            enabled: State.canApply(window.backend.status, window.backend.plan, window.backend.busy, window.backend.active, window.backend.planValid)
                            onClicked: window.backend.apply()
                        }
                        Button { id: detailsToggle; checkable: true; text: checked ? qsTr("Hide complete plan") : qsTr("Show complete plan and provenance") }
                        GroupBox {
                            implicitWidth: 0
                            Layout.fillWidth: true
                            visible: detailsToggle.checked
                            title: qsTr("Plan details and provenance")
                            TextArea { width: parent.width; text: JSON.stringify(window.backend.plan.plan || {}, null, 2); readOnly: true; selectByMouse: true; wrapMode: TextEdit.WrapAnywhere; Accessible.name: qsTr("Complete resolved plan") }
                        }
                    }
                }
            }
        }
    }
}
