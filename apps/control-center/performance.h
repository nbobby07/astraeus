#pragma once
#include <QObject>
#include <QProcess>
#include <QSet>
#include <QUrl>
#include <QVariantMap>

class Performance : public QObject {
    Q_OBJECT
    Q_PROPERTY(QVariantMap status READ status NOTIFY changed)
    Q_PROPERTY(QVariantList runs READ runs NOTIFY changed)
    Q_PROPERTY(QVariantMap result READ result NOTIFY changed)
    Q_PROPERTY(QVariantMap comparison READ comparison NOTIFY changed)
    Q_PROPERTY(QVariantMap sample READ sample NOTIFY changed)
    Q_PROPERTY(QString phase READ phase NOTIFY changed)
    Q_PROPERTY(QString error READ error NOTIFY changed)
    Q_PROPERTY(bool running READ running NOTIFY changed)
    Q_PROPERTY(bool loading READ loading NOTIFY changed)
    Q_PROPERTY(bool blocked READ blocked NOTIFY changed)
public:
    explicit Performance(QString executable, QObject *parent = nullptr);
    ~Performance() override;
    QVariantMap status() const { return m_status; }
    QVariantList runs() const { return m_runs; }
    QVariantMap result() const { return m_result; }
    QVariantMap comparison() const { return m_comparison; }
    QVariantMap sample() const { return m_sample; }
    QString phase() const { return m_phase; }
    QString error() const { return m_error; }
    bool running() const { return m_run != nullptr; }
    bool loading() const { return !m_queries.isEmpty(); }
    bool blocked() const { return m_blocked; }
    void setBlocked(bool blocked);
    Q_INVOKABLE void refresh();
    Q_INVOKABLE void observe();
    Q_INVOKABLE void start(const QString &kind);
    Q_INVOKABLE void stop();
    Q_INVOKABLE void show(const QString &id);
    Q_INVOKABLE void compare(const QString &before, const QString &after);
    Q_INVOKABLE void exportFile(const QString &id, const QUrl &url);
signals:
    void changed();
private:
    void query(const QString &channel, const QStringList &arguments, const QUrl &exportUrl = {});
    void consume();
    void fail(const QString &error);
    QString m_executable, m_phase, m_error, m_runId;
    QVariantMap m_status, m_result, m_comparison, m_sample;
    QVariantList m_runs;
    QSet<QString> m_queries;
    QProcess *m_run = nullptr;
    QByteArray m_buffer, m_diagnostic;
    qint64 m_received = 0;
    bool m_blocked = false, m_gotResult = false;
};
