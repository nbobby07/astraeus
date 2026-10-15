#include "controller.h"
#include <QFile>
#include <QJsonArray>
#include <QJsonObject>
#include <QRegularExpression>
#include <QSaveFile>
#include <algorithm>
#include <cmath>
#include <memory>

namespace {
constexpr qint64 maximumOutput = 16 * 1024 * 1024;
constexpr qint64 maximumConfiguration = 256 * 1024;
bool validConfiguration(const QVariantMap &config)
{
    const auto object = QJsonObject::fromVariantMap(config);
    if (object.value("schema_version").toInt() != 1 || !object.value("packages").isArray()
        || !object.value("gaming").isArray() || !object.value("providers").isObject()) return false;
    for (const auto &key : {"packages", "gaming"})
        for (const auto &value : object.value(key).toArray()) if (!value.isString()) return false;
    for (const auto &value : object.value("providers").toObject()) if (!value.isString()) return false;
    return true;
}
bool terminal(const QString &state)
{
    return QStringList{"succeeded", "awaiting_boot", "failed", "rollback_required", "rolled_back", "rejected"}.contains(state);
}
bool digest(const QJsonValue &value)
{
    return value.isString() && QRegularExpression("^sha256:[0-9a-f]{64}$").match(value.toString()).hasMatch();
}
bool stringMap(const QJsonValue &value, bool reasons = false)
{
    if (!value.isObject()) return false;
    for (const auto &item : value.toObject())
        if (!item.isString() || (reasons && item.toString() != "explicit" && item.toString() != "dependency")) return false;
    return true;
}
bool bytes(const QJsonValue &value)
{
    return value.isDouble() && value.toDouble() >= 0 && value.toDouble() == std::floor(value.toDouble());
}
bool managementState(const QJsonValue &value)
{
    if (!value.isObject()) return false;
    const auto object = value.toObject();
    return object.value("schema_version").toInt() == 1 && object.value("packages").isObject()
        && object.value("protected").isArray() && stringMap(object.value("repositories"))
        && validConfiguration(object.value("applied").toObject().toVariantMap());
}
bool validPlan(const QJsonObject &result, const QVariantMap &draft)
{
    if (!result.value("executable").isBool() || !result.value("blockers").isArray()
        || !result.value("warnings").isArray()) return false;
    // A blocked resolver may have no plan at all; it can only show its refusal.
    if (!result.value("executable").toBool() && result.value("plan").isNull()) return !result.value("blockers").toArray().isEmpty();
    if (!digest(result.value("plan_id")) || !result.value("plan").isObject()) return false;
    const auto plan = result.value("plan").toObject();
    const auto packages = plan.value("packages").toObject();
    const auto boot = plan.value("boot").toObject();
    const auto current = plan.value("current").toObject();
    const auto management = plan.value("management").toObject();
    if (plan.value("schema_version").toInt() != 2 || plan.value("desired").toString() != "managed_system"
        || !plan.value("snapshot_required").isBool() || !boot.value("regenerate_uki").isBool()
        || !boot.value("update_bootloader").isBool() || boot.value("update_bootloader").toBool()
        || !digest(current.value("id")) || !stringMap(current.value("packages"))
        || !packages.value("changes").isArray() || !packages.value("targets").isArray()
        || !bytes(packages.value("download_bytes"))
        || (!packages.value("installed_delta_bytes").isNull() && !packages.value("installed_delta_bytes").isDouble())
        || !managementState(management.value("after"))
        || (!management.value("before").isNull() && !managementState(management.value("before")))
        || !digest(management.value("before_digest")) || !digest(management.value("after_digest"))
        || !stringMap(management.value("reasons_before"), true) || !stringMap(management.value("reasons_after"), true)
        || management.value("after").toObject().value("applied").toObject() != QJsonObject::fromVariantMap(draft)) return false;
    QMap<QString, QString> expectedTargets;
    QSet<QString> names;
    for (const auto &item : packages.value("changes").toArray()) {
        if (!item.isObject()) return false;
        const auto change = item.toObject();
        const auto name = change.value("name").toString();
        const auto kind = change.value("kind").toString();
        if (name.isEmpty() || names.contains(name)) return false;
        names.insert(name);
        if (kind == "upgrade") {
            if (change.value("from").toString().isEmpty() || change.value("to").toString().isEmpty()) return false;
            expectedTargets[name] = change.value("to").toString();
        } else if (kind == "install" || kind == "remove") {
            if (change.value("version").toString().isEmpty()) return false;
            if (kind == "install") expectedTargets[name] = change.value("version").toString();
        } else return false;
    }
    QMap<QString, QString> actualTargets;
    double download = 0;
    for (const auto &item : packages.value("targets").toArray()) {
        if (!item.isObject()) return false;
        const auto target = item.toObject();
        const auto name = target.value("name").toString();
        if (name.isEmpty() || actualTargets.contains(name) || target.value("version").toString().isEmpty()
            || target.value("repository").toString().isEmpty() || !bytes(target.value("archive_bytes"))
            || !bytes(target.value("installed_bytes"))
            || !QRegularExpression("^[0-9a-f]{64}$").match(target.value("sha256").toString()).hasMatch()) return false;
        actualTargets[name] = target.value("version").toString();
        download += target.value("archive_bytes").toDouble();
    }
    if (actualTargets != expectedTargets || download != packages.value("download_bytes").toDouble()) return false;
    const bool mutation = !names.isEmpty() || management.value("before_digest") != management.value("after_digest")
        || management.value("reasons_before") != management.value("reasons_after");
    return (!mutation || (plan.value("snapshot_required").toBool() && boot.value("regenerate_uki").toBool()))
        && (!result.value("executable").toBool() || result.value("blockers").toArray().isEmpty());
}
}

Controller::Controller(QObject *parent) : Controller("/usr/bin/distroctl", "/usr/bin/pkexec", parent) {}
Controller::Controller(QString executable, QString authenticator, QObject *parent)
    : QObject(parent), m_executable(std::move(executable)), m_authenticator(std::move(authenticator))
{
    m_performance = new Performance(m_executable, this);
    connect(m_performance, &Performance::changed, this, &Controller::changed);
    connect(this, &Controller::changed, m_performance, [this] {
        m_performance->setBlocked(active() || m_pending.contains("submit") || m_status.value("reboot_required").toBool() || m_status.value("recovery_required").toBool());
    });
    m_poll.setInterval(2000);
    connect(&m_poll, &QTimer::timeout, this, &Controller::poll);
}
bool Controller::busy() const
{
    if (m_performance && m_performance->baselineRunning()) return true;
    for (const auto &key : {"plan", "submit", "parse", "adopt", "export"})
        if (m_pending.contains(key)) return true;
    return false;
}
bool Controller::active() const
{
    return m_pending.contains("submit") || (!m_operationId.isEmpty() && !terminal(m_operation.value("state").toString()));
}
void Controller::fail(const QString &message)
{
    m_error = message;
    emit changed();
}
void Controller::clearError() { m_error.clear(); emit changed(); }

void Controller::request(const QString &channel, QStringList arguments, QByteArray input,
                         Callback callback, bool privileged)
{
    if (m_pending.contains(channel)) return;
    auto *process = new QProcess(this);
    auto *timeout = new QTimer(process);
    timeout->setSingleShot(true);
    auto output = std::make_shared<QByteArray>();
    auto diagnostic = std::make_shared<QByteArray>();
    auto failure = std::make_shared<QString>();
    m_pending.insert(channel);
    emit changed();
    connect(process, &QProcess::readyReadStandardOutput, this, [process, output, failure] {
        output->append(process->readAllStandardOutput());
        if (output->size() > maximumOutput) {
            *failure = "The system tool returned an oversized response.";
            output->truncate(maximumOutput);
            process->kill();
        }
    });
    connect(process, &QProcess::readyReadStandardError, this, [process, diagnostic] {
        diagnostic->append(process->readAllStandardError());
        diagnostic->truncate(4096);
    });
    connect(timeout, &QTimer::timeout, this, [process, failure] {
        *failure = "The system tool did not respond. Refresh to check the current state.";
        process->kill();
    });
    connect(process, &QProcess::errorOccurred, this, [this, channel, process](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            m_pending.remove(channel);
            fail("Could not start the system tool: " + process->errorString());
            process->deleteLater();
        }
    });
    connect(process, &QProcess::finished, this,
            [this, channel, process, timeout, output, diagnostic, failure, callback, privileged](int code, QProcess::ExitStatus exit) {
        timeout->stop();
        output->append(process->readAllStandardOutput());
        diagnostic->append(process->readAllStandardError());
        m_pending.remove(channel);
        process->deleteLater();
        if (!failure->isEmpty()) { fail(*failure); return; }
        if (code != 0 || exit != QProcess::NormalExit) {
            if (privileged && code == 126) fail("Authentication was canceled. No request was submitted.");
            else if (privileged && code == 127) fail("Administrator authentication was not available or was denied.");
            else fail(QString::fromUtf8(diagnostic->left(4096)).trimmed().isEmpty()
                          ? QString("The system tool failed (exit %1). Refresh to check its status.").arg(code)
                          : QString::fromUtf8(diagnostic->left(4096)).trimmed());
            if (privileged) refresh();
            return;
        }
        QJsonParseError parseError;
        const auto document = QJsonDocument::fromJson(*output, &parseError);
        if (output->size() > maximumOutput || parseError.error != QJsonParseError::NoError
            || (channel != "history" && (!document.isObject() || document.object().value("schema_version").toInt() != 1))
            || (channel == "history" && !document.isArray())) {
            fail("The system tool returned an invalid or unsupported response. No further action was taken.");
            return;
        }
        callback(document);
        emit changed();
    });
    if (privileged) {
        arguments.prepend(m_executable);
        arguments.prepend("--disable-internal-agent");
    }
    process->setProgram(privileged ? m_authenticator : m_executable);
    process->setArguments(arguments);
    connect(process, &QProcess::started, this, [process, input] { process->write(input); process->closeWriteChannel(); });
    process->start();
    // Authentication has its own cancel button; never time out an accepted submission.
    if (!privileged) timeout->start(60000);
}

void Controller::refresh()
{
    request("status", {"system", "status", "--json"}, {}, [this](const auto &doc) {
        m_status = doc.object().toVariantMap();
        const auto config = m_status.value("configuration").toMap();
        if (!validConfiguration(config)) {
            m_haveDraft = false;
            m_planValid = false;
            m_plan.clear();
            fail("The saved configuration is unavailable. Resolve the reported recovery state before making changes.");
        } else {
            if (!m_dirty) m_draft = config;
            m_haveDraft = true;
        }
        const auto activeOperation = m_status.value("active_operation").toMap();
        const auto id = activeOperation.value("operation_id").toString();
        if (QRegularExpression("^[0-9a-f]{32}$").match(id).hasMatch()) {
            m_operationId = id;
            m_operation = activeOperation;
            if (terminal(m_operation.value("state").toString())) m_poll.stop();
            else { m_poll.start(); poll(); }
        }
    });
    request("features", {"system", "features", "--json"}, {}, [this](const auto &doc) {
        m_features = doc.object().value("features").toArray().toVariantList();
    });
    request("history", {"history", "--json"}, {}, [this](const auto &doc) {
        m_history = doc.array().toVariantList();
        std::reverse(m_history.begin(), m_history.end());
    });
    request("configuration", {"system", "export", "--json"}, {}, [this](const auto &doc) {
        m_configurationText = doc.object().value("toml").toString();
    });
}
void Controller::search(const QString &query)
{
    const auto trimmed = query.trimmed();
    if (trimmed.isEmpty()) { installed(); return; }
    const auto revision = ++m_searchRevision;
    request("search-" + QString::number(revision), {"system", "packages", "search", trimmed, "--json"}, {},
            [this, revision](const auto &doc) { if (revision == m_searchRevision) m_packages = doc.object().value("packages").toArray().toVariantList(); });
}
void Controller::installed()
{
    const auto revision = ++m_searchRevision;
    request("search-" + QString::number(revision), {"system", "packages", "installed", "--json"}, {},
            [this, revision](const auto &doc) { if (revision == m_searchRevision) m_packages = doc.object().value("packages").toArray().toVariantList(); });
}
bool Controller::acceptDraft(const QVariantMap &configuration)
{
    if (!validConfiguration(configuration)) { fail("The configuration response is incomplete."); return false; }
    m_draft = configuration;
    m_haveDraft = true;
    m_dirty = true;
    m_plan.clear();
    m_planValid = false;
    m_notice.clear();
    ++m_draftRevision;
    emit changed();
    return true;
}
void Controller::editSelection(const QString &key, const QString &name, bool selected)
{
    if (!m_haveDraft || busy() || active()) return;
    auto config = m_draft;
    auto values = config.value(key).toStringList();
    values.removeAll(name);
    if (selected) values.append(name);
    values.sort();
    config[key] = values;
    acceptDraft(config);
}
void Controller::setPackage(const QString &name, bool selected) { editSelection("packages", name, selected); }
void Controller::setFeature(const QString &name, bool selected) { editSelection("gaming", name, selected); }
void Controller::setProvider(const QString &name, const QString &provider)
{
    if (!m_haveDraft || busy() || active()) return;
    auto config = m_draft;
    auto providers = config.value("providers").toMap();
    if (provider.trimmed().isEmpty()) providers.remove(name); else providers[name] = provider.trimmed();
    config["providers"] = providers;
    acceptDraft(config);
}
void Controller::discard()
{
    if (busy() || active()) return;
    m_draft = m_status.value("configuration").toMap();
    m_dirty = false;
    m_plan.clear();
    m_planValid = false;
    ++m_draftRevision;
    emit changed();
}
void Controller::review()
{
    if (!m_haveDraft || busy() || active()) return;
    m_error.clear();
    const auto revision = m_draftRevision;
    request("plan", {"system", "plan", "--stdin", "--json"}, QJsonDocument::fromVariant(m_draft).toJson(QJsonDocument::Compact),
            [this, revision](const auto &doc) {
        if (revision != m_draftRevision) return;
        if (!validPlan(doc.object(), m_draft)) {
            m_plan.clear();
            m_planValid = false;
            fail("The system returned an incomplete or contradictory plan. Authentication is disabled; refresh and review again.");
            return;
        }
        m_plan = doc.object().toVariantMap();
        m_planValid = m_plan.value("executable").toBool();
        emit planReady();
    });
}
void Controller::apply()
{
    if (busy() || active() || !m_haveDraft || m_status.value("live").toBool() || m_status.value("reboot_required").toBool()
        || m_status.value("recovery_required").toBool()
        || !m_planValid || !m_plan.value("executable").toBool() || m_plan.value("plan_id").toString().isEmpty()) return;
    QVariantMap envelope{{"schema_version", 1}, {"config", m_draft}, {"expected_plan", m_plan.value("plan_id")}};
    m_error.clear();
    request("submit", {"system", "submit", "--json"}, QJsonDocument::fromVariant(envelope).toJson(QJsonDocument::Compact),
            [this](const auto &doc) {
        const auto id = doc.object().value("operation_id").toString();
        if (!QRegularExpression("^[0-9a-f]{32}$").match(id).hasMatch()) { fail("The operation identifier is invalid. Refresh to check the system."); refresh(); return; }
        m_operationId = id;
        m_operation = {{"operation_id", id}, {"state", "queued"}};
        m_dirty = false;
        m_plan.clear();
        m_planValid = false;
        m_notice = "Changes were submitted. You can close this window; the system worker will continue.";
        m_poll.start();
        poll();
        emit submitted();
    }, true);
}
void Controller::poll()
{
    if (m_operationId.isEmpty()) return;
    request("operation", {"system", "operation", m_operationId, "--json"}, {}, [this](const auto &doc) {
        m_operation = doc.object().toVariantMap();
        if (terminal(m_operation.value("state").toString())) {
            m_poll.stop();
            refresh();
        }
    });
}
void Controller::adopt()
{
    if (busy() || active()) return;
    request("adopt", {"system", "adopt", "--json"}, {}, [this](const auto &doc) {
        if (!acceptDraft(doc.object().value("configuration").toObject().toVariantMap())) return;
        m_notice = "Installed packages were copied into your draft. Review changes before saving them.";
    });
}
void Controller::parse(const QString &text)
{
    if (busy() || active()) return;
    if (text.toUtf8().size() > maximumConfiguration) { fail("Configuration files must not exceed 256 KiB."); return; }
    request("parse", {"system", "parse", "--stdin", "--json"}, text.toUtf8(), [this, text](const auto &doc) {
        if (!acceptDraft(doc.object().value("configuration").toObject().toVariantMap())) return;
        m_notice = "Configuration loaded into your draft. Review changes before applying it.";
        emit configurationParsed(text);
    });
}
void Controller::importFile(const QUrl &url)
{
    if (!url.isLocalFile()) { fail("Choose a local TOML configuration file."); return; }
    QFile file(url.toLocalFile());
    if (!file.open(QIODevice::ReadOnly) || file.size() > maximumConfiguration) { fail("Could not read this configuration, or it exceeds 256 KiB."); return; }
    parse(QString::fromUtf8(file.read(maximumConfiguration + 1)));
}
void Controller::exportFile(const QUrl &url)
{
    if (!url.isLocalFile()) { fail("Choose a local destination for the saved configuration."); return; }
    request("export", {"system", "export", "--json"}, {}, [this, url](const auto &doc) {
        const auto text = doc.object().value("toml").toString().toUtf8();
        if (text.isEmpty()) { fail("The system did not return a configuration to export."); return; }
        QSaveFile file(url.toLocalFile());
        if (!file.open(QIODevice::WriteOnly) || file.write(text) != text.size() || !file.commit()) {
            fail("Could not save the configuration: " + file.errorString()); return;
        }
        m_notice = "Saved configuration exported. Unapplied draft changes are not included.";
    });
}
