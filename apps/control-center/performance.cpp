#include "performance.h"
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QSaveFile>
#include <QTimer>
#include <cmath>
#include <memory>

namespace {
constexpr qint64 limit = 2 * 1024 * 1024;
bool validId(const QString &id) { return QRegularExpression("^[0-9a-f]{32}$").match(id).hasMatch(); }
bool validSample(const QJsonObject &v);
bool validReport(const QJsonObject &v) {
    const auto state = v.value("state").toString();
    bool valid = v.value("schema_version").toInt() == 1 && validId(v.value("id").toString())
        && (v.value("kind") == "record" || v.value("kind") == "baseline")
        && QStringList{"completed", "incomplete", "failed", "cancelled"}.contains(state)
        && v.value("context").isObject() && v.value("samples").isArray()
        && v.value("samples").toArray().size() <= 301 && v.value("measurements").isArray()
        && v.value("measurements").toArray().size() <= 3 && v.value("warnings").isArray()
        && v.value("elapsed_seconds").isDouble() && v.value("elapsed_seconds").toDouble() >= 0
        && v.value("elapsed_seconds").toDouble() <= 3600;
    for (const auto &s : v.value("samples").toArray()) valid &= s.isObject() && validSample(s.toObject());
    if (state == "completed") {
        valid &= !v.value("samples").toArray().isEmpty() && v.value("failure").isNull();
        if (v.value("kind") == "baseline") valid &= v.value("measurements").toArray().size() == 3;
    }
    for (const auto &m : v.value("measurements").toArray()) {
        const auto object = m.toObject(); const auto w = object.value("workload").toObject(); const auto values = object.value("values").toArray();
        valid &= m.isObject() && w.value("version").toInt() == 1 && w.value("threads").toInt() >= 1 && w.value("threads").toInt() <= 4
            && w.value("bytes").toDouble() > 0 && w.value("bytes").toDouble() <= 128 * 1024 * 1024
            && QStringList{"sha256", "memory-copy", "scratch-sync-read"}.contains(w.value("name").toString())
            && object.value("unit") == "MiB/s" && object.value("values").isArray() && values.size() <= 3;
        if (state == "completed") valid &= values.size() == 3;
        for (const auto &n : values) valid &= n.isDouble() && std::isfinite(n.toDouble()) && n.toDouble() >= 0;
    }
    return valid;
}
bool validSample(const QJsonObject &v) {
    const auto cpu = v.value("cpu_busy_percent");
    bool valid = (cpu.isNull() || (cpu.isDouble() && cpu.toDouble() >= 0 && cpu.toDouble() <= 100))
        && v.value("elapsed_seconds").isDouble() && v.value("elapsed_seconds").toDouble() >= 0
        && v.value("elapsed_seconds").toDouble() <= 3600 && v.value("unavailable").isArray()
        && v.value("temperatures").isArray() && v.value("temperatures").toArray().size() <= 128 && v.value("pressure_avg10_percent").isObject();
    for (const auto &t : v.value("temperatures").toArray()) {
        const auto o=t.toObject(); valid &= t.isObject() && o.value("label").isString() && o.value("label").toString().size() <= 80
            && o.value("celsius").isDouble() && o.value("celsius").toDouble() >= -100 && o.value("celsius").toDouble() <= 200;
    }
    for (const auto &s : v.value("unavailable").toArray()) valid &= s.isString() && s.toString().size() <= 512;
    return valid;
}
}

Performance::Performance(QString executable, QObject *parent) : QObject(parent), m_executable(std::move(executable)) {}
Performance::~Performance() {
    if (m_run) { m_run->disconnect(this); m_run->terminate(); if (!m_run->waitForFinished(3000)) { m_run->kill(); m_run->waitForFinished(1000); } }
}
void Performance::fail(const QString &error) { m_error = error; emit changed(); }
void Performance::setBlocked(bool blocked) { if (m_blocked == blocked) return; m_blocked = blocked; if (blocked && running()) stop(); emit changed(); }
void Performance::refresh() { query("status", {"status"}); query("list", {"list"}); }
void Performance::observe() { if (!running()) query("status", {"status"}); }
void Performance::show(const QString &id) { if (validId(id)) query("show", {"show", id}); else fail("Invalid saved run identifier."); }
void Performance::compare(const QString &a, const QString &b) {
    if (!validId(a) || !validId(b)) { fail("Choose two saved runs."); return; }
    query("compare", {"compare", a, b});
}
void Performance::exportFile(const QString &id, const QUrl &url) {
    if (!validId(id) || !url.isLocalFile()) { fail("Choose a saved run and a local export file."); return; }
    query("export", {"export", id}, url);
}
void Performance::query(const QString &channel, const QStringList &arguments, const QUrl &url) {
    if (m_queries.contains(channel)) return;
    m_queries.insert(channel); emit changed();
    auto *p = new QProcess(this); auto *timer = new QTimer(p); timer->setSingleShot(true);
    auto out = std::make_shared<QByteArray>(); auto err = std::make_shared<QByteArray>();
    auto failure = std::make_shared<QString>();
    connect(p, &QProcess::readyReadStandardOutput, this, [p, out, failure] {
        out->append(p->readAllStandardOutput()); if (out->size() > limit) { *failure = "Performance response exceeds 2 MiB."; out->truncate(limit); p->kill(); }
    });
    connect(p, &QProcess::readyReadStandardError, this, [p, err] { err->append(p->readAllStandardError()); err->truncate(4096); });
    connect(timer, &QTimer::timeout, this, [p, failure] { *failure = "Performance query timed out."; p->kill(); });
    connect(p, &QProcess::errorOccurred, this, [this,p,channel](auto error) {
        if (error == QProcess::FailedToStart) { m_queries.remove(channel); fail("Could not start the performance backend."); p->deleteLater(); }
    });
    connect(p, &QProcess::finished, this, [this,p,timer,out,err,failure,channel,url,arguments](int code, auto exit) {
        timer->stop(); out->append(p->readAllStandardOutput()); err->append(p->readAllStandardError());
        m_queries.remove(channel); p->deleteLater();
        if (!failure->isEmpty()) { fail(*failure); return; }
        if (code != 0 || exit != QProcess::NormalExit) { fail(QString::fromUtf8(err->left(4096)).trimmed().isEmpty() ? "Performance query failed." : QString::fromUtf8(err->left(4096))); return; }
        QJsonParseError parse; const auto doc = QJsonDocument::fromJson(*out, &parse); const auto v = doc.object();
        bool valid = out->size() <= limit && parse.error == QJsonParseError::NoError && doc.isObject() && v.value("schema_version").toInt() == 1;
        if (channel == "status") valid &= v.value("context").isObject() && v.value("sample").isObject() && validSample(v.value("sample").toObject()) && v.value("baseline_blockers").isArray();
        if (channel == "list") {
            valid &= v.value("runs").isArray() && v.value("runs").toArray().size() <= 1000;
            for (const auto &r : v.value("runs").toArray()) valid &= r.isObject() && validId(r.toObject().value("id").toString()) && QStringList{"completed","incomplete","failed","cancelled","unreadable"}.contains(r.toObject().value("state").toString());
        }
        if (channel == "show" || channel == "export") valid &= validReport(v);
        if (channel == "show" || channel == "export") valid &= v.value("id").toString() == arguments.value(1);
        if (channel == "compare") {
            valid &= v.value("comparable").isBool() && v.value("blockers").isArray() && v.value("measurements").isArray() && v.value("measurements").toArray().size() <= 3 && v.value("context_changes").isObject();
            for (const auto &r : v.value("measurements").toArray()) {
                const auto o=r.toObject();valid &= r.isObject() && o.value("workload").isObject() && o.value("workload").toObject().value("name").isString() && o.value("unit")=="MiB/s";
                for (const auto &key : {"before","after"}) { const auto s=o.value(key).toObject(); valid &= o.value(key).isObject() && s.value("median").isDouble() && s.value("spread").isDouble() && s.value("values").isArray(); }
            }
        }
        if (!valid) { fail("Invalid or unsupported performance response."); return; }
        if (channel == "status") { m_status = v.toVariantMap(); if (!running()) m_sample = v.value("sample").toObject().toVariantMap(); }
        if (channel == "list") m_runs = v.value("runs").toArray().toVariantList();
        if (channel == "show") m_result = v.toVariantMap();
        if (channel == "compare") m_comparison = v.toVariantMap();
        if (channel == "export") {
            QSaveFile f(url.toLocalFile()); const auto data = doc.toJson();
            if (!f.open(QIODevice::WriteOnly) || f.write(data) != data.size() || !f.commit()) { fail("Could not save the performance export."); return; }
        }
        emit changed();
    });
    auto args = arguments; args.prepend("performance"); args.append("--json");
    p->setProgram(m_executable); p->setArguments(args); p->start(); p->closeWriteChannel(); timer->start(20000);
}
void Performance::start(const QString &kind) {
    if (running() || blocked() || (kind != "record" && kind != "baseline")) { fail("A measurement cannot start while another operation is active."); return; }
    if (kind == "baseline" && (m_status.isEmpty() || !m_status.value("baseline_blockers").toList().isEmpty())) { fail("Resolve the baseline blockers first."); return; }
    m_buffer.clear(); m_diagnostic.clear(); m_received = 0; m_gotResult = false; m_runId.clear(); m_error.clear(); m_result.clear(); m_phase = "Starting";
    m_run = new QProcess(this); auto *p = m_run;
    connect(p, &QProcess::readyReadStandardOutput, this, [this] { consume(); });
    connect(p, &QProcess::readyReadStandardError, this, [this,p] { m_diagnostic.append(p->readAllStandardError()); m_diagnostic.truncate(4096); });
    connect(p, &QProcess::errorOccurred, this, [this,p](auto error) { if (error == QProcess::FailedToStart) { m_run = nullptr; p->deleteLater(); fail("Could not start the measurement backend."); } });
    connect(p, &QProcess::finished, this, [this,p](int code, auto exit) {
        consume(); m_diagnostic.append(p->readAllStandardError()); m_run = nullptr; p->deleteLater();
        if (!m_gotResult || !m_buffer.trimmed().isEmpty()) {
            m_result.clear(); m_gotResult = false;
            if (m_error.isEmpty()) m_error = "Measurement stopped without a valid final result. Inspect its saved record before using it.";
        }
        else if ((code != 0 || exit != QProcess::NormalExit) && m_result.value("state") == "completed") { m_result.clear(); m_error = "Backend failure contradicts its completion result."; }
        else if (m_error.isEmpty() && m_result.value("state") != "completed") m_error = m_result.value("failure").toString();
        m_phase = m_result.isEmpty() ? "Incomplete" : m_result.value("state").toString(); emit changed(); refresh();
    });
    p->setProgram(m_executable); p->setArguments({"performance", kind, "--json"}); p->start(); p->closeWriteChannel();
    QTimer::singleShot(kind == "baseline" ? 185000 : 65000, p, [this,p] { if (m_run == p) { fail("Measurement exceeded its execution budget."); stop(); } });
    emit changed();
}
void Performance::stop() {
    if (!m_run) return; auto *p = m_run; m_phase = "Stopping"; p->terminate();
    QTimer::singleShot(5000, p, [this,p] { if (m_run == p) p->kill(); }); emit changed();
}
void Performance::consume() {
    if (!m_run) return;
    const auto bytes = m_run->readAllStandardOutput(); m_received += bytes.size(); m_buffer.append(bytes);
    if (m_received > 8 * limit || m_buffer.size() > limit) { m_buffer.clear(); fail("Measurement output exceeded its limit."); m_run->kill(); return; }
    while (m_buffer.contains('\n')) {
        const auto line = m_buffer.left(m_buffer.indexOf('\n')); m_buffer.remove(0, line.size() + 1);
        QJsonParseError parse; const auto doc = QJsonDocument::fromJson(line, &parse); const auto e = doc.object(); const auto d = e.value("data").toObject();
        const auto kind = e.value("event").toString();
        bool valid = parse.error == QJsonParseError::NoError && doc.isObject() && e.value("schema_version").toInt() == 1 && e.value("data").isObject() && !m_gotResult;
        if (kind == "started") { valid &= m_runId.isEmpty() && validId(d.value("id").toString()); if (valid) m_runId = d.value("id").toString(); }
        else if (kind == "sample") { valid &= !m_runId.isEmpty() && validSample(d); if (valid) m_sample = d.toVariantMap(); }
        else if (kind == "phase") { valid &= !m_runId.isEmpty() && d.value("name").isString() && d.value("name").toString().size() <= 100; if (valid) m_phase = d.value("name").toString(); }
        else if (kind == "result") { valid &= !m_runId.isEmpty() && validReport(d) && d.value("id").toString() == m_runId; if (valid) { m_result = d.toVariantMap(); m_gotResult = true; } }
        else valid = false;
        if (!valid) { m_result.clear(); m_gotResult = false; fail("Invalid or unsupported measurement event."); m_run->kill(); return; }
        emit changed();
    }
}
