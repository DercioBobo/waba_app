# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt

from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from waba_app.services import handlers
from waba_app.tests.utils import make_settings

WA_ID = "258841234567"
PNID = "999"


def text(body):
	return {"from": WA_ID, "id": "wamid.1", "type": "text", "text": {"body": body}}


class TestKeywordRouting(FrappeTestCase):
	def setUp(self):
		self.mocks = {
			name: patch(f"waba_app.services.handlers.{name}").start() for name in ("handle_flow_reply", "reply")
		}
		self.mocks["start_invoice_flow"] = MagicMock()
		self.mocks["start_test_request_flow"] = MagicMock()
		patch(
			"waba_app.services.handlers.KEYWORD_FLOWS",
			(
				("invoice_keywords", self.mocks["start_invoice_flow"]),
				("test_request_keywords", self.mocks["start_test_request_flow"]),
			),
		).start()
		patch("waba_app.services.handlers.get_settings", return_value=make_settings()).start()
		self.addCleanup(patch.stopall)

	def test_keyword_starts_invoice_flow(self):
		for body in ("facturas", "  Facturas ", "FATURAS", "invoice\n"):
			with self.subTest(body=body):
				self.mocks["start_invoice_flow"].reset_mock()
				handlers.route_message(WA_ID, text(body), PNID)
				self.mocks["start_invoice_flow"].assert_called_once_with(WA_ID, phone_number_id=PNID)
		self.mocks["reply"].assert_not_called()
		self.mocks["start_test_request_flow"].assert_not_called()

	def test_keyword_starts_test_request_flow(self):
		handlers.route_message(WA_ID, text(" Teste "), PNID)
		self.mocks["start_test_request_flow"].assert_called_once_with(WA_ID, phone_number_id=PNID)
		self.mocks["start_invoice_flow"].assert_not_called()

	def test_keyword_inside_sentence_gets_help(self):
		handlers.route_message(WA_ID, text("quero as facturas"), PNID)
		self.mocks["start_invoice_flow"].assert_not_called()
		self.mocks["reply"].assert_called_once_with(WA_ID, handlers.HELP_TEXT, PNID)

	def test_nfm_reply_goes_to_flow_handler(self):
		message = {
			"from": WA_ID,
			"id": "wamid.2",
			"type": "interactive",
			"interactive": {"type": "nfm_reply", "nfm_reply": {"response_json": "{}"}},
		}
		handlers.route_message(WA_ID, message, PNID)
		self.mocks["handle_flow_reply"].assert_called_once_with(WA_ID, message, phone_number_id=PNID)

	def test_other_messages_get_help(self):
		for message in (
			{"type": "image", "image": {"id": "1"}},
			{"type": "interactive", "interactive": {"type": "button_reply"}},
			{"type": "text", "text": {}},
		):
			with self.subTest(message=message):
				self.mocks["reply"].reset_mock()
				handlers.route_message(WA_ID, message, PNID)
				self.mocks["reply"].assert_called_once_with(WA_ID, handlers.HELP_TEXT, PNID)
		self.mocks["start_invoice_flow"].assert_not_called()


class TestIsKeyword(FrappeTestCase):
	def test_matching(self):
		keywords = {"facturas", "invoice"}
		self.assertTrue(handlers.is_keyword(" FACTURAS ", keywords))
		self.assertFalse(handlers.is_keyword("factura", keywords))
		self.assertFalse(handlers.is_keyword("", keywords))
		self.assertFalse(handlers.is_keyword(None, keywords))


class TestIsOwnNumber(FrappeTestCase):
	def test_only_configured_number(self):
		self.assertTrue(handlers.is_own_number("111", "111"))
		self.assertFalse(handlers.is_own_number("222", "111"))
		self.assertFalse(handlers.is_own_number(None, "111"))
		self.assertFalse(handlers.is_own_number("111", ""))
		self.assertFalse(handlers.is_own_number("111", None))


class TestIterMessageChanges(FrappeTestCase):
	def test_only_messages_field(self):
		payload = {
			"entry": [
				{"changes": [{"field": "messages", "value": {"a": 1}}, {"field": "account_update", "value": {"b": 2}}]},
				{"changes": [{"field": "messages", "value": {"c": 3}}]},
			]
		}
		self.assertEqual(list(handlers.iter_message_changes(payload)), [{"a": 1}, {"c": 3}])
