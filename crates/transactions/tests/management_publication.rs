//! Real-filesystem publication failures. No mocked persistence result substitutes for the store.
use distro_transactions::{management_store as store, ManagementState};
use std::{
    fs,
    path::PathBuf,
    time::{SystemTime, UNIX_EPOCH},
};

struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        #[cfg(target_os = "linux")]
        let parent = {
            // Production trust checks intentionally reject the shared /tmp ancestor.
            assert_eq!(
                unsafe { libc::geteuid() },
                0,
                "requires an isolated root-owned fixture"
            );
            PathBuf::from("/root")
        };
        #[cfg(not(target_os = "linux"))]
        let parent = std::env::temp_dir();
        let path = parent.join(format!(
            "astraeus-publication-test-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

#[test]
#[cfg_attr(
    target_os = "linux",
    ignore = "requires root; uses only a new /root fixture directory"
)]
fn every_management_publication_boundary_retains_evidence_and_blocks_mixed_state() {
    let order = [store::CONFIG, store::LOCK, store::STATE];
    for blocked in 0..order.len() {
        let fixture = Root::new();
        let before = ManagementState::default();
        store::write_state(&fixture.0, &before).unwrap();
        let old: Vec<_> = order
            .iter()
            .map(|name| fs::read(fixture.0.join(name)).unwrap())
            .collect();
        let mut after = before.clone();
        after.applied.packages.insert("requested-app".into());
        after.validate().unwrap();
        let pending = fixture.0.join(order[blocked]).with_extension("pending");
        fs::write(&pending, b"retained interrupted publication evidence\n").unwrap();

        let failure = store::write_state(&fixture.0, &after).unwrap_err();
        assert!(failure.contains("stage"), "wrong write failure: {failure}");
        assert_eq!(
            fs::read(&pending).unwrap(),
            b"retained interrupted publication evidence\n"
        );
        for (index, relative) in order.iter().enumerate() {
            let observed = fs::read(fixture.0.join(relative)).unwrap();
            if index < blocked {
                assert_ne!(observed, old[index], "preceding {relative} did not publish");
            } else {
                assert_eq!(observed, old[index], "failed write changed {relative}");
            }
        }
        if blocked > 0 {
            assert_eq!(
                fs::read_to_string(fixture.0.join(store::CONFIG)).unwrap(),
                after.applied.to_toml().unwrap()
            );
        }
        if blocked > 1 {
            let lock: serde_json::Value =
                serde_json::from_slice(&fs::read(fixture.0.join(store::LOCK)).unwrap()).unwrap();
            assert_eq!(lock["management_sha256"], after.digest());
        }
        assert!(store::read_state(&fixture.0)
            .unwrap_err()
            .contains("unfinished"));
        // A retry cannot discard the pending evidence or return the previous receipt as current.
        assert!(store::write_state(&fixture.0, &after).is_err());
        assert!(pending.is_file());
        assert!(store::read_state(&fixture.0).is_err());
    }
}
