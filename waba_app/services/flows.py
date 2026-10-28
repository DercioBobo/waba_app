# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt
"""What every Flow shares: sessions keyed by flow_token, sending, and nfm_reply dispatch.

Each flow type registers its reply handler in REPLY_HANDLERS:
	handler(session, response: dict, wa_id, phone_number_id) -> str
"""

import json

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from waba_app.services import whatsapp
from waba_app.services.logs import to_json
from waba_app.waba_app.doctype.waba_flow_session.waba_flow_session import new_flow_token

SESSION_DOCTYPE = "WABA Flow Session"

REPLY_HANDLERS = {
	"invoices": "waba_app.services.invoice_flow.on_reply",
	"test_request": "waba_app.services.request_flow.on_reply",
}


def start_flow(
	wa_id: str,
	*,
	flow_type: str,
	flow_id: str,
	screen: str,
	data: dict,
	header: str | None,
	body: str,
	cta: str,
	phone_number_id: str | None = None,
	customer: str | None = None,
) -> str:
	"""Creates the session and sends the flow opening on `screen` with `data`."""
	session = frappe.get_doc(
		{
			"doctype": SESSION_DOCTYPE,
			"flow_token": new_flow_token(),
			"wa_id": wa_id,
			"customer": customer,
			"flow_id": flow_id,
			"flow_type": flow_type,
			"status": "Sent",
			"sent_payload": to_json(data),
		}
	).insert(ignore_permissions=True)

	try:
		whatsapp.send_flow(
			wa_id,
			flow_id,
			session.flow_token,
			screen,
			data,
			header=header,
			body=body,
			cta=cta,
			phone_number_id=phone_number_id,
			reference_doctype=SESSION_DOCTYPE,
			reference_name=session.name,
		)
	except whatsapp.WhatsAppAPIError:
		session.db_set("status", "Expired")
		return "send_failed"
	return "sent"


def parse_flow_response(message: dict) -> dict:
	"""interactive.nfm_reply.response_json is a JSON *string*; returns it decoded."""
	raw = ((message.get("interactive") or {}).get("nfm_reply") or {}).get("response_json")
	if not raw:
		raise ValueError("nfm_reply without response_json")
	data = json.loads(raw) if isinstance(raw, str) else raw
	if not isinstance(data, dict):
		raise ValueError("response_json is not an object")
	return data


def load_open_session(flow_token: str | None, wa_id: str) -> Document | None:
	"""The session for this token, if it is still open and was sent to this number."""
	if not flow_token or not isinstance(flow_token, str):
		return None
	if not frappe.db.exists(SESSION_DOCTYPE, flow_token):
		return None
	session = frappe.get_doc(SESSION_DOCTYPE, flow_token)
	if session.status != "Sent" or session.wa_id != wa_id:
		return None
	return session


def handle_flow_reply(wa_id: str, message: dict, *, phone_number_id: str | None = None) -> str:
	"""Routes an nfm_reply to its flow type's handler and closes the session."""
	try:
		response = parse_flow_response(message)
	except ValueError:
		frappe.log_error(title="WABA: invalid nfm_reply", message=to_json(message))
		return "invalid"

	session = load_open_session(response.get("flow_token"), wa_id)
	if not session:
		return "ignored"

	try:
		handler_path = REPLY_HANDLERS.get(session.flow_type)
		if not handler_path:
			frappe.log_error(title=f"WABA: no reply handler for flow type {session.flow_type!r}")
			return "unknown_flow"
		return frappe.get_attr(handler_path)(session, response, wa_id, phone_number_id)
	finally:
		session.db_set({"status": "Completed", "completed_on": now_datetime(), "response_json": to_json(response)})
