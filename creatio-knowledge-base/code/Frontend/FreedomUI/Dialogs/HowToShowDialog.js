define("UsrMyPage_FormPage", /**SCHEMA_DEPS*/[]/**SCHEMA_DEPS*/, function/**SCHEMA_ARGS*/()/**SCHEMA_ARGS*/ {
	return {

		viewConfigDiff: /**SCHEMA_VIEW_CONFIG_DIFF*/[
			// Caption: the page resource string "Button_ShowDialog_caption".
			{
				"operation": "insert",
				"name": "Button_ShowDialog",
				"values": {
					"layoutConfig": { "column": 1, "row": 1, "colSpan": 1, "rowSpan": 1 },
					"type": "crt.Button",
					"caption": "#ResourceString(Button_ShowDialog_caption)#",
					"iconPosition": "only-text",
					"clicked": {
						"request": "usr.ShowInfoRequest",
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

		// --- How to show an informational dialog popup -----------------------
		// Use crt.ShowDialogRequest dispatched via executeRequest.
		//
		// dialogConfig.data.message - the text shown in the dialog body.
		// dialogConfig.data.actions - array of buttons; each needs a key and config.
		//   key           - identifier returned when the button is clicked
		//   config.caption - button label
		//   config.color   - "primary" | "default" | "danger"
		// Style: frontend guide 3.2, 3.4, 3.5

		handlers: /**SCHEMA_HANDLERS*/[
			{
				request: "usr.ShowInfoRequest",
				handler: async (request, next) => {
					const name = await request.$context.PDS_Name_someAttr;
					// Texts are page resource strings: RecordNameMessage, OkButtonCaption.
					const message = await request.$context.Resources.Strings.RecordNameMessage;

					await request.$context.executeRequest({
						type: "crt.ShowDialogRequest",
						$context: request.$context,
						dialogConfig: {
							data: {
								message: message + name,
								actions: [
									{
										key: "OK",
										config: {
											color: "primary",
											caption: await request.$context.Resources.Strings.OkButtonCaption
										}
									}
								]
							}
						}
					});

					return next?.handle(request);
				}
			}
		]/**SCHEMA_HANDLERS*/,

		converters: /**SCHEMA_CONVERTERS*/{}/**SCHEMA_CONVERTERS*/,
		validators: /**SCHEMA_VALIDATORS*/{}/**SCHEMA_VALIDATORS*/

	};
});
