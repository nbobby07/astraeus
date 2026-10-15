pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import org.kde.kirigami as Kirigami
import "State.js" as State

ScrollView {
    id: page
    required property var backend
    clip: true
    contentWidth: availableWidth
    function metric(value, unit) { return value === undefined || value === null ? qsTr("Unavailable") : Number(value).toFixed(1) + " " + unit; }
    function runName(run) { return (run.kind || qsTr("Unknown")) + " · " + run.state + " · " + run.id.slice(0, 8); }
    onVisibleChanged: if (visible) backend.refresh()
    Timer { interval: 3000; repeat: true; running: page.visible && !page.backend.running; onTriggered: page.backend.observe() }
    FileDialog {
        id: exportDialog
        title: qsTr("Export performance result")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "json"
        nameFilters: [qsTr("JSON report (*.json)")]
        onAccepted: page.backend.exportFile(page.backend.result.id, selectedFile)
    }
    Dialog {
        id: baselineDialog
        title: qsTr("Run a short system baseline?")
        modal: true
        focus: true
        anchors.centerIn: parent
        width: Math.min(page.width - 24, 540)
        standardButtons: Dialog.Ok | Dialog.Cancel
        onOpened: standardButton(Dialog.Ok).forceActiveFocus()
        contentItem: Label { wrapMode: Text.WordWrap; text: qsTr("Allow roughly two minutes. The tests use at most 4 CPU threads, 128 MiB of memory and one 128 MiB scratch file. Close demanding applications for a useful comparison. You can stop at any time. Results include filesystem caching and are development measurements.") }
        onAccepted: page.backend.start("baseline")
    }
    ColumnLayout {
        width: parent.width
        spacing: Kirigami.Units.largeSpacing
        Kirigami.Heading { text: qsTr("Performance"); level: 1 }
        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: qsTr("Observe this system, save a bounded baseline and compare repeated runs.") }
        Kirigami.InlineMessage { Layout.fillWidth: true; visible: page.backend.error.length > 0; text: State.message(page.backend.error); type: Kirigami.MessageType.Error }
        Label {
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            text: (page.backend.status.context || {}).virtual_machine === true ? qsTr("Virtual machine: these results describe this guest. Physical CPU, storage, thermal and GPU performance remain unqualified.") : qsTr("Measurements depend on workload, background activity, power and temperature. Missing sensors remain unavailable.")
        }
        GroupBox {
            Layout.fillWidth: true; title: qsTr("Current observations")
            ColumnLayout {
                width: parent.width
                Label { objectName: "cpuMetric"; text: qsTr("CPU busy: ") + page.metric(page.backend.sample.cpu_busy_percent, "%"); Accessible.name: text }
                Label { text: qsTr("Memory available: ") + page.metric(page.backend.sample.memory_available_bytes === null || page.backend.sample.memory_available_bytes === undefined ? null : page.backend.sample.memory_available_bytes / 1073741824, "GiB") }
                Label { text: qsTr("Disk read: ") + page.metric(page.backend.sample.disk_read_bytes_per_second === null || page.backend.sample.disk_read_bytes_per_second === undefined ? null : page.backend.sample.disk_read_bytes_per_second / 1048576, "MiB/s") }
                Label { text: qsTr("Disk write: ") + page.metric(page.backend.sample.disk_write_bytes_per_second === null || page.backend.sample.disk_write_bytes_per_second === undefined ? null : page.backend.sample.disk_write_bytes_per_second / 1048576, "MiB/s") }
                Repeater { model: page.backend.sample.temperatures || []; delegate: Label { required property var modelData; text: modelData.label + ": " + page.metric(modelData.celsius, "°C"); textFormat: Text.PlainText } }
                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: qsTr("Unavailable: ") + (page.backend.sample.unavailable || []).join(", "); visible: (page.backend.sample.unavailable || []).length > 0 }
            }
        }
        Repeater { model: page.backend.status.baseline_blockers || []; delegate: Label { required property string modelData; Layout.fillWidth: true; wrapMode: Text.WordWrap; text: modelData; textFormat: Text.PlainText } }
        RowLayout {
            Layout.fillWidth: true
            Button { objectName: "recordPerformance"; text: qsTr("Record 60 seconds"); enabled: !page.backend.running; onClicked: page.backend.start("record") }
            Button { objectName: "baselinePerformance"; text: qsTr("Run baseline…"); enabled: !page.backend.running && !page.backend.blocked && !!page.backend.status.schema_version && !(page.backend.status.baseline_blockers || []).length; onClicked: baselineDialog.open() }
            Button { objectName: "stopPerformance"; text: qsTr("Stop"); enabled: page.backend.running; onClicked: page.backend.stop() }
        }
        ProgressBar { Layout.fillWidth: true; visible: page.backend.running; indeterminate: true; Accessible.name: qsTr("Measurement in progress") }
        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: page.backend.phase; textFormat: Text.PlainText; visible: text.length > 0 }
        GroupBox {
            Layout.fillWidth: true; title: qsTr("Saved results")
            ColumnLayout {
                width: parent.width
                Button { text: qsTr("Refresh saved runs"); enabled: !page.backend.loading; onClicked: page.backend.refresh() }
                Label { text: qsTr("No saved measurements yet."); visible: !page.backend.runs.length }
                ComboBox { id: selectedRun; objectName: "performanceRun"; Layout.fillWidth: true; model: page.backend.runs; textRole: "id"; valueRole: "id"; Accessible.name: qsTr("Saved performance run"); displayText: currentIndex >= 0 ? page.runName(page.backend.runs[currentIndex]) : qsTr("Choose a run") }
                Button { text: qsTr("Open result"); enabled: selectedRun.currentIndex >= 0 && !page.backend.running; onClicked: page.backend.show(selectedRun.currentValue) }
                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: page.backend.result.id ? qsTr("Result: ") + page.backend.result.state + " · " + page.metric(page.backend.result.elapsed_seconds, "s") : ""; textFormat: Text.PlainText }
                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; visible: !!page.backend.result.context; text: qsTr("CPU: ") + ((page.backend.result.context || {}).cpu_model || qsTr("Unavailable")) + qsTr(" · Kernel: ") + ((page.backend.result.context || {}).kernel || qsTr("Unavailable")); textFormat: Text.PlainText }
                Repeater {
                    model: page.backend.result.measurements || []
                    delegate: Label { required property var modelData; Layout.fillWidth: true; wrapMode: Text.WordWrap; text: modelData.workload.name + ": " + modelData.values.map(function(v) { return Number(v).toFixed(1); }).join(", ") + " " + modelData.unit; textFormat: Text.PlainText }
                }
                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; visible: !!page.backend.result.failure; text: page.backend.result.failure || ""; textFormat: Text.PlainText }
                Button { text: qsTr("Export opened result…"); enabled: !!page.backend.result.id && !page.backend.running; onClicked: exportDialog.open() }
            }
        }
        GroupBox {
            Layout.fillWidth: true; title: qsTr("Compare baselines")
            ColumnLayout {
                width: parent.width
                ComboBox { id: before; Layout.fillWidth: true; model: page.backend.runs; textRole: "id"; valueRole: "id"; Accessible.name: qsTr("Baseline before"); displayText: currentIndex >= 0 ? page.runName(page.backend.runs[currentIndex]) : qsTr("Choose before") }
                ComboBox { id: after; Layout.fillWidth: true; model: page.backend.runs; textRole: "id"; valueRole: "id"; Accessible.name: qsTr("Baseline after"); displayText: currentIndex >= 0 ? page.runName(page.backend.runs[currentIndex]) : qsTr("Choose after") }
                Button { text: qsTr("Compare selected runs"); enabled: before.currentIndex >= 0 && after.currentIndex >= 0 && !page.backend.running; onClicked: page.backend.compare(before.currentValue, after.currentValue) }
                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: (page.backend.comparison.blockers || []).join("\n"); textFormat: Text.PlainText }
                Repeater {
                    model: page.backend.comparison.measurements || []
                    delegate: Label { required property var modelData; Layout.fillWidth: true; wrapMode: Text.WordWrap; text: modelData.workload.name + ": " + page.metric(modelData.before.median, modelData.unit) + " → " + page.metric(modelData.after.median, modelData.unit) + " (" + page.metric(modelData.change_percent, "%") + ")\n" + qsTr("Spread: ") + page.metric(modelData.before.spread, modelData.unit) + " → " + page.metric(modelData.after.spread, modelData.unit) + "\n" + qsTr("Repetitions: ") + modelData.before.values.map(function(v) { return Number(v).toFixed(1); }).join(", ") + " → " + modelData.after.values.map(function(v) { return Number(v).toFixed(1); }).join(", "); textFormat: Text.PlainText }
                }
                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; visible: !!page.backend.comparison.conditions; text: qsTr("Observed CPU busy median: ") + page.metric(((page.backend.comparison.conditions || {}).before || {}).cpu_busy_percent_median, "%") + " → " + page.metric(((page.backend.comparison.conditions || {}).after || {}).cpu_busy_percent_median, "%") + "\n" + qsTr("Peak observed temperature: ") + page.metric(((page.backend.comparison.conditions || {}).before || {}).peak_observed_celsius, "°C") + " → " + page.metric(((page.backend.comparison.conditions || {}).after || {}).peak_observed_celsius, "°C") }
                Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: page.backend.comparison.warning || ""; textFormat: Text.PlainText }
                TextArea { Layout.fillWidth: true; visible: Object.keys(page.backend.comparison.context_changes || {}).length > 0; text: JSON.stringify(page.backend.comparison.context_changes || {}, null, 2); readOnly: true; wrapMode: TextEdit.WrapAnywhere; Accessible.name: qsTr("Comparison context differences") }
            }
        }
        Label { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: qsTr("Results stay in your user account until you export them. Closing Control Center stops a measurement. Package transactions continue independently.") }
    }
}
