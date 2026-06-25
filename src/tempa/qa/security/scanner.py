"""GitHub security API scanner."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class SecurityFinding:
    source: str
    severity: str
    title: str
    description: str
    package: str = ""
    cve_id: str = ""
    file_path: str = ""
    line_number: int = 0
    url: str = ""

    @property
    def severity_rank(self) -> int:
        return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(self.severity.lower(), 0)


@dataclass
class SecurityReport:
    repo: str
    dependabot: list[SecurityFinding] = field(default_factory=list)
    codeql: list[SecurityFinding] = field(default_factory=list)
    secrets: list[SecurityFinding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def all_findings(self) -> list[SecurityFinding]:
        combined = self.dependabot + self.codeql + self.secrets
        return sorted(combined, key=lambda f: f.severity_rank, reverse=True)

    @property
    def total_count(self) -> int:
        return len(self.all_findings)

    def to_markdown(self) -> str:
        if self.total_count == 0 and not self.errors:
            return f"## Security Report — All Clear\n\nNo findings for `{self.repo}`."
        lines = [f"## Security Report — `{self.repo}`\n", f"**{self.total_count} finding(s)**\n"]
        for source_name, findings in [
            ("Dependabot", self.dependabot),
            ("CodeQL", self.codeql),
            ("Secret Scanning", self.secrets),
        ]:
            if findings:
                lines.append(f"### {source_name}")
                for f in findings[:10]:
                    lines.append(f"- **{f.severity.upper()}** {f.title}")
        if self.errors:
            lines.append(f"\n> APIs unavailable: {', '.join(self.errors)}")
        return "\n".join(lines)


def run_security_scan(repo: str, token: str) -> SecurityReport:
    report = SecurityReport(repo=repo)
    report.dependabot = _scan_dependabot(repo, token, report.errors)
    report.codeql = _scan_codeql(repo, token, report.errors)
    report.secrets = _scan_secrets(repo, token, report.errors)
    return report


def _scan_dependabot(repo: str, token: str, errors: list[str]) -> list[SecurityFinding]:
    from tempa.qa.github.client import gh_get

    try:
        alerts = gh_get(f"/repos/{repo}/dependabot/alerts?state=open&per_page=30", token)
        if not isinstance(alerts, list):
            return []
        findings: list[SecurityFinding] = []
        for alert in alerts:
            adv = alert.get("security_advisory", {})
            dep = alert.get("dependency", {})
            pkg = dep.get("package", {}).get("name", "")
            severity = str(adv.get("severity", "medium")).lower()
            cve_ids = [i["value"] for i in adv.get("identifiers", []) if i.get("type") == "CVE"]
            findings.append(
                SecurityFinding(
                    source="dependabot",
                    severity=severity,
                    title=str(adv.get("summary", f"Vulnerability in {pkg}"))[:100],
                    description=str(adv.get("description", ""))[:200],
                    package=pkg,
                    cve_id=cve_ids[0] if cve_ids else "",
                    url=str(alert.get("html_url", "")),
                )
            )
        return findings
    except Exception as exc:
        err = str(exc)
        if "403" in err or "404" in err:
            errors.append("Dependabot")
        else:
            log.warning("dependabot scan failed: %s", exc)
        return []


def _scan_codeql(repo: str, token: str, errors: list[str]) -> list[SecurityFinding]:
    from tempa.qa.github.client import gh_get

    try:
        alerts = gh_get(f"/repos/{repo}/code-scanning/alerts?state=open&per_page=30", token)
        if not isinstance(alerts, list):
            return []
        findings: list[SecurityFinding] = []
        for alert in alerts:
            rule = alert.get("rule", {})
            location = alert.get("most_recent_instance", {}).get("location", {})
            severity = str(rule.get("severity", "medium")).lower()
            if severity == "error":
                severity = "high"
            elif severity == "warning":
                severity = "medium"
            findings.append(
                SecurityFinding(
                    source="codeql",
                    severity=severity,
                    title=str(rule.get("description", rule.get("id", "CodeQL finding")))[:100],
                    description=str(alert.get("message", {}).get("text", ""))[:200],
                    file_path=str(location.get("path", "")),
                    line_number=int(location.get("start_line", 0) or 0),
                    url=str(alert.get("html_url", "")),
                )
            )
        return findings
    except Exception as exc:
        err = str(exc)
        if "403" in err or "404" in err:
            errors.append("CodeQL")
        return []


def _scan_secrets(repo: str, token: str, errors: list[str]) -> list[SecurityFinding]:
    from tempa.qa.github.client import gh_get

    try:
        alerts = gh_get(f"/repos/{repo}/secret-scanning/alerts?state=open&per_page=30", token)
        if not isinstance(alerts, list):
            return []
        findings: list[SecurityFinding] = []
        for alert in alerts:
            secret_type = alert.get("secret_type_display_name", alert.get("secret_type", "Secret"))
            findings.append(
                SecurityFinding(
                    source="secret_scanning",
                    severity="critical",
                    title=f"Exposed {secret_type}",
                    description=str(alert.get("html_url", "")),
                    url=str(alert.get("html_url", "")),
                )
            )
        return findings
    except Exception as exc:
        err = str(exc)
        if "403" in err or "404" in err:
            errors.append("Secret Scanning")
        return []
