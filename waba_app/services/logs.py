# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt
"""Writes to WABA Message Log. Every inbound and outbound message goes through here."""

import json
from typing import Any

import frappe
from frappe.model.document import Document

LOG_DOCTYPE = "WABA Message Log"

# Meta can deliver status webhooks out of order; never move a log backwards.
STATUS_RANK = {"Received": 0, "Sent": 1, "Delivered": 2, "Read": 3, "Failed": 4}
META_STATUS = {"sent": "Sent", "delivered": "Delivered", "read": "Read", "failed": "Failed"}


def to_json(value: Any) -> str | None:
	if value is None or isinstance(value, str):
		return value
	return json.dumps(value, indent=1, ensure_ascii=False, default=str)


def log_message(
	direction: str,
	*,
	status: str,
	wa_id: str | None = None,
	phone_number_id: str | None = None,
	wamid: str | None = None,
	message_type: str | None = None,
	payload: Any = None,
	response: Any = None,
	error: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> Document:
	return frappe.get_doc(
		{
			"doctype": LOG_DOCTYPE,
			"direction": direction,
			"status": status,
			"wa_id": wa_id,
			"phone_number_id": phone_number_id,
			"wamid": wamid,
			"message_type": message_type,
			"payload": to_json(payload),
			"response": to_json(response),
			"error": error,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
		}
	).insert(ignore_permissions=True)


def is_logged(wamid: str) -> bool:
	return bool(frappe.db.exists(LOG_DOCTYPE, {"wamid": wamid}))


def apply_status_update(status: dict) -> None:
	"""One entry of value.statuses[] from the webhook."""
	new_status = META_STATUS.get(status.get("status"))
	wamid = status.get("id")
	if not new_status or not wamid:
		return

	log = frappe.db.get_value(LOG_DOCTYPE, {"wamid": wamid, "direction": "Outbound"}, ["name", "status"], as_dict=True)
	if not log or STATUS_RANK.get(new_status, 0) <= STATUS_RANK.get(log.status, 0):
		return

	values = {"status": new_status}
	if new_status == "Failed":
		values["error"] = "; ".join(
			f"{err.get('code')}: {err.get('title') or err.get('message')}" for err in status.get("errors") or []
		)
	frappe.db.set_value(LOG_DOCTYPE, log.name, values)
