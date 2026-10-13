#pragma once
#include <QObject>
#include <QJsonDocument>
#include <QProcess>
#include <QSet>
#include <QTimer>
#include <QUrl>
#include <QVariantMap>
#include <functional>

class Controller : public QObject {
    Q_OBJECT
    Q_PROPERTY(QVariantMap status READ status NOTIFY changed)
    Q_PROPERTY(QVariantMap draft READ draft NOTIFY changed)
    Q_PROPERTY(QVariantMap plan READ plan NOTIFY changed)
    Q_PROPERTY(QVariantMap operation READ operation NOTIFY changed)
    Q_PROPERTY(QVariantList packages READ packages NOTIFY changed)
    Q_PROPERTY(QVariantList features READ features NOTIFY changed)
    Q_PROPERTY(QVariantList history READ history NOTIFY changed)
    Q_PROPERTY(QString error READ error NOTIFY changed)
    Q_PROPERTY(QString notice READ notice NOTIFY changed)
    Q_PROPERTY(QString configurationText READ configurationText NOTIFY changed)
    Q_PROPERTY(bool busy READ busy NOTIFY changed)
    Q_PROPERTY(bool loading READ loading NOTIFY changed)
    Q_PROPERTY(bool dirty READ dirty NOTIFY changed)
    Q_PROPERTY(bool active READ active NOTIFY changed)
    Q_PROPERTY(bool planValid READ planValid NOTIFY changed)
public:
    explicit Controller(QObject *parent = nullptr);
    Controller(QString executable, QString authenticator, QObject *parent = nullptr);
    QVariantMap status() const { return m_status; }
    QVariantMap draft() const { return m_draft; }
    QVariantMap plan() const { return m_plan; }
    QVariantMap operation() const { return m_operation; }
    QVariantList packages() const { return m_packages; }
    QVariantList features() const { return m_features; }
    QVariantList history() const { return m_history; }
    QString error() const { return m_error; }
    QString notice() const { return m_notice; }
    QString configurationText() const { return m_configurationText; }
    bool busy() const;
    bool loading() const { return !m_pending.isEmpty(); }
    bool dirty() const { return m_dirty; }
    bool active() const;
    bool planValid() const { return m_planValid; }
    Q_INVOKABLE void refresh();
    Q_INVOKABLE void search(const QString &query);
    Q_INVOKABLE void installed();
    Q_INVOKABLE void setPackage(const QString &name, bool selected);
    Q_INVOKABLE void setFeature(const QString &name, bool selected);
    Q_INVOKABLE void setProvider(const QString &name, const QString &provider);
    Q_INVOKABLE void discard();
    Q_INVOKABLE void review();
    Q_INVOKABLE void apply();
    Q_INVOKABLE void adopt();
    Q_INVOKABLE void parse(const QString &text);
    Q_INVOKABLE void importFile(const QUrl &url);
    Q_INVOKABLE void exportFile(const QUrl &url);
    Q_INVOKABLE void clearError();
signals:
    void changed();
    void planReady();
    void submitted();
private:
    using Callback = std::function<void(const QJsonDocument &)>;
    void request(const QString &channel, QStringList arguments, QByteArray input, Callback callback, bool privileged = false);
    void poll();
    void editSelection(const QString &key, const QString &name, bool selected);
    void acceptDraft(const QVariantMap &configuration);
    void fail(const QString &message);
    QString m_executable, m_authenticator, m_error, m_notice, m_configurationText, m_operationId;
    QVariantMap m_status, m_draft, m_plan, m_operation;
    QVariantList m_packages, m_features, m_history;
    QSet<QString> m_pending;
    QTimer m_poll;
    bool m_dirty = false, m_haveDraft = false, m_planValid = false;
    quint64 m_searchRevision = 0, m_draftRevision = 0;
};
