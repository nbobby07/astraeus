// Fixture generator: link against the built workspace crates, then run with an output directory.
use distro_config::SystemConfig;
use distro_transactions::{reconcile, CurrentSystemState, ExecutionPlan, InstallReason, ManagementState, PackageChange, PackagePlan, PackageTarget};
use std::{collections::BTreeMap, fs, path::PathBuf};

fn main() {
    let output = PathBuf::from(std::env::args().nth(1).expect("fixture output directory"));
    fs::create_dir_all(&output).unwrap();
    let current = CurrentSystemState::new(BTreeMap::from([("nano".into(), "9.2-1".into())]));
    let reasons = BTreeMap::from([("nano".into(), InstallReason::Explicit)]);
    let before = ManagementState {
        applied: SystemConfig { packages: ["nano".into()].into(), ..Default::default() },
        protected: ["nano".into()].into(),
        repositories: BTreeMap::from([("extra".into(), format!("sha256:{}", "b".repeat(64)))]),
        ..Default::default()
    };
    let config = SystemConfig { packages: ["kate".into(), "nano".into()].into(), ..Default::default() };
    let resolved = CurrentSystemState::new(BTreeMap::from([("nano".into(), "9.2-1".into()), ("kate".into(), "26.08.1-1".into())]));
    let after_reasons = BTreeMap::from([("nano".into(), InstallReason::Explicit), ("kate".into(), InstallReason::Explicit)]);
    let management = reconcile(Some(&before), &current, &reasons, &resolved, &after_reasons, &config, &before.protected, &before.repositories).unwrap();
    let plan = ExecutionPlan::new(current, PackagePlan {
        changes: vec![PackageChange::Install { name: "kate".into(), version: "26.08.1-1".into() }],
        targets: vec![PackageTarget { name: "kate".into(), version: "26.08.1-1".into(), repository: "extra".into(), archive_bytes: 3 * 1024 * 1024, installed_bytes: 6 * 1024 * 1024, sha256: "e".repeat(64) }],
        download_bytes: 3 * 1024 * 1024, installed_delta_bytes: Some(6 * 1024 * 1024),
    }).with_management(management);
    plan.validate().unwrap();
    let executable = serde_json::json!({"schema_version":1,"plan_id":plan.fingerprint(),"executable":true,"plan":plan,"blockers":[],"warnings":[]});
    let mut blocked = executable.clone();
    blocked["executable"] = false.into();
    blocked["blockers"] = serde_json::json!(["A previous transaction is awaiting boot confirmation."]);
    for (name, value) in [("install-plan.json", executable), ("blocked-plan.json", blocked)] {
        fs::write(output.join(name), serde_json::to_string_pretty(&value).unwrap() + "\n").unwrap();
    }
}
