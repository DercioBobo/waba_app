# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from waba_app.services import flows

WA_ID = "258841234567"


def nfm(response_json):
	return {
		"from": WA_ID,
		"id": "wamid.3",
		"type": "interactive",
		"interactive": {"type": "nfm_reply", "nfm_reply": {"name": "flow", "response_json": response_json}},
	}


class TestParseFlowResponse(FrappeTestCase):
	def test_decodes_string(self):
		data = {"flow_token": "tok", "factura": "SINV-1", "accao": "pdf"}
		self.assertEqual(flows.parse_flow_response(nfm(json.dumps(data))), data)

	def test_invalid_payloads(self):
		for message in (nfm(None), nfm(""), nfm("{not json"), nfm("[1, 2]"), {"type": "interactive"}, {}):
			with self.subTest(message=message):
				with self.assertRaises(ValueError):
					flows.parse_flow_response(message)


class TestHandleFlowReply(FrappeTestCase):
	def setUp(self):
		self.handler = MagicMock(return_value="done")
		patch("waba_app.services.flows.frappe.get_attr", return_value=self.handler).start()
		self.addCleanup(patch.stopall)

	def session(self, **overrides):
		values = {"status": "Sent", "wa_id": WA_ID, "customer": "CUST-A", "flow_type": "invoices"}
		values.update(overrides)
		return MagicMock(**values)

	def run_reply(self, session, response=None):
		response = response or {"flow_token": "tok", "factura": "SINV-1", "accao": "pdf"}
		with (
			patch("waba_app.services.flows.frappe.db.exists", return_value=session is not None),
			patch("waba_app.services.flows.frappe.get_doc", return_value=session),
		):
			return flows.handle_flow_reply(WA_ID, nfm(json.dumps(response)), phone_number_id="999")

	def test_dispatches_by_flow_type_and_completes(self):
		session = self.session(flow_type="test_request")
		with patch("waba_app.services.flows.frappe.get_attr", return_value=self.handler) as get_attr:
			self.assertEqual(self.run_reply(session), "done")
			get_attr.assert_called_once_with(flows.REPLY_HANDLERS["test_request"])
		response = self.handler.call_args.args[1]
		self.handler.assert_called_once_with(session, response, WA_ID, "999")
		values = session.db_set.call_args.args[0]
		self.assertEqual(values["status"], "Completed")
		self.assertIn("SINV-1", values["response_json"])

	def test_session_completes_even_if_handler_fails(self):
		session = self.session()
		self.handler.side_effect = RuntimeError("boom")
		with self.assertRaises(RuntimeError):
			self.run_reply(session)
		self.assertEqual(session.db_set.call_args.args[0]["status"], "Completed")

	def test_unknown_flow_type(self):
		session = self.session(flow_type="nope")
		with patch("waba_app.services.flows.frappe.log_error"):
			self.assertEqual(self.run_reply(session), "unknown_flow")
		self.handler.assert_not_called()

	def test_missing_session_is_ignored(self):
		self.assertEqual(self.run_reply(None), "ignored")
		self.handler.assert_not_called()

	def test_completed_session_is_ignored(self):
		session = self.session(status="Completed")
		self.assertEqual(self.run_reply(session), "ignored")
		self.handler.assert_not_called()
		session.db_set.assert_not_called()

	def test_session_of_another_number_is_ignored(self):
		session = self.session(wa_id="258820000000")
		self.assertEqual(self.run_reply(session), "ignored")
		self.handler.assert_not_called()

	def test_invalid_json_is_logged(self):
		with patch("waba_app.services.flows.frappe.log_error") as log_error:
			self.assertEqual(flows.handle_flow_reply(WA_ID, nfm("{bad"), phone_number_id="999"), "invalid")
			log_error.assert_called_once()
		self.handler.assert_not_called()


class TestFlowFiles(FrappeTestCase):
	"""Static Flow JSONs: every ${data.x} is declared, and every navigate payload
	carries exactly the data its target screen declares."""

	def test_references_match_declared_data(self):
		flows_dir = Path(flows.__file__).resolve().parent.parent / "flows"
		for path in flows_dir.glob("*.json"):
			flow = json.loads(path.read_text(encoding="utf-8"))
			self.assertNotIn("routing_model", flow)
			self.assertNotIn("data_api_version", flow)
			screens = {screen["id"]: screen for screen in flow["screens"]}
			for screen in flow["screens"]:
				declared = set(screen.get("data", {}))
				with self.subTest(flow=path.name, screen=screen["id"]):
					for name in re.findall(r"\$\{data\.(\w+)\}", json.dumps(screen["layout"])):
						self.assertIn(name, declared)
					for action in iter_actions(screen["layout"]):
						if action["name"] == "navigate":
							target = screens[action["next"]["name"]]
							self.assertEqual(set(action.get("payload", {})), set(target.get("data", {})))


def iter_actions(node):
	if isinstance(node, dict):
		if "on-click-action" in node:
			yield node["on-click-action"]
		for value in node.values():
			yield from iter_actions(value)
	elif isinstance(node, list):
		for item in node:
			yield from iter_actions(item)
