define("UsrOrder_ListPage", /**SCHEMA_DEPS*/[]/**SCHEMA_DEPS*/, function/**SCHEMA_ARGS*/()/**SCHEMA_ARGS*/ {
	return {

		// --- Reference: four stock requests wired to custom buttons -------------
		// A stock request can be the `clicked` of a button you insert yourself; the platform handler
		// does the work. These four are used on client pages and are NOT in clio's request catalogue
		// (get-request-info lists 14 requests, none of these; checked 2026-11-24 with the test site's name), so every parameter below is OBSERVED, not published, and none ran on the test site:
		// treat the first use on a page as a probe, with validate-page and the browser console.
		//
		//   crt.MergeRecordsRequest
		//       dataSourceName   the grid's data source ("PDS" of a list page)
		//       selectionState   "$<GridName>_SelectionState" - the rows to merge (the attribute the
		//                        grid keeps, see StockConvertersReference.js)
		//       Opens the merge-records dialog for the selected rows of one entity.
		//   crt.CreateEmailRequest
		//       Opens the new-email window; parameters were not read (none in the survey notes).
		//   crt.AddCommunicationOptionsRequest
		//       Opens the dialog that adds a communication option (phone, email) to the record;
		//       parameters were not read.
		//   crt.SaveAttributeToProfileRequest
		//       profileAttributeName   the attribute whose value is remembered per user
		//       Saves a page attribute to the user's profile, so a grid setting (a toggle, a view mode)
		//       comes back at the next visit.
		//
		// RULES THAT HOLD FOR ALL FOUR: the button's `clicked` is { "request": "<type>", "params": {...} };
		// a request the page or the platform has no handler for does nothing and says nothing
		// (frontend guide section 10: check types in get-request-info / get-component-info first);
		// a button that needs the selection is disabled by a converter of the selection state (StockConvertersReference.js), not by a handler.
		// Style: frontend guide 3.2, 3.4

		viewConfigDiff: /**SCHEMA_VIEW_CONFIG_DIFF*/[
			{
				"operation": "insert",
				"name": "Button_MergeSelected",
				"values": {
					"type": "crt.Button",
					"caption": "#ResourceString(Button_MergeSelected_caption)#",
					"iconPosition": "only-text",
					"clicked": {
						"request": "crt.MergeRecordsRequest",
						"params": {
							"dataSourceName": "PDS",
							"selectionState": "$DataTable_SelectionState"
						}
					}
				},
				"parentName": "ActionButtonsContainer",
				"propertyName": "items",
				"index": 0
			},
			{
				"operation": "insert",
				"name": "Button_NewEmail",
				"values": {
					"type": "crt.Button",
					"caption": "#ResourceString(Button_NewEmail_caption)#",
					"iconPosition": "only-text",
					"clicked": { "request": "crt.CreateEmailRequest", "params": {} }
				},
				"parentName": "ActionButtonsContainer",
				"propertyName": "items",
				"index": 1
			},
			{
				"operation": "insert",
				"name": "Button_AddCommunication",
				"values": {
					"type": "crt.Button",
					"caption": "#ResourceString(Button_AddCommunication_caption)#",
					"iconPosition": "only-text",
					"clicked": { "request": "crt.AddCommunicationOptionsRequest", "params": {} }
				},
				"parentName": "ActionButtonsContainer",
				"propertyName": "items",
				"index": 2
			},
			{
				"operation": "insert",
				"name": "Button_RememberView",
				"values": {
					"type": "crt.Button",
					"caption": "#ResourceString(Button_RememberView_caption)#",
					"iconPosition": "only-text",
					"clicked": {
						"request": "crt.SaveAttributeToProfileRequest",
						"params": { "profileAttributeName": "UsrViewMode" }
					}
				},
				"parentName": "ActionButtonsContainer",
				"propertyName": "items",
				"index": 3
			}
		]/**SCHEMA_VIEW_CONFIG_DIFF*/,
		viewModelConfigDiff: /**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/[]/**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/,
		modelConfigDiff: /**SCHEMA_MODEL_CONFIG_DIFF*/[]/**SCHEMA_MODEL_CONFIG_DIFF*/,

		handlers: /**SCHEMA_HANDLERS*/[]/**SCHEMA_HANDLERS*/,
		converters: /**SCHEMA_CONVERTERS*/{}/**SCHEMA_CONVERTERS*/,
		validators: /**SCHEMA_VALIDATORS*/{}/**SCHEMA_VALIDATORS*/

	};
});
