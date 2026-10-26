# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt

from unittest.mock import MagicMock, patch

import requests
from frappe.tests.utils import FrappeTestCase

from waba_app.services import whatsapp
from waba_app.tests.utils import make_settings

TOKEN = "TEST-ACCESS-TOKEN-SECRET"


def http_response(status=200, body=None):
	response = MagicMock(ok=200 <= status < 300, status_code=status)
	response.json.return_value = body if body is not None else {}
	return response


class TestWhatsAppClient(FrappeTestCase):
	def setUp(self):
		self.settings = make_settings()
		patch("waba_app.services.whatsapp.get_settings", return_value=self.settings).start()
		self.post = patch("waba_app.services.whatsapp.requests.post").start()
		self.log = patch("waba_app.services.whatsapp.log_message").start()
		self.addCleanup(patch.stopall)

	def assert_token_not_logged(self):
		for call in self.log.call_args_list:
			self.assertNotIn(TOKEN, repr(call))

	def test_send_text(self):
		self.post.return_value = http_response(body={"messages": [{"id": "wamid.OUT"}]})
		whatsapp.send_text("258841234567", "Olá", phone_number_id="999")

		url = self.post.call_args.args[0]
		kwargs = self.post.call_args.kwargs
		self.assertEqual(url, "https://graph.facebook.com/v25.0/999/messages")
		self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {TOKEN}")
		self.assertEqual(kwargs["json"]["text"]["body"], "Olá")
		self.assertIsNotNone(kwargs["timeout"])

		self.assertEqual(self.log.call_args.kwargs["status"], "Sent")
		self.assertEqual(self.log.call_args.kwargs["wamid"], "wamid.OUT")
		self.assert_token_not_logged()

	def test_default_sender(self):
		self.post.return_value = http_response(body={"messages": [{"id": "w"}]})
		whatsapp.send_text("258841234567", "x")
		self.assertIn(f"/{self.settings.phone_number_id}/messages", self.post.call_args.args[0])

	def test_flow_draft_mode(self):
		self.post.return_value = http_response(body={"messages": [{"id": "w"}]})
		whatsapp.send_flow("258841234567", "FLOW", "tok", "FACTURAS", {"a": "b"}, "H", "B", "CTA")
		parameters = self.post.call_args.kwargs["json"]["interactive"]["action"]["parameters"]
		self.assertEqual(parameters["mode"], "draft")
		self.assertEqual(parameters["flow_token"], "tok")
		self.assertEqual(parameters["flow_action_payload"], {"screen": "FACTURAS", "data": {"a": "b"}})

	def test_flow_published_mode(self):
		self.settings.flow_mode = "published"
		self.post.return_value = http_response(body={"messages": [{"id": "w"}]})
		whatsapp.send_flow("258841234567", "FLOW", "tok", "FACTURAS", {}, None, "B", "CTA")
		interactive = self.post.call_args.kwargs["json"]["interactive"]
		self.assertNotIn("mode", interactive["action"]["parameters"])
		self.assertNotIn("header", interactive)

	def test_graph_error_is_logged_and_raised(self):
		self.post.return_value = http_response(400, {"error": {"code": 131047, "message": "Re-engagement message"}})
		with self.assertRaises(whatsapp.WhatsAppAPIError):
			whatsapp.send_text("258841234567", "x")
		self.assertEqual(self.log.call_args.kwargs["status"], "Failed")
		self.assertIn("131047", self.log.call_args.kwargs["error"])
		self.assert_token_not_logged()

	def test_network_error(self):
		self.post.side_effect = requests.Timeout("timed out")
		with self.assertRaises(whatsapp.WhatsAppAPIError):
			whatsapp.send_text("258841234567", "x")
		self.assertEqual(self.log.call_args.kwargs["status"], "Failed")

	def test_upload_media(self):
		self.post.return_value = http_response(body={"id": "MEDIA-1"})
		media_id = whatsapp.upload_media(b"%PDF-1.4", "SINV-1.pdf", "application/pdf")
		self.assertEqual(media_id, "MEDIA-1")
		kwargs = self.post.call_args.kwargs
		self.assertEqual(kwargs["data"]["messaging_product"], "whatsapp")
		self.assertEqual(kwargs["files"]["file"][0], "SINV-1.pdf")
		self.assertEqual(self.log.call_args.kwargs["payload"]["size"], 8)
		self.assert_token_not_logged()
