# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt
"""The 'facturas' use case: list unpaid Sales Invoices in a Flow and act on the choice."""

import frappe
from frappe.utils import flt, fmt_money, getdate
from frappe.utils.pdf import get_pdf

from waba_app.services import whatsapp
from waba_app.services.customers import find_customer_by_phone
from waba_app.services.flows import start_flow
from waba_app.services.messaging import reply
from waba_app.waba_app.doctype.waba_settings.waba_settings import get_settings

FLOW_TYPE = "invoices"
SCREEN = "FACTURAS"
MAX_INVOICES = 10
MAX_SUMMARY_ITEMS = 5
# RadioButtonsGroup limits titles to 30 characters.
MAX_TITLE_LENGTH = 30

TEXT_NO_CUSTOMER = "Não encontrámos uma conta associada a este número."
TEXT_NO_INVOICES = "Não tens facturas pendentes."
TEXT_UNAVAILABLE = "Esta factura já não está disponível. Escreve *facturas* para ver a lista actualizada."
TEXT_PAYMENT_SOON = "Pagamento via WhatsApp disponível brevemente."
TEXT_NOT_CONFIGURED = "Este serviço ainda não está disponível."


def start_invoice_flow(wa_id: str, *, phone_number_id: str | None = None) -> str:
	"""Sends the invoice Flow. Returns what happened, for logs and the dev helper."""
	settings = get_settings()
	if not settings.invoice_flow_id:
		frappe.log_error(title="WABA: Invoice Flow ID is not configured")
		reply(wa_id, TEXT_NOT_CONFIGURED, phone_number_id)
		return "not_configured"

	customer = find_customer_by_phone(wa_id)
	if not customer:
		reply(wa_id, TEXT_NO_CUSTOMER, phone_number_id)
		return "no_customer"

	invoices = get_unpaid_invoices(customer, settings.company)
	if not invoices:
		reply(wa_id, TEXT_NO_INVOICES, phone_number_id)
		return "no_invoices"

	customer_name = frappe.db.get_value("Customer", customer, "customer_name") or customer
	data = {
		"saudacao": f"Olá {customer_name}, estas são as tuas facturas pendentes.",
		"facturas": [invoice_option(invoice) for invoice in invoices],
	}

	return start_flow(
		wa_id,
		flow_type=FLOW_TYPE,
		flow_id=settings.invoice_flow_id,
		screen=SCREEN,
		data=data,
		header="Facturas pendentes",
		body="Escolhe uma factura e o que queres fazer com ela.",
		cta="Ver facturas",
		phone_number_id=phone_number_id,
		customer=customer,
	)


def get_unpaid_invoices(customer: str, company: str | None = None) -> list[dict]:
	filters = {"docstatus": 1, "outstanding_amount": [">", 0], "customer": customer}
	if company:
		filters["company"] = company
	return frappe.get_all(
		"Sales Invoice",
		filters=filters,
		fields=["name", "currency", "outstanding_amount", "due_date"],
		order_by="due_date asc",
		limit=MAX_INVOICES,
	)


def invoice_option(invoice: dict) -> dict:
	return {
		"id": invoice["name"],
		"title": invoice["name"][:MAX_TITLE_LENGTH],
		"description": f"{invoice['currency']} {format_amount(invoice['outstanding_amount'])} · vence {format_date(invoice['due_date'])}",
	}


def format_amount(value) -> str:
	return fmt_money(flt(value), precision=2)


def format_date(value) -> str:
	return getdate(value).strftime("%d/%m/%Y") if value else "-"


def on_reply(session, response: dict, wa_id: str, phone_number_id: str | None) -> str:
	"""Flow reply handler (see flows.REPLY_HANDLERS)."""
	invoice = get_owned_outstanding_invoice(response.get("factura"), session.customer, get_settings().company)
	if not invoice:
		reply(wa_id, TEXT_UNAVAILABLE, phone_number_id)
		return "unavailable"
	return perform_action(response.get("accao"), invoice.name, wa_id, phone_number_id)


def get_owned_outstanding_invoice(invoice_name, customer: str, company: str | None = None):
	"""Never trust the Flow payload: the invoice must still be this customer's and unpaid."""
	if not invoice_name or not isinstance(invoice_name, str) or not customer:
		return None
	invoice = frappe.db.get_value(
		"Sales Invoice",
		invoice_name,
		["name", "customer", "company", "docstatus", "outstanding_amount"],
		as_dict=True,
	)
	if not invoice or invoice.customer != customer or invoice.docstatus != 1:
		return None
	if flt(invoice.outstanding_amount) <= 0:
		return None
	if company and invoice.company != company:
		return None
	return invoice


def perform_action(action: str | None, invoice_name: str, wa_id: str, phone_number_id: str | None) -> str:
	if action == "pdf":
		send_invoice_pdf(invoice_name, wa_id, phone_number_id)
	elif action == "detalhes":
		reply(wa_id, invoice_summary(invoice_name), phone_number_id, reference_doctype="Sales Invoice", reference_name=invoice_name)
	elif action == "pagar":
		reply(wa_id, TEXT_PAYMENT_SOON, phone_number_id, reference_doctype="Sales Invoice", reference_name=invoice_name)
	else:
		return "unknown_action"
	return action


def send_invoice_pdf(invoice_name: str, wa_id: str, phone_number_id: str | None) -> None:
	pdf = get_pdf(frappe.get_print("Sales Invoice", invoice_name))
	filename = f"{invoice_name}.pdf"
	reference = {"reference_doctype": "Sales Invoice", "reference_name": invoice_name}
	media_id = whatsapp.upload_media(pdf, filename, "application/pdf", phone_number_id=phone_number_id, **reference)
	whatsapp.send_document(wa_id, media_id, filename, f"Factura {invoice_name}", phone_number_id=phone_number_id, **reference)


def invoice_summary(invoice_name: str) -> str:
	invoice = frappe.get_doc("Sales Invoice", invoice_name)
	lines = [
		f"*Factura {invoice.name}*",
		f"Data: {format_date(invoice.posting_date)}",
		f"Vencimento: {format_date(invoice.due_date)}",
		f"Total: {invoice.currency} {format_amount(invoice.grand_total)}",
		f"Em dívida: {invoice.currency} {format_amount(invoice.outstanding_amount)}",
	]
	if invoice.items:
		lines += ["", "*Itens*"]
		for item in invoice.items[:MAX_SUMMARY_ITEMS]:
			lines.append(f"• {item.item_name} — Qtd {flt(item.qty):g} · {invoice.currency} {format_amount(item.amount)}")
		if len(invoice.items) > MAX_SUMMARY_ITEMS:
			lines.append(f"… e mais {len(invoice.items) - MAX_SUMMARY_ITEMS} itens")
	return "\n".join(lines)
