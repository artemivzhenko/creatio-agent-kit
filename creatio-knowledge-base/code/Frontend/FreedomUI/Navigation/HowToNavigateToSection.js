define("UsrMyPage_FormPage", /**SCHEMA_DEPS*/[]/**SCHEMA_DEPS*/, function/**SCHEMA_ARGS*/()/**SCHEMA_ARGS*/ {
	return {

		viewConfigDiff: /**SCHEMA_VIEW_CONFIG_DIFF*/[
			// Caption: the page resource string "Button_OpenSection_caption".
			{
				"operation": "insert",
				"name": "Button_OpenSection",
				"values": {
					"layoutConfig": { "column": 1, "row": 1, "colSpan": 1, "rowSpan": 1 },
					"type": "crt.Button",
					"caption": "#ResourceString(Button_OpenSection_caption)#",
					"iconPosition": "only-text",
					"clicked": {
						"request": "usr.OpenSectionRequest",
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

		// --- How to navigate to another section or page ----------------------
		// Run crt.OpenPageRequest through request.$context.executeRequest with
		// the list page schema of the section; it opens in the current tab.
		//
		// schemaName - the section's list page, e.g. "UsrMyEntity_ListPage"
		//
		// From a link (no handler), the Shell hash does the same: #Section/<ListPage>.
		// Not Terrasoft.workspaceBaseUrl + window.open.
		// Style: frontend guide 3.2, 3.4, 3.5

		handlers: /**SCHEMA_HANDLERS*/[
			{
				request: "usr.OpenSectionRequest",
				handler: async (request, next) => {
					await request.$context.executeRequest({
						type: "crt.OpenPageRequest",
						$context: request.$context,
						schemaName: "UsrMyEntity_ListPage"
					});

					return next?.handle(request);
				}
			}
		]/**SCHEMA_HANDLERS*/,

		converters: /**SCHEMA_CONVERTERS*/{}/**SCHEMA_CONVERTERS*/,
		validators: /**SCHEMA_VALIDATORS*/{}/**SCHEMA_VALIDATORS*/

	};
});
