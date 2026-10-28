# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt
"""Background processing of webhook notifications and message routing."""

import json

import frappe

from waba_app.services import logs
from waba_app.services.flows import handle_flow_reply
from waba_app.services.invoice_flow import start_invoice_flow
from waba_app.services.messaging import reply
from waba_app.services.request_flow import start_test_request_flow
from waba_app.waba_app.doctype.waba_settings.waba_settings import get_settings

HELP_TEXT = "Escreve *facturas* para ver as tuas facturas pendentes."

# Settings keyword field -> flow it starts. First match wins.
KEYWORD_FLOWS = (
	("invoice_keywords", start_invoice_flow),
	("test_request_keywords", start_test_request_flow),
)
ERROR_TEXT = "Não foi possível processar o teu pedido. Tenta novamente mais tarde."

RATE_LIMIT_MESSAGES = 10
RATE_LIMIT_WINDOW_SECONDS = 60


def process_webhook(log_name: str) -> None:
	"""Job enqueued by the webhook with the raw notification log."""
	# The webhook request is a Guest; printing invoices needs a real user.
	frappe.set_user("Administrator")
	payload = json.loads(frappe.db.get_value(logs.LOG_DOCTYPE, log_name, "payload") or "{}")
	own_number = get_settings().phone_number_id

	for value in iter_message_changes(payload):
		phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
		if not is_own_number(phone_number_id, own_number):
			continue
		for status in value.get("statuses") or []:
			logs.apply_status_update(status)
		for message in value.get("messages") or []:
			process_message(message, phone_number_id)


def iter_message_changes(payload: dict):
	for entry in payload.get("entry") or []:
		for change in entry.get("changes") or []:
			if change.get("field") == "messages":
				yield change.get("value") or {}


def is_own_number(phone_number_id: str | None, own_number: str | None) -> bool:
	"""Only act on the number configured in WABA Settings, so a webhook for another
	number (e.g. production subscribed by mistake) never gets replies from here."""
	return bool(own_number) and phone_number_id == own_number


def process_message(message: dict, phone_number_id: str | None) -> None:
	wamid, wa_id = message.get("id"), message.get("from")
	if not wamid or not wa_id or logs.is_logged(wamid):
		return  # Meta retried a notification we already have.

	try:
		log = logs.log_message(
			"Inbound",
			status="Received",
			wa_id=wa_id,
			phone_number_id=phone_number_id,
			wamid=wamid,
			message_type=message.get("type"),
			payload=message,
		)
		frappe.db.commit()
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		frappe.db.rollback()  # A concurrent job logged it first.
		return

	if is_rate_limited(wa_id):
		frappe.db.set_value(logs.LOG_DOCTYPE, log.name, "error", "Ignored: rate limit exceeded")
		return

	try:
		route_message(wa_id, message, phone_number_id)
	except Exception:
		frappe.log_error(title="WABA: message processing failed", reference_doctype=logs.LOG_DOCTYPE, reference_name=log.name)
		reply(wa_id, ERROR_TEXT, phone_number_id)
	frappe.db.commit()


def route_message(wa_id: str, message: dict, phone_number_id: str | None) -> None:
	message_type = message.get("type")

	if message_type == "text":
		start = flow_for_text((message.get("text") or {}).get("body"), get_settings())
		if start:
			start(wa_id, phone_number_id=phone_number_id)
			return

	elif message_type == "interactive" and (message.get("interactive") or {}).get("type") == "nfm_reply":
		handle_flow_reply(wa_id, message, phone_number_id=phone_number_id)
		return

	reply(wa_id, HELP_TEXT, phone_number_id)


def flow_for_text(text: str | None, settings):
	"""The flow starter whose keyword is the whole message, or None."""
	for fieldname, start in KEYWORD_FLOWS:
		if is_keyword(text, settings.get_keywords(fieldname)):
			return start
	return None


def is_keyword(text: str | None, keywords: set[str]) -> bool:
	return bool(text) and text.strip().casefold() in keywords


def is_rate_limited(wa_id: str) -> bool:
	"""More than RATE_LIMIT_MESSAGES from one number inside the window."""
	cache = frappe.cache()
	key = cache.make_key(f"waba_app:rate:{wa_id}")
	try:
		count = cache.incr(key)
		if count == 1:
			cache.expire(key, RATE_LIMIT_WINDOW_SECONDS)
	except Exception:
		return False  # Never drop messages because Redis hiccuped.
	return count > RATE_LIMIT_MESSAGES
