define("UsrMyPage_FormPage", /**SCHEMA_DEPS*/[]/**SCHEMA_DEPS*/, function/**SCHEMA_ARGS*/()/**SCHEMA_ARGS*/ {
	return {

		viewConfigDiff: /**SCHEMA_VIEW_CONFIG_DIFF*/[
			// Caption: the page resource string "Button_Notify_caption".
			{
				"operation": "insert",
				"name": "Button_Notify",
				"values": {
					"layoutConfig": { "column": 1, "row": 1, "colSpan": 1, "rowSpan": 1 },
					"type": "crt.Button",
					"caption": "#ResourceString(Button_Notify_caption)#",
					"iconPosition": "only-text",
					"clicked": {
						"request": "usr.ShowToastRequest",
						"params": {}
					}
				},
				"parentName": "SideAreaProfileContainer",
				"propertyName": "items",
				"index": 0
			}
		]/**SCHEMA_VIEW_CONFIG_DIFF*/,

		viewModelConfigDiff: /**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/[]/**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/,
		modelConfigDiff: /**SCHEMA_MODEL_CONFIG_DIFF*/[]/**SCHEMA_MODEL_CONFIG_DIFF*/,

		// --- How to show a toast (non-blocking) notification -----------------
		// Use crt.NotificationRequest for lightweight messages that disappear
		// automatically, unlike crt.ShowDialogRequest which requires user action.
		//
		// message  - text to display
		// duration - milliseconds before auto-dismiss (default ~3000)
		//
		// Available since Creatio 8.0.10.
		// No SDK dependency required - dispatched via executeRequest like any other request.
		// Style: frontend guide 3.2, 3.4, 3.5

		handlers: /**SCHEMA_HANDLERS*/[
			{
				request: "usr.ShowToastRequest",
				handler: async (request, next) => {
					const name = await request.$context.PDS_Name_someAttr;
					// The text is the page resource string RecordSavedMessage.
					const message = await request.$context.Resources.Strings.RecordSavedMessage;

					await request.$context.executeRequest({
						type: "crt.NotificationRequest",
						$context: request.$context,
						message: message + name
					});

					return next?.handle(request);
				}
			}
		]/**SCHEMA_HANDLERS*/,

		converters: /**SCHEMA_CONVERTERS*/{}/**SCHEMA_CONVERTERS*/,
		validators: /**SCHEMA_VALIDATORS*/{}/**SCHEMA_VALIDATORS*/

	};
});
