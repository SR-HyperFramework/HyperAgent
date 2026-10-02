"""Unit tests for the DataAnonymizer — PII scrubbing before Cloud API."""
from __future__ import annotations

import pytest

from hyperagent.tools.anonymizer import (
    AnonymizationSummary,
    DataAnonymizer,
    DEFAULT_INTERNAL_DOMAIN_SUFFIXES,
)


class TestPrivateIPv4:
    """RFC 1918 + loopback addresses must be scrubbed."""

    def test_rfc1918_10_x(self):
        anon = DataAnonymizer()
        text = "Connecting to 10.0.0.1 on port 443"
        result, tmap = anon.anonymize(text)
        assert "10.0.0.1" not in result
        assert "[INTERNAL_IP_1]" in result
        assert tmap["[INTERNAL_IP_1]"] == "10.0.0.1"

    def test_rfc1918_172_16(self):
        anon = DataAnonymizer()
        text = "Beacon to 172.16.5.100"
        result, tmap = anon.anonymize(text)
        assert "172.16.5.100" not in result
        assert "[INTERNAL_IP_1]" in result

    def test_rfc1918_192_168(self):
        anon = DataAnonymizer()
        text = "C2 callback to 192.168.1.100 every 60s"
        result, tmap = anon.anonymize(text)
        assert "192.168.1.100" not in result
        assert "[INTERNAL_IP_1]" in result
        assert tmap["[INTERNAL_IP_1]"] == "192.168.1.100"

    def test_loopback_127(self):
        anon = DataAnonymizer()
        text = "Listening on 127.0.0.1:8080"
        result, _ = anon.anonymize(text)
        assert "127.0.0.1" not in result
        assert "[INTERNAL_IP_1]" in result

    def test_public_ip_not_scrubbed(self):
        anon = DataAnonymizer()
        text = "Resolves to 8.8.8.8"
        result, tmap = anon.anonymize(text)
        assert "8.8.8.8" in result
        assert len(tmap) == 0

    def test_multiple_ips_get_unique_tokens(self):
        anon = DataAnonymizer()
        text = "10.0.0.1 connects to 192.168.1.1"
        result, tmap = anon.anonymize(text)
        assert "[INTERNAL_IP_1]" in result
        assert "[INTERNAL_IP_2]" in result
        assert len(tmap) == 2

    def test_same_ip_gets_stable_token(self):
        anon = DataAnonymizer()
        text = "10.0.0.1 then again 10.0.0.1"
        result, tmap = anon.anonymize(text)
        assert result.count("[INTERNAL_IP_1]") == 2
        assert len(tmap) == 1


class TestUserPaths:
    """Windows and Linux user paths must have usernames scrubbed."""

    def test_windows_user_path(self):
        anon = DataAnonymizer()
        text = r"Reading C:\Users\victim\Desktop\malware.exe"
        result, tmap = anon.anonymize(text)
        assert "victim" not in result
        assert "[USER_PATH_1]" in result

    def test_linux_home_path(self):
        anon = DataAnonymizer()
        text = "Dropped to /home/analyst/samples/payload.bin"
        result, tmap = anon.anonymize(text)
        assert "analyst" not in result
        assert "[USER_PATH_1]" in result

    def test_multiple_users(self):
        anon = DataAnonymizer()
        text = r"C:\Users\alice\file.txt and C:\Users\bob\file.txt"
        result, tmap = anon.anonymize(text)
        assert "alice" not in result
        assert "bob" not in result
        assert "[USER_PATH_1]" in result
        assert "[USER_PATH_2]" in result


class TestAPIKeys:
    """Common API key prefixes must be detected and scrubbed."""

    def test_openai_key(self):
        anon = DataAnonymizer()
        text = 'api_key = "sk-proj1234567890abcdefgh"'
        result, tmap = anon.anonymize(text)
        assert "sk-proj1234567890abcdefgh" not in result
        assert "[API_KEY_1]" in result

    def test_aws_access_key(self):
        anon = DataAnonymizer()
        text = "aws_key=AKIAIOSFODNN7EXAMPLE"
        result, tmap = anon.anonymize(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "[API_KEY_1]" in result

    def test_github_pat(self):
        anon = DataAnonymizer()
        # Use a context that doesn't trigger the credential regex (token:)
        text = "Authorization ghp_1234567890abcdefghij attached"
        result, tmap = anon.anonymize(text)
        assert "ghp_1234567890abcdefghij" not in result
        assert "[API_KEY_1]" in result


class TestCredentials:
    """Hardcoded passwords and secrets must be scrubbed."""

    def test_password_equals(self):
        anon = DataAnonymizer()
        text = 'password="SuperSecret123!"'
        result, tmap = anon.anonymize(text)
        assert "SuperSecret123!" not in result
        assert "[CREDENTIAL_1]" in result

    def test_passwd_colon(self):
        anon = DataAnonymizer()
        text = "passwd: my_s3cr3t_pwd"
        result, tmap = anon.anonymize(text)
        assert "my_s3cr3t_pwd" not in result
        assert "[CREDENTIAL_1]" in result

    def test_secret_in_config(self):
        anon = DataAnonymizer()
        text = "secret = abcdef12345678"
        result, tmap = anon.anonymize(text)
        assert "abcdef12345678" not in result
        assert "[CREDENTIAL_1]" in result


class TestInternalDomains:
    """FQDNs with internal suffixes must be scrubbed."""

    def test_corp_domain(self):
        anon = DataAnonymizer()
        text = "DNS lookup for dc01.acme.corp failed"
        result, tmap = anon.anonymize(text)
        assert "dc01.acme.corp" not in result
        assert "[INTERNAL_DOMAIN_1]" in result
        assert tmap["[INTERNAL_DOMAIN_1]"] == "dc01.acme.corp"

    def test_local_domain(self):
        anon = DataAnonymizer()
        text = "Resolved printer.office.local to 10.0.0.50"
        result, tmap = anon.anonymize(text)
        assert "printer.office.local" not in result
        assert "[INTERNAL_DOMAIN_1]" in result

    def test_public_domain_not_scrubbed(self):
        anon = DataAnonymizer()
        text = "C2 at evil.example.com"
        result, tmap = anon.anonymize(text)
        assert "evil.example.com" in result


class TestEmails:
    """Email addresses must be scrubbed."""

    def test_email_replaced(self):
        anon = DataAnonymizer()
        text = "Contact: admin@internal.corp"
        result, tmap = anon.anonymize(text)
        # Note: both email and domain pattern might fire — email first
        assert "admin@internal.corp" not in result


class TestRestore:
    """Token maps can be reversed to get original text back."""

    def test_round_trip(self):
        anon = DataAnonymizer()
        original = "Server at 192.168.1.100, user C:\\Users\\victim\\Desktop"
        anonymized, tmap = anon.anonymize(original)
        assert "192.168.1.100" not in anonymized
        assert "victim" not in anonymized

        restored = anon.restore(anonymized, tmap)
        assert "192.168.1.100" in restored
        assert "victim" in restored

    def test_restore_with_internal_map(self):
        anon = DataAnonymizer()
        original = "10.0.0.1 connects"
        anonymized, _ = anon.anonymize(original)
        # Restore using internal map (no explicit token_map arg)
        restored = anon.restore(anonymized)
        assert "10.0.0.1" in restored


class TestSummary:
    """Counts per category for telemetry."""

    def test_summary_counts(self):
        anon = DataAnonymizer()
        text = (
            "10.0.0.1 connects to dc.acme.corp "
            "from C:\\Users\\victim\\Desktop "
            'with password="abc12345"'
        )
        anon.anonymize(text)
        summary = anon.get_summary()
        assert summary.internal_ips >= 1
        assert summary.internal_domains >= 1
        assert summary.user_paths >= 1
        assert summary.credentials >= 1
        assert summary.total() >= 4


class TestReset:
    """Reset clears all state."""

    def test_reset_clears_mappings(self):
        anon = DataAnonymizer()
        anon.anonymize("10.0.0.1 connects to dc.acme.corp")
        assert anon.get_summary().total() > 0

        anon.reset()
        assert anon.get_summary().total() == 0

        # After reset, same value gets same index (starts from 1 again)
        _, tmap = anon.anonymize("10.0.0.1")
        assert "[INTERNAL_IP_1]" in tmap


class TestInjectionGuardIntegration:
    """Verify the injection_guard properly integrates the anonymizer."""

    def test_build_system_prompt_returns_tuple(self):
        from hyperagent.engine.injection_guard import build_system_prompt

        prompt, tmap = build_system_prompt(
            skill_instructions="Connect to 192.168.1.100",
            reads_sample_content=True,
        )
        assert isinstance(prompt, str)
        assert isinstance(tmap, dict)
        assert "INJECTION_GUARD" not in prompt  # The guard text shouldn't contain this literal
        assert "SECURITY CONSTRAINT" in prompt

    def test_build_system_prompt_no_sample_no_scrub(self):
        from hyperagent.engine.injection_guard import build_system_prompt

        prompt, tmap = build_system_prompt(
            skill_instructions="Connect to 192.168.1.100",
            reads_sample_content=False,
        )
        # When reads_sample_content=False, no anonymization
        assert "192.168.1.100" in prompt
        assert len(tmap) == 0

    def test_build_system_prompt_anonymize_disabled(self):
        from hyperagent.engine.injection_guard import build_system_prompt

        prompt, tmap = build_system_prompt(
            skill_instructions="Connect to 192.168.1.100",
            reads_sample_content=True,
            anonymize=False,
        )
        # Anonymization explicitly disabled — IP stays
        assert "192.168.1.100" in prompt
        assert len(tmap) == 0
