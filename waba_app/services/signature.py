# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt

import hashlib
import hmac


def compute_signature(raw_body: bytes, app_secret: str) -> str:
	digest = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
	return f"sha256={digest}"


def verify_signature(raw_body: bytes, header: str | None, app_secret: str) -> bool:
	"""Checks Meta's X-Hub-Signature-256 header ('sha256=<hex>') against the raw body."""
	if not header or not app_secret:
		return False
	return hmac.compare_digest(compute_signature(raw_body, app_secret), header.strip())
