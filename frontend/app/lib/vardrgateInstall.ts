// VardrGate ships as a release binary, not a package, so these one-liners do what its README
// asks of a manual install: download a pinned release, check it against that release's
// SHA256SUMS, refuse it on a mismatch, then put it on PATH. Pinned rather than "latest" so the
// command never installs a build nobody has looked at; bump it when VardrGate releases.
export const VARDRGATE_VERSION = "0.1.0";

const releaseUrl = (version: string) => `https://github.com/VardrSec/VardrGate/releases/download/v${version}`;

// PowerShell 5.1-compatible. Windows builds are amd64 only (they also run on Windows on Arm).
export function vardrgateWindowsInstallCommand(version: string = VARDRGATE_VERSION): string {
  return [
    `$v='${version}'`,
    `$d="$env:LOCALAPPDATA\\Programs\\VardrGate"`,
    `$u='${releaseUrl(version)}'`,
    `$f="vardrgate_$($v)_windows_amd64.zip"`,
    `$t=Join-Path $env:TEMP $f`,
    `$s=Join-Path $env:TEMP 'vardrgate-SHA256SUMS'`,
    `iwr "$u/$f" -OutFile $t -UseBasicParsing`,
    `iwr "$u/SHA256SUMS" -OutFile $s -UseBasicParsing`,
    `$h=((Get-Content $s | ? { $_ -like "* $f" }) -split '\\s+')[0]`,
    `if (-not $h -or (Get-FileHash $t -Algorithm SHA256).Hash -ne $h) { throw 'VardrGate checksum mismatch: not installed' }`,
    `Expand-Archive $t $d -Force`,
    `$p=[Environment]::GetEnvironmentVariable('Path','User')`,
    `if ($p -notlike "*$d*") { [Environment]::SetEnvironmentVariable('Path',"$p;$d",'User') }`,
    `$env:Path+=";$d"`,
    `vardrgate version`,
  ].join("; ");
}

// POSIX sh, run in a subshell so `set -e` and `cd` never touch the user's own shell.
// Installs to ~/.local/bin, which needs no sudo.
export function vardrgateUnixInstallCommand(version: string = VARDRGATE_VERSION): string {
  return [
    `(set -e; v=${version}`,
    `os=$(uname -s | tr '[:upper:]' '[:lower:]')`,
    `arch=$(uname -m); case "$arch" in x86_64) arch=amd64;; aarch64) arch=arm64;; esac`,
    `f="vardrgate_\${v}_\${os}_\${arch}.tar.gz"`,
    `u="${releaseUrl(version)}"`,
    `t=$(mktemp -d); cd "$t"`,
    `curl -fsSLO "$u/$f"; curl -fsSLO "$u/SHA256SUMS"`,
    `grep " $f$" SHA256SUMS > sum`,
    `if command -v sha256sum >/dev/null; then sha256sum -c sum; else shasum -a 256 -c sum; fi`,
    `tar -xzf "$f" vardrgate; mkdir -p "$HOME/.local/bin"; install -m 755 vardrgate "$HOME/.local/bin/vardrgate"`,
    `cd /; rm -rf "$t") && ~/.local/bin/vardrgate version`,
  ].join("; ");
}
