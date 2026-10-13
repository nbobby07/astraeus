#include "controller.h"
#include <QApplication>
#include <QQmlApplicationEngine>
#include <QQuickStyle>

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    app.setApplicationName("Astraeus Control Center");
    app.setOrganizationName("Astraeus");
    app.setDesktopFileName("org.astraeus.ControlCenter");
    if (qEnvironmentVariableIsEmpty("QT_QUICK_CONTROLS_STYLE"))
        QQuickStyle::setStyle("org.kde.desktop");
    Controller controller;
    QQmlApplicationEngine engine;
    engine.setInitialProperties({{"backend", QVariant::fromValue(&controller)}});
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app,
                     [] { QCoreApplication::exit(1); }, Qt::QueuedConnection);
    engine.loadFromModule("org.astraeus.control", "Main");
    controller.refresh();
    return app.exec();
}
