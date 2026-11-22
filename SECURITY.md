# Security policy

## Supported versions

Security fixes target the latest stable release and the current `main` branch.
Older releases are not maintained separately; upgrade to the latest release
before checking whether a problem still occurs.

This is a personal, best-effort project. Response and remediation times are not
guaranteed.

## Reporting a vulnerability

Please report suspected vulnerabilities privately through
[GitHub private vulnerability reporting](https://github.com/alienbrainfarm/yt2mp3/security/advisories/new).
You can also open the repository's **Security** tab and choose **Report a
vulnerability**.

Do not put vulnerability details, exploit code, browser cookies, account tokens,
or unredacted logs in a public issue or pull request. Use public issues for
ordinary bugs that do not expose sensitive information.

Include:

- The affected release or commit, operating system, and whether you use a
  packaged build or run from source.
- Steps to reproduce, expected and actual behavior, and a minimal proof of
  concept using test data.
- The potential impact and any required access, configuration, or interaction.
- Relevant logs or screenshots with cookies, tokens, account details, and
  personal paths removed.

Reports will be assessed privately. Maintainers may ask for more information
and coordinate a fix and disclosure with the reporter. Please keep details
private while that coordination is in progress.

## Security model

yt2mp3 is a local, single-user desktop application. Its web server binds to
`127.0.0.1`; sensitive API endpoints require a per-run application token.
It is not designed to be exposed to a LAN, the public internet, or multiple
untrusted users through a proxy or tunnel.

The application runs with the permissions of the operating-system account that
starts it. Output folders, cookies files, and custom browser-profile paths are
restricted to the home and app folders, plus absolute locations explicitly set
in `YT2MP3_ALLOWED_ROOTS` before startup. API requests cannot extend that list.
Resolved paths, including symlink targets, must remain within those locations.
Open/reveal is further restricted to download folders. Account mode allows
yt-dlp to read the selected local browser's cookies. External yt-dlp configuration
files are ignored. The application is not a sandbox for untrusted local programs
that can change files or symlinks concurrently.

Reports about bypassing the local API protections, unintended file access,
command execution, exposure of account data, malicious media or metadata, and
dependency vulnerabilities affecting yt2mp3 are welcome. Local-only operation
does not make these issues automatically out of scope.

## Protecting your installation

- Run the application as a regular user, without administrator or root privileges.
- Keep yt2mp3 and its dependencies up to date. Packaged builds include their own
  dependencies, so updating a separate Python installation does not update them.
- Obtain packaged builds from this repository's
  [GitHub Releases](https://github.com/alienbrainfarm/yt2mp3/releases) and compare
  their checksums with the published `SHA256SUMS.txt`. Checksums detect changed
  files; they do not replace code signing.
- Treat exported cookies as credentials. Do not commit or share cookies files,
  browser profiles, application tokens, local settings, history, or unredacted
  logs.
