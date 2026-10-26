# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt
"""Meta webhook: https://<site>/api/method/waba_app.api.webhook.receive

Only accepts, checks and logs the request; processing runs in a background job
so Meta gets its 200 quickly.
"""

import json

import frappe
from werkzeug.wrappers import Response

from waba_app.services.logs import log_message
from waba_app.services.signature import verify_signature
from waba_app.waba_app.doctype.waba_settings.waba_settings import get_settings


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def receive(*args, **kwargs) -> Response:
	if frappe.request.method == "GET":
		return _verify_subscription()
	return _accept_notification()


def _plain(body: str, status: int) -> Response:
	return Response(body, status=status, mimetype="text/plain")


def _verify_subscription() -> Response:
	challenge = check_verification(frappe.request.args, get_settings().verify_token)
	if challenge is None:
		return _plain("Forbidden", 403)
	return _plain(challenge, 200)


def check_verification(params, verify_token: str | None) -> str | None:
	"""Meta's GET handshake: the challenge to echo back, or None to refuse."""
	if not verify_token:
		return None
	if params.get("hub.mode") != "subscribe" or params.get("hub.verify_token") != verify_token:
		return None
	return params.get("hub.challenge") or ""


def _accept_notification() -> Response:
	settings = get_settings()
	raw_body = frappe.request.get_data() or b""

	app_secret = settings.get_password("app_secret", raise_exception=False)
	if app_secret:
		if not verify_signature(raw_body, frappe.request.headers.get("X-Hub-Signature-256"), app_secret):
			return _plain("Invalid signature", 401)
	else:
		frappe.logger("waba_app").warning("WABA webhook received without App Secret configured")

	if not settings.enabled:
		return _plain("OK", 200)

	try:
		payload = json.loads(raw_body)
	except ValueError:
		return _plain("Invalid JSON", 400)

	log = log_message("Inbound", status="Received", message_type="webhook", payload=payload)
	frappe.enqueue(
		"waba_app.services.handlers.process_webhook",
		queue="short",
		log_name=log.name,
		enqueue_after_commit=True,
	)
	return _plain("OK", 200)
