import { VARDRGATE_VERSION, vardrgateUnixInstallCommand, vardrgateWindowsInstallCommand } from "../vardrgateInstall";

const RELEASE = "https://github.com/VardrSec/VardrGate/releases/download/v";

describe("vardrgateWindowsInstallCommand", () => {
  const cmd = vardrgateWindowsInstallCommand("9.8.7");

  it("downloads the pinned release, never latest", () => {
    expect(cmd).toContain(`${RELEASE}9.8.7`);
    expect(cmd).toContain("$v='9.8.7'");
    expect(cmd).toContain("vardrgate_$($v)_windows_amd64.zip");
    expect(cmd).not.toContain("latest");
  });

  it("refuses the archive before extracting it when the checksum does not match", () => {
    const check = cmd.indexOf("Get-FileHash $t -Algorithm SHA256");
    const thrown = cmd.indexOf("throw 'VardrGate checksum mismatch: not installed'");
    expect(check).toBeGreaterThan(-1);
    expect(thrown).toBeGreaterThan(check);
    expect(cmd.indexOf("Expand-Archive")).toBeGreaterThan(thrown);
    // A missing SHA256SUMS line must fail too, not compare against nothing.
    expect(cmd).toContain("if (-not $h -or");
  });

  it("puts it on the user PATH and proves it runs", () => {
    expect(cmd).toContain("[Environment]::SetEnvironmentVariable('Path'");
    expect(cmd.endsWith("vardrgate version")).toBe(true);
  });
});

describe("vardrgateUnixInstallCommand", () => {
  const cmd = vardrgateUnixInstallCommand("9.8.7");

  it("downloads the pinned release for this OS and architecture", () => {
    expect(cmd).toContain(`u="${RELEASE}9.8.7"`);
    expect(cmd).toContain('f="vardrgate_${v}_${os}_${arch}.tar.gz"');
    expect(cmd).toContain("x86_64) arch=amd64;; aarch64) arch=arm64;;");
    expect(cmd).not.toContain("latest");
  });

  it("verifies the checksum before installing, and stops on any failure", () => {
    expect(cmd.startsWith("(set -e;")).toBe(true);
    const check = cmd.indexOf("sha256sum -c sum");
    expect(check).toBeGreaterThan(-1);
    expect(cmd).toContain("shasum -a 256 -c sum");
    expect(cmd.indexOf("tar -xzf")).toBeGreaterThan(check);
  });

  it("installs without sudo and proves it runs", () => {
    expect(cmd).not.toContain("sudo");
    expect(cmd).toContain('install -m 755 vardrgate "$HOME/.local/bin/vardrgate"');
    expect(cmd.endsWith("&& ~/.local/bin/vardrgate version")).toBe(true);
  });
});

it("defaults both commands to the pinned VardrGate version", () => {
  expect(vardrgateWindowsInstallCommand()).toContain(`${RELEASE}${VARDRGATE_VERSION}`);
  expect(vardrgateUnixInstallCommand()).toContain(`${RELEASE}${VARDRGATE_VERSION}`);
});
