# Security policy

Please report suspected vulnerabilities privately through this repository's
GitHub **Security → Report a vulnerability** page. If private reporting is not
available, open an issue asking for a private reporting channel without posting
credentials, VPN profiles, a working exploit, or other sensitive details.

The initial 0.1.x release is experimental. Fixes target the latest release;
older versions do not receive a separate maintenance branch.

## Trust model

This project calls the user's existing Homebrew and MAS installations and selected
official developer endpoints. It does not modify MAS, store account credentials,
disable Gatekeeper, grant Homebrew tap trust, or add passwordless administrator rules.
Run it as a normal user. Package managers and vendor installers request their own
administrator authentication when required.

DuoBar downloads must match the release's SHA-256, bundle identifier, pinned Apple
Developer ID and Gatekeeper assessment. This depends on the publisher's GitHub
account, release metadata, signing identity and Apple's trust services; a checksum
is an integrity check, not independent publisher authentication. Vendor installers
remain vendor-controlled software and are outside this project's implementation.

Check-only commands do not install apps, but Homebrew and MAS may refresh metadata
and caches. Reports include local app names, paths and versions; inspect reports
before sharing them. An `action_required` result means installation has not been
verified as complete. Reboots and VPN connections are never initiated automatically.
