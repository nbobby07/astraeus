#include "controller.h"
#include <QGuiApplication>
#include <QQmlApplicationEngine>

int main(int argc, char **argv)
{
    QGuiApplication app(argc, argv);
    app.setApplicationName("Astraeus Control Center");
    app.setOrganizationName("Astraeus");
    app.setDesktopFileName("org.astraeus.ControlCenter");
    Controller controller;
    QQmlApplicationEngine engine;
    engine.setInitialProperties({{"backend", QVariant::fromValue(&controller)}});
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app,
                     [] { QCoreApplication::exit(1); }, Qt::QueuedConnection);
    engine.loadFromModule("org.astraeus.control", "Main");
    controller.refresh();
    return app.exec();
}
