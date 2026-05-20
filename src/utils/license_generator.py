"""
Admin-only license generator.

This module must not run without an explicit admin secret in the environment.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import sys


def _get_secret_key() -> str:
    """Load the signing secret from the environment and fail closed if missing."""
    key = os.environ.get("REVERIE_SECRET_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "REVERIE_SECRET_KEY is required for license generation. "
            "Set it before running the admin tool."
        )
    return key


class LicenseGenerator:
    """
    Generate admin-side license keys in the existing Reverie format.

    Format: XXXXX-XXXXX-XXXXX-X-XXXXX
    """

    def __init__(self, secret_key: str | None = None):
        self.secret_key = secret_key or _get_secret_key()

    def generate(
        self,
        user_id: str,
        hardware_id: str,
        duration_days: int = 30,
        license_type: str = "A",
    ) -> str:
        """Create a new license key."""
        user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:5].upper()

        expire_date = datetime.datetime.now() + datetime.timedelta(days=duration_days)
        expire_str = expire_date.strftime("%Y%m%d")
        expire_int = int(expire_str)
        expire_encoded = self._to_base36(expire_int).zfill(5).upper()

        hw_hash = hashlib.sha256(hardware_id.encode()).hexdigest()[:5].upper()

        verification_string = (
            f"{user_hash}{expire_encoded}{hw_hash}{license_type}{self.secret_key}"
        )
        verification = hashlib.sha256(verification_string.encode()).hexdigest()[:5].upper()

        return f"{user_hash}-{expire_encoded}-{hw_hash}-{license_type}-{verification}"

    def _to_base36(self, num: int) -> str:
        if num == 0:
            return "0"

        alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        result = ""
        while num > 0:
            num, remainder = divmod(num, 36)
            result = alphabet[remainder] + result
        return result

    def decode_license(self, license_key: str) -> dict:
        """Decode a license key for admin inspection."""
        parts = license_key.split("-")
        if len(parts) != 5:
            return {"error": "Invalid format"}

        user_hash, expire_encoded, hw_hash, license_type, verification = parts

        try:
            expire_int = int(expire_encoded, 36)
            expire_str = str(expire_int).zfill(8)
            expire_date = datetime.datetime.strptime(expire_str, "%Y%m%d")
        except Exception:
            expire_date = None

        type_map = {
            "A": "All",
            "H": "Horror",
            "T": "Touching",
            "M": "Makjang",
            "P": "Pack-based",
            "S": "Senior",
        }

        return {
            "user_hash": user_hash,
            "expire_date": expire_date.strftime("%Y-%m-%d") if expire_date else "Unknown",
            "hardware_hash": hw_hash,
            "type_code": license_type,
            "type_desc": type_map.get(license_type, "Unknown"),
            "verification": verification,
        }


def _main() -> int:
    print("=" * 60)
    print("Reverie Automation - License Generator")
    print("=" * 60)

    try:
        generator = LicenseGenerator()
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 1

    if len(sys.argv) == 1:
        print("\nEnter user information")
        print("-" * 60)

        user_id = input("User ID (email or name): ").strip()
        if not user_id:
            print("ERROR: User ID is required")
            return 1

        hardware_id = input("Hardware ID (16 chars): ").strip().upper()
        if not hardware_id:
            print("ERROR: Hardware ID is required")
            return 1

        duration_input = input("Duration in days [30]: ").strip()
        duration_days = int(duration_input) if duration_input else 30

        license_type = input("License type [A/H/T/M/P/S, default P]: ").strip().upper() or "P"

        license_key = generator.generate(
            user_id=user_id,
            hardware_id=hardware_id,
            duration_days=duration_days,
            license_type=license_type,
        )

        print("\nGenerated license")
        print("-" * 60)
        print(license_key)
        print("-" * 60)
        print(generator.decode_license(license_key))
        return 0

    print("Usage: python src/utils/license_generator.py")
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
