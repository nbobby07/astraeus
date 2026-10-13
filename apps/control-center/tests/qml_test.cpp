#include <QtQuickTest/quicktest.h>
#include <QFile>
#include <QJsonDocument>
#include <QQmlContext>
#include <QQmlEngine>
class Setup : public QObject {
    Q_OBJECT
public slots:
    void qmlEngineAvailable(QQmlEngine *engine) {
        engine->rootContext()->setContextProperty("testOutputDirectory", QCoreApplication::applicationDirPath());
        QFile file(QStringLiteral(QUICK_TEST_SOURCE_DIR "/fixtures/install-plan.json"));
        if (!file.open(QIODevice::ReadOnly)) qFatal("Rust-generated plan fixture is missing");
        engine->rootContext()->setContextProperty("installPlanFixture", QJsonDocument::fromJson(file.readAll()).toVariant());
        QFile blocked(QStringLiteral(QUICK_TEST_SOURCE_DIR "/fixtures/blocked-plan.json"));
        if (!blocked.open(QIODevice::ReadOnly)) qFatal("Rust-generated blocked plan fixture is missing");
        engine->rootContext()->setContextProperty("blockedPlanFixture", QJsonDocument::fromJson(blocked.readAll()).toVariant());
    }
};
QUICK_TEST_MAIN_WITH_SETUP(astraeus_control_center, Setup)
#include "qml_test.moc"
