#include "performance.h"
#include <QFile>
#include <QTemporaryDir>
#include <QtTest>

class PerformanceTest : public QObject {
    Q_OBJECT
    QTemporaryDir directory;
    QString fixture(const QString &mode = "normal") {
        const auto path = directory.filePath("backend-" + mode);
        QFile f(path); if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate)) return {};
        QByteArray source = R"PY(#!/usr/bin/python3
import json,sys,time,signal
mode='MODE'
args=sys.argv[1:]
assert args[0]=='performance' and args[-1]=='--json'
action=args[1]
sample=dict(elapsed_seconds=1.0,cpu_busy_percent=None,unavailable=['Thermal sensors'],temperatures=[],pressure_avg10_percent={})
context=dict(virtual_machine=True)
report=dict(schema_version=1,id='a'*32,kind='record',state='completed',context=context,samples=[sample],measurements=[],warnings=[],elapsed_seconds=1.0,failure=None)
def emit(kind,data):print(json.dumps(dict(schema_version=1,event=kind,data=data)),flush=True)
if action=='status': print(json.dumps(dict(schema_version=2 if mode=='future' else 1,context=context,sample=sample,baseline_blockers=[])))
elif action=='list': print(json.dumps(dict(schema_version=1,runs=[])))
elif action in ('show','export'): print(json.dumps(report))
elif action=='compare': print(json.dumps(dict(schema_version=1,comparable=False,blockers=['incompatible'],measurements=[],context_changes={})))
elif action in ('record','baseline'):
 if mode=='malformed': print('{malformed',flush=True);time.sleep(30)
 else:
  emit('started',dict(id='a'*32,kind=action,requested_seconds=60))
  emit('sample',sample)
  if mode=='cancel':
   def cancel(*_):
    report.update(state='cancelled',failure='cancelled by caller');emit('result',report);sys.exit(1)
   signal.signal(signal.SIGTERM,cancel);time.sleep(30)
  elif mode=='missing-result': pass
  elif mode=='false-success': report.update(state='completed',samples=[]);emit('result',report)
  else: emit('result',report)
)PY";
        source.replace("MODE", mode.toUtf8()); f.write(source); f.close();
        f.setPermissions(QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner); return path;
    }
private slots:
    void statusAndCompletedRecording() {
        Performance p(fixture()); p.refresh(); QTRY_VERIFY(!p.loading());
        QVERIFY(p.status().value("context").toMap().value("virtual_machine").toBool());
        p.start("record"); QTRY_VERIFY(!p.running()); QCOMPARE(p.result().value("state").toString(),"completed"); QVERIFY(p.error().isEmpty());
    }
    void malformedEventsNeverComplete() {
        Performance p(fixture("malformed"));p.start("record");QTRY_VERIFY(!p.running()); QVERIFY(p.result().isEmpty()); QVERIFY(!p.error().isEmpty());
    }
    void futureStatusCannotEnableBaseline() {
        Performance p(fixture("future"));p.refresh();QTRY_VERIFY(!p.loading());QVERIFY(p.status().isEmpty());p.start("baseline");QVERIFY(!p.running());
    }
    void missingFinalRecordIsIncomplete() {
        Performance p(fixture("missing-result"));p.start("record");QTRY_VERIFY(!p.running());QVERIFY(p.result().isEmpty());QVERIFY(p.error().contains("incomplete"));
    }
    void emptySuccessCannotComplete() {
        Performance p(fixture("false-success"));p.start("record");QTRY_VERIFY(!p.running());QVERIFY(p.result().isEmpty());QVERIFY(!p.error().isEmpty());
    }
    void cancellationPreservesCancelledResult() {
        Performance p(fixture("cancel"));p.start("record");QTRY_VERIFY(!p.sample().isEmpty());p.stop();QTRY_VERIFY(!p.running());QCOMPARE(p.result().value("state").toString(),"cancelled");
    }
    void managementBlockRefusesStart() {
        Performance p(fixture());p.setBlocked(true);p.start("record");QVERIFY(!p.running());QVERIFY(!p.error().isEmpty());
    }
    void exportAndIdentifiersAreBounded() {
        Performance p(fixture());p.show("../escape");QVERIFY(p.result().isEmpty());p.exportFile(QString(32,'a'),QUrl::fromLocalFile(directory.filePath("export.json")));QTRY_VERIFY(!p.loading());QFile f(directory.filePath("export.json"));QVERIFY(f.open(QIODevice::ReadOnly));QVERIFY(f.readAll().contains("completed"));
    }
    void destructorStopsItsMeasurement() {
        auto *p = new Performance(fixture("cancel"));p->start("record");QTRY_VERIFY(!p->sample().isEmpty());delete p;
    }
};
QTEST_GUILESS_MAIN(PerformanceTest)
#include "performance_test.moc"
