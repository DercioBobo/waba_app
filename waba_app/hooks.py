app_name = "waba_app"
app_title = "WABA App"
app_publisher = "Dércio Bobo"
app_description = "WhatsApp Business Cloud API + WhatsApp Flows for Frappe/ERPNext"
app_email = "derciobob@gmail.com"
app_license = "mit"
app_icon = "octicon octicon-comment-discussion"
app_color = "#25d366"

required_apps = ["erpnext"]

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": [
		"waba_app.waba_app.doctype.waba_flow_session.waba_flow_session.expire_stale_sessions",
	],
}
