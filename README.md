# WABA App

Connects ERPNext to the **WhatsApp Business Cloud API** (Meta Graph API) and uses
**WhatsApp Flows** for structured conversations.

Phase 1 (pilot, sandbox site, Meta test WABA): a customer types `facturas`, receives a
Flow with their unpaid Sales Invoices, picks one and an action, and gets the PDF or a
text summary back.

## Layout

```
waba_app/
├── api/
│   ├── webhook.py        # receive(): Meta verification (GET) + notifications (POST)
│   └── dev.py            # send_invoice_flow(phone): manual trigger, System Manager only
├── services/
│   ├── whatsapp.py       # Graph API client: send_text, send_flow, upload_media, send_document
│   ├── handlers.py       # background job: idempotency, rate limit, routing
│   ├── flows.py          # shared: sessions, start_flow, nfm_reply dispatch by flow type
│   ├── invoice_flow.py   # start_invoice_flow + invoice actions
│   ├── request_flow.py   # multi-screen test flow -> WABA Test Request
│   ├── customers.py      # phone normalisation + Customer lookup
│   ├── logs.py           # WABA Message Log writes and status updates
│   ├── messaging.py      # best-effort text replies
│   └── signature.py      # X-Hub-Signature-256 (HMAC-SHA256)
├── flows/invoice_flow.json   # static Flow to paste into WhatsApp Manager
├── waba_app/doctype/         # WABA Settings, WABA Message Log, WABA Flow Session
└── tests/
```

## Install

```bash
cd ~/frappe-bench
bench get-app https://github.com/<you>/waba_app   # or: bench get-app /path/to/waba_app
bench --site sandbox.local install-app waba_app
bench --site sandbox.local migrate
bench restart
```

Requires ERPNext. Background jobs must be running (`bench worker` / supervisor), because
incoming messages are processed in the `short` queue.

The site must be reachable by Meta over **HTTPS** with a valid certificate. For a local
sandbox use a tunnel (e.g. `cloudflared tunnel --url http://localhost:8000`, and add the
tunnel host to the site with `bench --site sandbox.local add-to-hosts` / `host_name`).

## WABA Settings

In Meta's App Dashboard → **WhatsApp → API Setup** (test number):

| Field | Where to get it |
|---|---|
| Enabled | Tick when ready |
| Graph API Version | `v25.0` (or the version shown in API Setup) |
| Phone Number ID | API Setup → *Phone number ID* of the test number |
| WABA ID | API Setup → *WhatsApp Business Account ID* |
| Access Token | Temporary token from API Setup (24 h) or, better, a System User token with `whatsapp_business_messaging` and `whatsapp_business_management` |
| App Secret | App Dashboard → **App settings → Basic → App secret** |
| Verify Token | Any random string you choose (used only in the GET handshake) |
| Invoice Flow ID | The Flow's ID from WhatsApp Manager (see below) |
| Flow Mode | `draft` until the flow is published, then `published` |
| Invoice Keywords | `facturas,faturas,invoice` |
| Company | Optional — only offer invoices of this company |
| Default Country Code | `258` |

With the test WABA you can only message numbers added to the test number's recipient
list (API Setup → *To*).

Customers are matched by phone through their **Contact** (`Contact Phone` rows and
`mobile_no`), linked to the Customer. Any format works: `+258 84 123 4567`,
`841234567`, `00258…`. A number linked to more than one customer matches none.

## Webhook

URL:

```
https://<site>/api/method/waba_app.api.webhook.receive
```

### Option A — App-level webhook

App Dashboard → **WhatsApp → Configuration → Webhook**: callback URL above, verify token
from WABA Settings, then subscribe to the **messages** field.

### Option B — per-WABA override (`override_callback_uri`)

> **If production already runs on a Meta app, don't use this — create a separate Meta
> app for the sandbox instead.** Running this with the production WABA ID redirects all
> production traffic. Never subscribe the production WABA to the sandbox app either.
> As an extra guard, the app ignores notifications for any `phone_number_id` other than
> the one in WABA Settings.

Only for a WABA that no other system depends on:

```bash
curl -X POST "https://graph.facebook.com/v25.0/<WABA_ID>/subscribed_apps" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
        "override_callback_uri": "https://<site>/api/method/waba_app.api.webhook.receive",
        "verify_token": "<VERIFY_TOKEN>"
      }'

# check
curl "https://graph.facebook.com/v25.0/<WABA_ID>/subscribed_apps" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

Meta calls the GET verification on the new URL before accepting it. The **messages**
field must still be subscribed at app level.

### Test the GET verification

```bash
curl -i "https://<site>/api/method/waba_app.api.webhook.receive?hub.mode=subscribe&hub.verify_token=<VERIFY_TOKEN>&hub.challenge=1158201444"
# HTTP/1.1 200 OK
# 1158201444        <- plain text, not {"message": ...}
```

A wrong token returns `403`.

### Test a POST (signed)

```bash
APP_SECRET='<APP_SECRET>'
BODY='{"object":"whatsapp_business_account","entry":[{"id":"<WABA_ID>","changes":[{"field":"messages","value":{"messaging_product":"whatsapp","metadata":{"display_phone_number":"15551234567","phone_number_id":"<PHONE_NUMBER_ID>"},"contacts":[{"profile":{"name":"Teste"},"wa_id":"258841234567"}],"messages":[{"from":"258841234567","id":"wamid.TEST-0001","timestamp":"1761500000","type":"text","text":{"body":"facturas"}}]}}]}]}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$APP_SECRET" | sed 's/^.* //')

curl -i -X POST "https://<site>/api/method/waba_app.api.webhook.receive" \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=$SIG" \
  --data-raw "$BODY"
# HTTP/1.1 200 OK
```

Sending the same `wamid` again is ignored (Meta retries webhooks). A bad or missing
signature returns `401` whenever App Secret is set. Check **WABA Message Log**: one
`webhook` entry with the raw payload, one inbound `text` entry, and the outbound reply.

## Create the Flow in WhatsApp Manager

1. WhatsApp Manager → **Account tools → Flows → Create Flow**. Pick any category
   (e.g. *Other*), no endpoint.
2. Open the JSON editor, replace its content with
   [`waba_app/flows/invoice_flow.json`](waba_app/flows/invoice_flow.json) and save.
   The preview uses the `__example__` data.
3. Copy the **Flow ID** into WABA Settings → *Invoice Flow ID*.
4. Keep *Flow Mode* = `draft` while testing. After **Publish**, set it to `published`
   (a published flow can no longer be edited — clone it for changes).

The flow is static: the invoice list is injected in the message at send time
(`flow_action: navigate`, screen `FACTURAS`). When the customer taps *Continuar*, Meta
sends an `nfm_reply` whose `response_json` carries `flow_token`, `factura` and `accao`.
The app re-checks that the invoice still belongs to the session's customer and is unpaid
before doing anything.

## Multi-screen test flow

A static, three-screen flow that creates a **WABA Test Request**. It doesn't touch real
ERPNext data.

```
INICIO (nome, categoria) ──navigate──▶ DETALHES (data, período, extras, notas) ──navigate──▶ CONFIRMAR (opt-in) ──complete──▶ nfm_reply
```

- **"GET"**: the categories (from **WABA Test Category**), the periods (the options of
  *WABA Test Request → Period*) and the extras are loaded from ERPNext when the flow is
  sent. Each `navigate` payload passes them, together with the values already entered,
  to the next screen. That is how a static flow shares data between screens.
- **"POST"**: `complete` sends everything back as an `nfm_reply`. The server checks
  every field again (category exists and is enabled, period is valid, date is not in the
  past, extras are known ids, texts are trimmed and limited) before creating the request.
  The customer then receives `Pedido WTR-00001 registado`.

Setup:

1. Create a few categories, or seed them from the browser console:
   `frappe.call("waba_app.api.dev.seed_test_categories")`
2. In WhatsApp Manager, create a new flow, paste
   [`waba_app/flows/test_request_flow.json`](waba_app/flows/test_request_flow.json), and
   copy its ID into **WABA Settings → Test Request Flow ID**.
3. Send **`teste`** from your phone (keywords: *Test Request Keywords*), or
   `frappe.call("waba_app.api.dev.send_test_request_flow", { phone: "84 123 4567" })`.

If the Flow Builder rejects the dynamic `init-values` on the first screen's Form (used to
prefill the name from the matched Customer), delete the `init-values` block. The flow
works without it.

New flow types plug in through `services/flows.py`: call `start_flow(...)` to send, and
register a reply handler in `REPLY_HANDLERS`.

## Manual trigger

From the browser console (logged in as System Manager):

```js
frappe.call("waba_app.api.dev.send_invoice_flow", { phone: "84 123 4567" })
```

or `bench --site sandbox.local execute waba_app.api.dev.send_invoice_flow --kwargs "{'phone': '258841234567'}"`.

Free-form messages (including Flows) only reach a number that wrote to the business in
the last 24 hours, so send any message from the phone first.

## Tests

```bash
bench --site sandbox.local set-config allow_tests true
bench --site sandbox.local run-tests --app waba_app
```

All HTTP calls are mocked.

## Notes

- Background processing runs as `Administrator` (the webhook request itself is Guest),
  which is needed to render invoice print formats.
- Each number is limited to 10 messages per minute; extra messages are logged and
  ignored.
- Replies always go out from the `phone_number_id` that received the message.
- Flow sessions not answered within 24 h are marked *Expired* by a daily job.
- Not built yet: encrypted Flow data endpoint, template messages, payments (`pagar`
  answers "Pagamento via WhatsApp disponível brevemente.").
