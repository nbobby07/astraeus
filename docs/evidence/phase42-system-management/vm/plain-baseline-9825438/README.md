Fresh plain installation of runtime `9825438d` passed two enforcing cold boots
and actual SDDM/Plasma Wayland logins. The accepted baseline manifest has SHA256
`73f4e7f972d4d7f5db52982d8f9ab32b7a45ea0631c36e530f798124eb47ded0`.
Both boots verified the maintained signed UKI, owner certificate, original desktop
smoke and healthy installed state. They used distinct boot IDs recorded in the
manifest. SetupMode was observed before installation writes; both installed boots
required SecureBoot enabled and SetupMode disabled.

The locally verified 3,506,248-byte evidence archive has SHA256
`9b18f01b35c09ae3004f5a98c293b7d02b36f340651920b53895084ecefacb5a`.
All 118 files matched its index. These compact records establish fresh production
payload installation and boot readiness. Calamares UI, management transactions,
recovery and physical GPU qualification are separate gates. Private keys,
credentials and guest disks were not exported.
