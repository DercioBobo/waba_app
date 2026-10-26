# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt
"""Thin WhatsApp Cloud API (Graph API) client.

Every call is logged to WABA Message Log. The access token only ever travels in
the Authorization header and is never written to a log.
"""

from typing import Any

import requests

from waba_app.services.logs import log_message
from waba_app.waba_app.doctype.waba_settings.waba_settings import get_settings

GRAPH_URL = "https://graph.facebook.com"
TIMEOUT = (5, 30)  # (connect, read) seconds


class WhatsAppAPIError(Exception):
	pass


def send_text(
	to: str,
	body: str,
	*,
	phone_number_id: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> dict:
	return _send_message(
		to,
		"text",
		{"preview_url": False, "body": body},
		phone_number_id=phone_number_id,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)


def send_flow(
	to: str,
	flow_id: str,
	flow_token: str,
	screen: str,
	data: dict,
	header: str | None,
	body: str,
	cta: str,
	*,
	phone_number_id: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> dict:
	parameters: dict[str, Any] = {
		"flow_message_version": "3",
		"flow_token": flow_token,
		"flow_id": flow_id,
		"flow_cta": cta,
		"flow_action": "navigate",
		"flow_action_payload": {"screen": screen, "data": data},
	}
	if get_settings().flow_mode == "draft":
		parameters["mode"] = "draft"

	interactive: dict[str, Any] = {
		"type": "flow",
		"body": {"text": body},
		"action": {"name": "flow", "parameters": parameters},
	}
	if header:
		interactive["header"] = {"type": "text", "text": header}

	return _send_message(
		to,
		"interactive",
		interactive,
		phone_number_id=phone_number_id,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)


def send_document(
	to: str,
	media_id: str,
	filename: str,
	caption: str | None = None,
	*,
	phone_number_id: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> dict:
	document = {"id": media_id, "filename": filename}
	if caption:
		document["caption"] = caption
	return _send_message(
		to,
		"document",
		document,
		phone_number_id=phone_number_id,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)


def upload_media(
	file_bytes: bytes,
	filename: str,
	mime: str,
	*,
	phone_number_id: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> str:
	"""POST /{phone_number_id}/media -> media id."""
	settings = get_settings()
	sender = phone_number_id or settings.phone_number_id
	log_payload = {"filename": filename, "mime": mime, "size": len(file_bytes)}

	response = _request(
		_url(settings, sender, "media"),
		files={"file": (filename, file_bytes, mime)},
		data={"messaging_product": "whatsapp", "type": mime},
		log=dict(
			phone_number_id=sender,
			message_type="media",
			payload=log_payload,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
		),
	)
	media_id = response.get("id")
	if not media_id:
		raise WhatsAppAPIError("Media upload returned no id")
	return media_id


def _send_message(
	to: str,
	message_type: str,
	content: dict,
	*,
	phone_number_id: str | None,
	reference_doctype: str | None,
	reference_name: str | None,
) -> dict:
	settings = get_settings()
	sender = phone_number_id or settings.phone_number_id
	payload = {
		"messaging_product": "whatsapp",
		"recipient_type": "individual",
		"to": to,
		"type": message_type,
		message_type: content,
	}
	return _request(
		_url(settings, sender, "messages"),
		json=payload,
		log=dict(
			wa_id=to,
			phone_number_id=sender,
			message_type=message_type,
			payload=payload,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
		),
	)


def _url(settings, phone_number_id: str | None, path: str) -> str:
	if not phone_number_id:
		raise WhatsAppAPIError("Phone Number ID is not configured in WABA Settings")
	return f"{GRAPH_URL}/{settings.graph_api_version}/{phone_number_id}/{path}"


def _request(url: str, *, log: dict, **kwargs) -> dict:
	"""POSTs to the Graph API, logs the outcome and raises WhatsAppAPIError on failure."""
	token = get_settings().get_password("access_token", raise_exception=False)
	if not token:
		log_message("Outbound", status="Failed", error="Access Token is not configured", **log)
		raise WhatsAppAPIError("Access Token is not configured in WABA Settings")

	try:
		response = requests.post(url, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT, **kwargs)
	except requests.RequestException as e:
		log_message("Outbound", status="Failed", error=f"{type(e).__name__}: {e}", **log)
		raise WhatsAppAPIError(str(e)) from e

	body = _json_or_text(response)
	if not response.ok:
		error = _graph_error(body) or f"HTTP {response.status_code}"
		log_message("Outbound", status="Failed", response=body, error=error, **log)
		raise WhatsAppAPIError(error)

	wamid = None
	if isinstance(body, dict) and body.get("messages"):
		wamid = body["messages"][0].get("id")
	log_message("Outbound", status="Sent", response=body, wamid=wamid, **log)
	return body if isinstance(body, dict) else {}


def _json_or_text(response: requests.Response) -> dict | str:
	try:
		return response.json()
	except ValueError:
		return response.text


def _graph_error(body: dict | str) -> str | None:
	if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
		return None
	err = body["error"]
	details = (err.get("error_data") or {}).get("details")
	message = f"{err.get('code')}: {err.get('message')}"
	return f"{message} ({details})" if details else message
