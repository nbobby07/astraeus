#include "controller.h"
#include <QFile>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QtTest>

class ControllerTest : public QObject {
    Q_OBJECT
    QTemporaryDir directory;
    QString executable;

    void fixture(const QString &mode = "normal") {
        executable = directory.filePath("distroctl-fixture");
        QFile::remove(directory.filePath("plan.json"));
        QVERIFY(QFile::copy(QFINDTESTDATA("fixtures/install-plan.json"), directory.filePath("plan.json")));
        QFile script(executable);
        QVERIFY(script.open(QIODevice::WriteOnly | QIODevice::Truncate));
        const QByteArray python = R"PY(#!/usr/bin/python3
import json, pathlib, sys
args = sys.argv[1:]
mode = 'MODE'
with open(pathlib.Path(__file__).with_name('calls'), 'a') as log:
    log.write(json.dumps(args) + '\n')
if args[0] == '--disable-internal-agent':
    if mode == 'cancel': sys.exit(126)
    if mode == 'deny': sys.exit(127)
    args = args[2:]
if mode == 'malformed':
    print('this is not JSON'); sys.exit()
config = dict(schema_version=1, packages=['nano'], gaming=[], providers={})
result = dict(schema_version=1)
if args[0] == 'history': result = []
elif args[1] == 'status': result.update(configuration=config, drift=[], active_operation=dict(operation_id='b'*32,state='awaiting_boot') if mode=='reconnect' else None, reboot_required=mode=='reconnect', live=mode=='live')
elif args[1] == 'features': result.update(features=[dict(id='core', title='Steam Core', packages=['steam'], supported=True)])
elif args[1] == 'packages': result.update(packages=[dict(name='nano', version='1', description='Editor', repository='extra', installed_version='1', protected=True, system_package=False, selectable=True)])
elif args[1] in ('adopt', 'export'): result.update(configuration=config, toml='schema_version = 1\npackages = ["nano"]\ngaming = []\n[providers]\n')
elif args[1] == 'parse':
    text=sys.stdin.read()
    if text == 'invalid': print('invalid TOML', file=sys.stderr); sys.exit(1)
    result.update(configuration=dict(config, packages=['kate']))
elif args[1] == 'plan':
    config=json.load(sys.stdin)
    result=json.loads(pathlib.Path(__file__).with_name('plan.json').read_text())
    if mode == 'snapshot-missing': result['plan'].pop('snapshot_required')
    if mode == 'snapshot-false': result['plan']['snapshot_required']=False
    if mode == 'boot-missing': result['plan']['boot'].pop('regenerate_uki')
    if mode == 'boot-false': result['plan']['boot']['regenerate_uki']=False
    if mode == 'reasons-missing': result['plan']['management'].pop('reasons_after')
    if mode == 'targets-missing': result['plan']['packages']['targets']=[]
    if mode == 'blocked': result.update(executable=False,blockers=['A previous transaction is awaiting boot confirmation.'])
elif args[1] == 'submit':
    request=json.load(sys.stdin)
    assert request['expected_plan']==json.loads(pathlib.Path(__file__).with_name('plan.json').read_text())['plan_id']
    assert request['config']['schema_version']==1
    result.update(operation_id='b'*32)
elif args[1] == 'operation': result.update(operation_id='b'*32, state='awaiting_boot', transaction=dict(id=1,state='awaiting_boot'), error=None)
if mode == 'schema' and isinstance(result,dict): result['schema_version']=2
if mode == 'recovery' and args[1:2] == ['status']:
    result.update(configuration=None,configuration_available=False,recovery_required=True,health={'kernel':'observed'},security={'state':'unknown'})
print(json.dumps(result))
)PY";
        auto source = python;
        source.replace("MODE", mode.toUtf8());
        QCOMPARE(script.write(source), source.size());
        script.close();
        QVERIFY(script.setPermissions(QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner));
        QFile::remove(directory.filePath("calls"));
    }
    QString calls() {
        QFile log(directory.filePath("calls"));
        if (!log.open(QIODevice::ReadOnly)) return {};
        return QString::fromUtf8(log.readAll());
    }
private slots:
    void missingExecutableIsReported() {
        Controller controller(directory.filePath("missing"), directory.filePath("missing-authenticator"));
        controller.refresh();
        QTRY_VERIFY(!controller.loading());
        QVERIFY(controller.error().contains("Could not start"));
        QVERIFY(controller.draft().isEmpty());
    }
    void unavailableConfigurationPreservesObservedOverview() {
        fixture("recovery");
        Controller controller(executable, executable);
        controller.refresh(); QTRY_VERIFY(!controller.loading());
        QVERIFY(controller.status().value("recovery_required").toBool());
        QCOMPARE(controller.status().value("health").toMap().value("kernel").toString(), QString("observed"));
        QVERIFY(controller.error().contains("configuration is unavailable"));
        controller.review(); controller.apply();
        QVERIFY(!calls().contains("submit"));
        QVERIFY(!controller.planValid());
    }
    void startupIsReadOnlyAndDraftInvalidatesPlan() {
        fixture();
        Controller controller(executable, executable);
        controller.refresh();
        QTRY_VERIFY(!controller.loading());
        QVERIFY(controller.error().isEmpty());
        QCOMPARE(controller.draft().value("packages").toStringList(), QStringList{"nano"});
        QVERIFY(!calls().contains("submit"));
        QSignalSpy planned(&controller, &Controller::planReady);
        controller.setPackage("kate", true);
        controller.review();
        QTRY_COMPARE(planned.size(), 1);
        QVERIFY(controller.plan().value("executable").toBool());
        QVERIFY(controller.planValid());
        controller.setPackage("kate", false);
        QVERIFY(controller.plan().isEmpty());
        QVERIFY(controller.dirty());
        QVERIFY(!controller.draft().value("packages").toStringList().contains("kate"));
        controller.discard();
        QVERIFY(!controller.dirty());
        QCOMPARE(controller.draft().value("packages").toStringList(), QStringList{"nano"});
    }
    void packageSelectionDoesNotDiscardRemovalProtection() {
        fixture();
        Controller controller(executable, executable);
        controller.installed();
        QTRY_COMPARE(controller.packages().size(), 1);
        const auto package = controller.packages().first().toMap();
        QVERIFY(package.value("protected").toBool());
        QVERIFY(package.value("selectable").toBool());
        QVERIFY(!calls().contains("submit"));
    }
    void malformedAndUnknownSchemaAreRejected_data() {
        QTest::addColumn<QString>("mode");
        QTest::newRow("invalid-json") << QString("malformed");
        QTest::newRow("future-schema") << QString("schema");
    }
    void malformedAndUnknownSchemaAreRejected() {
        QFETCH(QString, mode);
        fixture(mode);
        Controller controller(executable, executable);
        controller.refresh();
        QTRY_VERIFY(!controller.loading());
        QVERIFY(!controller.error().isEmpty());
        QVERIFY(controller.draft().isEmpty());
        controller.apply();
        QVERIFY(!calls().contains("submit"));
    }
    void authenticationCancellationAndDenial_data() {
        QTest::addColumn<QString>("mode");
        QTest::addColumn<QString>("message");
        QTest::newRow("cancel") << QString("cancel") << QString("canceled");
        QTest::newRow("deny") << QString("deny") << QString("denied");
    }
    void authenticationCancellationAndDenial() {
        QFETCH(QString, mode); QFETCH(QString, message);
        fixture(mode);
        Controller controller(executable, executable);
        controller.refresh();
        QTRY_VERIFY(!controller.loading());
        controller.setPackage("kate", true);
        controller.review();
        QTRY_VERIFY(!controller.loading());
        controller.apply();
        QTRY_VERIFY(!controller.loading());
        QVERIFY2(controller.error().contains(message), qPrintable(controller.error()));
        QVERIFY(controller.operation().isEmpty());
        QVERIFY(!controller.active());
    }
    void liveSessionCannotSubmit() {
        fixture("live");
        Controller controller(executable, executable);
        controller.refresh();
        QTRY_VERIFY(!controller.loading());
        controller.setPackage("kate", true);
        controller.review();
        QTRY_VERIFY(!controller.loading());
        controller.apply();
        QVERIFY(!calls().contains("submit"));
    }
    void contradictoryPlanCannotAuthenticate_data() {
        QTest::addColumn<QString>("mode");
        for (const auto &name : {"snapshot-missing", "snapshot-false", "boot-missing", "boot-false", "reasons-missing", "targets-missing"})
            QTest::newRow(name) << QString(name);
    }
    void contradictoryPlanCannotAuthenticate() {
        QFETCH(QString, mode);
        fixture(mode);
        Controller controller(executable, executable);
        controller.refresh(); QTRY_VERIFY(!controller.loading());
        controller.setPackage("kate", true);
        controller.review(); QTRY_VERIFY(!controller.loading());
        QVERIFY(!controller.planValid());
        QVERIFY(controller.error().contains("contradictory"));
        controller.apply();
        QVERIFY(!calls().contains("submit"));
    }
    void validBlockedPlanRemainsReviewableWithoutAuthentication() {
        fixture("blocked");
        Controller controller(executable, executable);
        controller.refresh(); QTRY_VERIFY(!controller.loading());
        controller.setPackage("kate", true);
        QSignalSpy planned(&controller, &Controller::planReady);
        controller.review(); QTRY_VERIFY(!controller.loading());
        QCOMPARE(planned.size(), 1);
        QVERIFY(!controller.planValid());
        QVERIFY(!controller.plan().value("blockers").toList().isEmpty());
        controller.apply();
        QVERIFY(!calls().contains("submit"));
    }
    void requestAndOperationSurviveFrontendState() {
        fixture();
        Controller controller(executable, executable);
        controller.refresh();
        QTRY_VERIFY(!controller.loading());
        controller.setPackage("kate", true);
        controller.review();
        QTRY_VERIFY(!controller.loading());
        controller.apply();
        QTRY_COMPARE(controller.operation().value("state").toString(), QString("awaiting_boot"));
        QTRY_VERIFY(!controller.loading());
        QVERIFY(!controller.active());
        QVERIFY(!controller.dirty());
        QVERIFY(controller.error().isEmpty());
    }
    void reopenPendingBootDoesNotRestartPollingOrSubmit() {
        fixture("reconnect");
        Controller controller(executable, executable);
        controller.refresh();
        QTRY_VERIFY(!controller.loading());
        QCOMPARE(controller.operation().value("state").toString(), QString("awaiting_boot"));
        QVERIFY(!controller.active());
        QVERIFY(!calls().contains("operation\""));
        controller.apply();
        QVERIFY(!calls().contains("submit"));
    }
    void importValidationPreservesDraftAndExportIsAtomic() {
        fixture();
        Controller controller(executable, executable);
        controller.refresh();
        QTRY_VERIFY(!controller.loading());
        const auto original = controller.draft();
        QSignalSpy parsed(&controller, &Controller::configurationParsed);
        controller.parse("invalid");
        QTRY_VERIFY(!controller.loading());
        QCOMPARE(parsed.size(), 0);
        QCOMPARE(controller.draft(), original);
        QVERIFY(!controller.error().isEmpty());
        controller.clearError();
        controller.parse("schema_version = 1");
        QTRY_VERIFY(!controller.loading());
        QCOMPARE(parsed.size(), 1);
        QCOMPARE(parsed.first().first().toString(), QString("schema_version = 1"));
        QCOMPARE(controller.draft().value("packages").toStringList(), QStringList{"kate"});
        const auto destination = directory.filePath("system.toml");
        controller.exportFile(QUrl::fromLocalFile(destination));
        QTRY_VERIFY(!controller.loading());
        QFile exported(destination);
        QVERIFY(exported.open(QIODevice::ReadOnly));
        QVERIFY(exported.readAll().contains("nano"));
        QVERIFY(controller.dirty());
        controller.parse(QString(256 * 1024 + 1, 'a'));
        QVERIFY(controller.error().contains("256 KiB"));
        QVERIFY(!controller.loading());
    }
};
QTEST_GUILESS_MAIN(ControllerTest)
#include "controller_test.moc"
