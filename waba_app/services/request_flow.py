# Copyright (c) 2026, Dércio Bobo and contributors
# For license information, please see license.txt
"""Multi-screen test flow (static, no endpoint): INICIO -> DETALHES -> CONFIRMAR.

"GET": every list the screens need (categories, periods, extras) is read from
ERPNext when the flow is sent and travels from screen to screen in the navigate
payloads. "POST": the final `complete` arrives as an nfm_reply and becomes a
WABA Test Request after every field is validated again.
"""

from datetime import date, datetime, timezone

import frappe
from frappe.utils import getdate

from waba_app.services.customers import find_customer_by_phone
from waba_app.services.flows import start_flow
from waba_app.services.logs import to_json
from waba_app.services.messaging import reply
from waba_app.waba_app.doctype.waba_settings.waba_settings import get_settings

FLOW_TYPE = "test_request"
FIRST_SCREEN = "INICIO"
REQUEST_DOCTYPE = "WABA Test Request"
CATEGORY_DOCTYPE = "WABA Test Category"

# Dropdown accepts up to 200 options; titles are limited to 30 characters.
MAX_OPTIONS = 200
MAX_TITLE_LENGTH = 30
MAX_NAME_LENGTH = 80
MAX_NOTES_LENGTH = 500

EXTRAS = [
	{"id": "urgente", "title": "É urgente"},
	{"id": "ligar", "title": "Prefiro que me liguem"},
	{"id": "factura", "title": "Preciso de factura"},
]

TEXT_NOT_CONFIGURED = "Este serviço ainda não está disponível."
TEXT_NO_CATEGORIES = "Ainda não há categorias configuradas."
TEXT_CREATED = "Pedido *{name}* registado. Obrigado, {full_name}!"
TEXT_INVALID = "Não foi possível registar o pedido: {reason}. Escreve *teste* para recomeçar."


class InvalidRequest(ValueError):
	pass


def start_test_request_flow(wa_id: str, *, phone_number_id: str | None = None) -> str:
	settings = get_settings()
	if not settings.test_request_flow_id:
		frappe.log_error(title="WABA: Test Request Flow ID is not configured")
		reply(wa_id, TEXT_NOT_CONFIGURED, phone_number_id)
		return "not_configured"

	categories = get_categories()
	if not categories:
		reply(wa_id, TEXT_NO_CATEGORIES, phone_number_id)
		return "no_categories"

	# Not required for the test flow; only used to suggest the name.
	customer = find_customer_by_phone(wa_id)
	suggested_name = frappe.db.get_value("Customer", customer, "customer_name") if customer else ""

	return start_flow(
		wa_id,
		flow_type=FLOW_TYPE,
		flow_id=settings.test_request_flow_id,
		screen=FIRST_SCREEN,
		data=initial_data(categories, get_periods(), suggested_name or "", getdate()),
		header="Pedido de teste",
		body="Regista um pedido em três passos.",
		cta="Começar",
		phone_number_id=phone_number_id,
		customer=customer,
	)


def get_categories() -> list[str]:
	return frappe.get_all(
		CATEGORY_DOCTYPE,
		filters={"enabled": 1},
		order_by="category_name asc",
		limit=MAX_OPTIONS,
		pluck="name",
	)


def get_periods() -> list[str]:
	"""The Select options of WABA Test Request.period, so the doctype is the single source."""
	options = frappe.get_meta(REQUEST_DOCTYPE).get_field("period").options or ""
	return [option for option in options.split("\n") if option]


def options(values: list[str]) -> list[dict]:
	return [{"id": value, "title": value[:MAX_TITLE_LENGTH]} for value in values]


def initial_data(categories: list[str], periods: list[str], suggested_name: str, today: date) -> dict:
	"""Data for screen INICIO. Keys must match the screen's declared data schema."""
	return {
		"nome_sugerido": suggested_name,
		"categorias": options(categories),
		"periodos": options(periods),
		"opcoes_extras": EXTRAS,
		"data_minima": today.isoformat(),
	}


def on_reply(session, response: dict, wa_id: str, phone_number_id: str | None) -> str:
	"""Flow reply handler (see flows.REPLY_HANDLERS)."""
	try:
		values = validate_request(response, periods=get_periods(), today=getdate())
	except InvalidRequest as e:
		reply(wa_id, TEXT_INVALID.format(reason=e), phone_number_id)
		return "invalid"

	request = frappe.get_doc(
		{
			"doctype": REQUEST_DOCTYPE,
			**values,
			"wa_id": wa_id,
			"customer": session.customer,
			"flow_session": session.name,
			"response_json": to_json(response),
		}
	).insert(ignore_permissions=True)

	reply(
		wa_id,
		TEXT_CREATED.format(name=request.name, full_name=request.full_name),
		phone_number_id,
		reference_doctype=REQUEST_DOCTYPE,
		reference_name=request.name,
	)
	return "created"


def validate_request(response: dict, *, periods: list[str], today: date) -> dict:
	"""Never trust the Flow payload: every field is checked again here."""
	full_name = clean_text(response.get("nome"), MAX_NAME_LENGTH, single_line=True)
	if not full_name:
		raise InvalidRequest("falta o nome")

	category = response.get("categoria")
	if not isinstance(category, str) or not frappe.db.exists(CATEGORY_DOCTYPE, {"name": category, "enabled": 1}):
		raise InvalidRequest("categoria inválida")

	period = response.get("periodo")
	if period not in periods:
		raise InvalidRequest("período inválido")

	preferred_date = parse_flow_date(response.get("data_preferida"))
	if not preferred_date:
		raise InvalidRequest("data inválida")
	if preferred_date < today:
		raise InvalidRequest("a data já passou")

	return {
		"full_name": full_name,
		"category": category,
		"period": period,
		"preferred_date": preferred_date,
		"extras": ", ".join(parse_extras(response.get("extras"))),
		"notes": clean_text(response.get("notas"), MAX_NOTES_LENGTH),
		"contact_opt_in": int(parse_bool(response.get("aceita_contacto"))),
	}


def clean_text(value, max_length: int, *, single_line: bool = False) -> str:
	if not isinstance(value, str):
		return ""
	text = " ".join(value.split()) if single_line else value.strip()
	return text[:max_length]


def parse_flow_date(value) -> date | None:
	"""DatePicker sends 'YYYY-MM-DD' (Flow JSON 5.0+); older versions sent epoch milliseconds."""
	if not isinstance(value, str | int) or isinstance(value, bool):
		return None
	text = str(value).strip()
	try:
		if text.isdigit():
			return datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc).date()
		return date.fromisoformat(text)
	except (ValueError, OverflowError, OSError):
		return None


def parse_extras(value) -> list[str]:
	"""CheckboxGroup sends a list of ids; keep only known ones, in the offered order."""
	if isinstance(value, str):
		value = [part.strip() for part in value.split(",")]
	if not isinstance(value, list):
		return []
	chosen = {item for item in value if isinstance(item, str)}
	return [extra["id"] for extra in EXTRAS if extra["id"] in chosen]


def parse_bool(value) -> bool:
	if isinstance(value, bool):
		return value
	return isinstance(value, str) and value.strip().lower() in ("true", "1", "yes", "sim")
