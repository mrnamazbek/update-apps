# Contributing

Start with an issue describing the app's official distribution channel, bundle
identifier and expected update behavior. An app's display name is not enough to
identify it: several unrelated products are named Insomnia.

Use Python 3.9+ and the standard library. Run `make test` before submitting a pull
request. Tests use temporary fixtures and mocked package-manager/network calls;
they must not update real apps, request administrator access, connect a VPN or
change power settings.

When adding an updater, document its source and limits. Preserve settings and
existing stable/beta channels, avoid forced adoption, provide a read-only preview,
and report installation steps still requiring user action. Add regression tests
for identity mismatches, failed downloads and failed installation/rollback paths.

Keep credentials, local app inventories, VPN configuration and security-audit
reports out of the repository. See [SECURITY.md](SECURITY.md) for private reporting.
