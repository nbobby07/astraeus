# Calamares validation on disposable VMs

Run `scripts/validate/phase42-baseline.py run --calamares-ui` on the disposable
Linux KVM validator with the same explicit ISO, source, binary hashes, OVMF and
private-directory arguments as the payload baseline. Run separate fresh plain
and LUKS2 cases. This runner never accepts an existing disk argument.

The runner creates a blank 32 GiB disk with a random serial. After the packaged
live smoke, use its private QMP console to start the command channel described in
`attention.json`. It verifies the disk is blank and observes the setup firmware
before handing control to the installer operator.

At `stage: calamares-ui`, use the real desktop installer to select the declared
encryption, account and private credentials. Capture the welcome, summary and
successful finished pages as `calamares-welcome.png`, `calamares-summary.png` and
`calamares-finished.png` in the output directory. Retain the actual installer log
as `calamares.log`. Do not restart from the finished page. Close the installer.
Review captures/logs for accidentally exposed credentials before exporting them.

Write `calamares-ui.json` atomically after observing completion. Its fields are
`schema_version: 1`, `observed_finished: true`, the exact `source_commit`,
`image_sha256`, `encryption` and `serial` from `installation.json`, and a `sha256`
object mapping those four evidence filenames to their hashes. This is an
operator observation with bound evidence, not an independent proof of UI use.
Do not create it from an assumed success or merely from a disk's contents.

The runner requires Calamares to have exited, checks the dedicated disk and
unmounted layout, verifies LUKS2/Argon2id where selected, mounts the installed
subvolumes, and checks the production storage receipt, account and binary hashes.
It adds only disposable owner signing, the explicitly selected pre-existing app
fixture, and the validation command channel. It does not repeat partitioning,
extraction, account creation or production provisioning. Failed installations
must remain failed; repairs require another fresh case.

The two following cold boots use the same GUI-installed disk, without the ISO,
under enforcing owner-trust OVMF. Log in through SDDM on each boot. Successful
baseline manifests retain `method: calamares-ui` and `calamares_ui: true`, and can
then feed the existing management, fault and restored-root recovery runners.

Initial setup uses observed OVMF SetupMode. Installed enforcement with disposable
owner keys does not qualify the setup ISO for factory Secure Boot, nor establish
physical GPU support. The default runner mode remains explicitly identified as
payload/provisioner installation and does not claim Calamares UI acceptance.
