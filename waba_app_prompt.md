# Build `waba_app` — a Frappe/ERPNext app for WhatsApp Cloud API + WhatsApp Flows

## Context

I'm an ERPNext/Frappe developer. I want a custom Frappe app called `waba_app` that connects ERPNext to the WhatsApp Business Cloud API (Meta Graph API) and uses **WhatsApp Flows** for structured interactions.

This first phase is a pilot on a **sandbox site** using Meta's **test WhatsApp Business Account**. Production (a different WABA and number) comes later, so everything account-specific must be configurable, never hardcoded.

The first use case: a customer types a keyword (e.g. "facturas") on WhatsApp, receives a Flow listing their unpaid Sales Invoices, picks one and an action, and the app performs the action (send the invoice PDF or a text summary).

## Before writing code

1.check how other apps of erpnext did the tree of the folders and the paths

## Scope of phase 1

In scope:
- Webhook endpoint (verification + incoming messages + status updates)
- Sending text, interactive Flow messages, and documents (PDF)
- Static Flow (no Flow data endpoint) with data injected at send time
- Logging of every inbound and outbound message
- Flow sessions keyed by `flow_token`

Out of scope for now (design so they can be added later, but don't build them):
- Encrypted Flow data endpoint (`data_exchange`, RSA/AES)
- Template messages / business-initiated conversations
- Payments (M-Pesa/eMola). An action "pagar" may exist but should reply that it's coming soon.

## Doctypes

**WABA Settings** (Single)
- `enabled` (Check)
- `graph_api_version` (Data, default `v25.0`)
- `phone_number_id`, `waba_id` (Data)
- `access_token`, `app_secret` (Password)
- `verify_token` (Data)
- `invoice_flow_id` (Data)
- `flow_mode` (Select: `draft` / `published`) — when `draft`, send `"mode": "draft"` in the flow message parameters
- `invoice_keywords` (Small Text, comma-separated, default `facturas,faturas,invoice`)
- `company` (Link: Company, optional filter)
- `default_country_code` (Data, default `258`)

**WABA Message Log**
- `direction` (Select: Inbound / Outbound)
- `wa_id` (Data), `phone_number_id` (Data)
- `wamid` (Data, unique where present)
- `message_type` (Data: text, interactive, document, status…)
- `status` (Select: Received / Sent / Delivered / Read / Failed)
- `payload` (Code, JSON), `response` (Code, JSON), `error` (Small Text)
- `reference_doctype` (Link: DocType), `reference_name` (Dynamic Link)

**WABA Flow Session**
- `flow_token` (Data, unique, used as name — generate with a random token, e.g. `secrets.token_urlsafe`)
- `wa_id` (Data), `customer` (Link: Customer)
- `flow_id` (Data), `flow_type` (Data, e.g. `invoices`)
- `status` (Select: Sent / Completed / Expired)
- `sent_payload` (Code, JSON), `response_json` (Code, JSON)
- `completed_on` (Datetime)

## Endpoints

`waba_app/api/webhook.py`, a single whitelisted method with `allow_guest=True`, handling both verbs:

- **GET** (Meta verification): if `hub.mode == "subscribe"` and `hub.verify_token` matches settings, return **only** the `hub.challenge` value as **plain text** (return a `werkzeug.wrappers.Response`, not Frappe's JSON wrapper — Meta rejects `{"message": ...}`). Otherwise 403.
- **POST**:
  - Verify `X-Hub-Signature-256` with HMAC-SHA256 over the **raw** request body (`frappe.request.get_data()`) using `app_secret`. Reject with 401 if invalid. Use `hmac.compare_digest`.
  - Log the raw payload, then `frappe.enqueue` the processing and return 200 immediately. Meta needs a fast response.
  - Idempotency: Meta retries webhooks. Skip messages whose `wamid` is already logged.
  - Handle `statuses` (update the matching outbound log) and `messages`.

Webhook URL format:
`https://<site>/api/method/waba_app.api.webhook.receive`

## Services

`waba_app/services/whatsapp.py` — thin Graph API client:
- `send_text(to, body)`
- `send_flow(to, flow_id, flow_token, screen, data, header, body, cta)`
- `upload_media(file_bytes, filename, mime)` → media id (`POST /{phone_number_id}/media`, multipart, `messaging_product=whatsapp`)
- `send_document(to, media_id, filename, caption)`
- Every call logs to WABA Message Log (request, response, wamid, errors). Use timeouts. Never log the access token.

`waba_app/services/handlers.py` — routing:
- Text message matching a keyword in `invoice_keywords` (case-insensitive, trimmed) → `start_invoice_flow(wa_id)`
- `interactive` with `interactive.type == "nfm_reply"` → `handle_flow_reply(wa_id, message)`
- Anything else → short help text: "Escreve *facturas* para ver as tuas facturas pendentes."

`waba_app/services/customers.py`:
- `find_customer_by_phone(wa_id)`: WhatsApp sends numbers like `258841234567` (digits only, with country code). ERPNext contacts may store `+258 84 123 4567`, `841234567`, `00258…`, etc. Normalize to digits, build variants (with and without the country code), search `Contact Phone` (`phone`) and `Contact.mobile_no`, then follow `Dynamic Link` to a Customer. If multiple customers match, pick none and log a warning.

## Invoice flow behaviour

`start_invoice_flow(wa_id)`:
1. Find the customer. If not found, reply: "Não encontrámos uma conta associada a este número."
2. Query Sales Invoices: `docstatus = 1`, `outstanding_amount > 0`, `customer = …`, optional `company` filter, ordered by `due_date`, limit 10.
3. If none: reply "Não tens facturas pendentes."
4. Create a WABA Flow Session, then send the flow with screen `FACTURAS` and data:
   - `saudacao`: "Olá {customer_name}, estas são as tuas facturas pendentes."
   - `facturas`: list of `{ "id": invoice.name, "title": invoice.name, "description": "<currency> <outstanding formatted> · vence <dd/mm/yyyy>" }`

`handle_flow_reply(wa_id, message)`:
1. `response_json` is a **string**. `json.loads` it. It contains `flow_token`.
2. Load the session by `flow_token`; ignore if missing or already Completed.
3. **Never trust the payload.** Re-check that the invoice belongs to the session's customer and is still submitted with outstanding > 0.
4. Actions:
   - `pdf`: render the default print format (`frappe.get_print` + `frappe.utils.pdf.get_pdf`), upload as media, send as document with filename `<invoice>.pdf`.
   - `detalhes`: send a text summary (number, posting date, due date, grand total, outstanding, up to 5 items with qty and amount).
   - `pagar`: reply "Pagamento via WhatsApp disponível brevemente."
5. Mark the session Completed and store `response_json`.
6. Always reply from the same `phone_number_id` that received the message.

## Flow JSON

Create `waba_app/flows/invoice_flow.json` — a **static** flow I'll paste into WhatsApp Manager's Flow Builder:
- `"version": "7.3"`, **no** `routing_model` and **no** `data_api_version` (those are only for endpoint-powered flows).
- One terminal screen `FACTURAS` (`terminal: true`, `success: true`) with:
  - `TextSubheading` showing `${data.saudacao}`
  - A `Form` containing:
    - `RadioButtonsGroup` `factura`, required, `data-source: "${data.facturas}"`
    - `RadioButtonsGroup` `accao`, required, options: `pdf` "Receber PDF", `detalhes` "Ver detalhes", `pagar` "Pagar"
    - `Footer` "Continuar" with `complete` action, payload `{ "factura": "${form.factura}", "accao": "${form.accao}" }`
- Declare `data` with types and `__example__` values so the builder preview works.

Known Flow JSON gotchas (from previous testing — respect them):
- Initial values for fields inside a `Form` go on the Form as `"init-values": {...}`, **not** as `init-value` on the component (the builder rejects it).
- Avoid `TextInput` with `input-type: number` when passing values between screens: the builder types it as number but the device sends a string. Use strings.
- Every dynamic reference must match the declared data schema type exactly.

## Security and robustness

- `allow_guest=True` only on the webhook. Signature check is mandatory when `app_secret` is set.
- Rate-limit or ignore bursts per `wa_id` (simple cache counter is fine).
- Errors in background processing must be logged (`frappe.log_error`) and never leak tracebacks to the customer.
- The 24-hour customer service window applies: free-form messages (including the flow message) only work if the customer wrote first. That's always true in this phase because everything is triggered by an inbound message.

## Testing

- Unit tests (`frappe.tests.utils.FrappeTestCase`) for: phone normalization and matching, signature verification, keyword routing, `nfm_reply` parsing, and ownership checks. Mock all HTTP calls.
- A whitelisted, System Manager–only helper `waba_app.api.dev.send_invoice_flow(phone)` to trigger the flow manually.
- A README with: install steps, how to fill WABA Settings, how to subscribe the test WABA to this webhook with `override_callback_uri`, curl examples for the GET verification and for a sample POST, and how to create the flow in WhatsApp Manager.

## Code style

- Follow Frappe app conventions (`bench new-app` layout, hooks, `modules.txt`).
- Type hints, small functions, no business logic inside the webhook function.

Work incrementally: scaffold → doctypes → webhook → services → handlers → flow JSON → tests → README. Show me what changed after each step.
