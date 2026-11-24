define("UsrMyPage_FormPage", /**SCHEMA_DEPS*/["@creatio-devkit/common"]/**SCHEMA_DEPS*/, function/**SCHEMA_ARGS*/(sdk)/**SCHEMA_ARGS*/ {
	return {

		viewConfigDiff: /**SCHEMA_VIEW_CONFIG_DIFF*/[
			// Caption: the page resource string "Button_RunProcess_caption".
			{
				"operation": "insert",
				"name": "Button_RunProcess",
				"values": {
					"layoutConfig": { "column": 1, "row": 1, "colSpan": 1, "rowSpan": 1 },
					"type": "crt.Button",
					"caption": "#ResourceString(Button_RunProcess_caption)#",
					"iconPosition": "only-text",
					"clicked": {
						"request": "usr.RunProcessRequest",
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

		// --- How to run a business process from the frontend -----------------
		// Use request.$context.executeRequest with crt.RunBusinessProcessRequest to
		// invoke a server-side business process and read its output parameters.
		// sdk.HandlerChainService.instance.process is for code without a $context.
		//
		// processName            - code of the process in Creatio
		// processParameters      - key-value input parameters for the process
		// resultParameterNames   - list of output parameter names to retrieve
		// processRunType         - not needed in this imperative form: on 8.2.3 the
		//                          request ran without it (success: true, the process
		//                          wrote its row; S40-T05). The declarative button
		//                          ("clicked": {"request": ..., "params": {...}}) sets it,
		//                          e.g. "ForTheSelectedPage".
		// Keys of processParameters are the process PARAMETER CODES; clio says a wrong key is
		// dropped silently.
		//
		// result.success                       - true if the process completed
		// result.resultParameterValues.ParamName - value of an output parameter
		//
		// Requires: @creatio-devkit/common in SCHEMA_DEPS (sdk argument).
		// Style: frontend guide 3.2, 3.4, 3.5

		handlers: /**SCHEMA_HANDLERS*/[
			{
				request: "usr.RunProcessRequest",
				handler: async (request, next) => {
					const field1 = await request.$context.PDS_Field1_someAttr;
					const field2 = await request.$context.PDS_Field2_someAttr;

					const result = await request.$context.executeRequest({
						type: "crt.RunBusinessProcessRequest",
						$context: request.$context,
						processName: "UsrMyProcessCode",
						processParameters: {
							MyField1: field1,
							MyField2: field2
						},
						resultParameterNames: ["MyResultParam", "MySuccessFlag"]
					});

					if (result.success) {
						const output = result.resultParameterValues.MyResultParam;
						request.$context.MyAttribute = output;
					}

					return next?.handle(request);
				}
			}
		]/**SCHEMA_HANDLERS*/,

		converters: /**SCHEMA_CONVERTERS*/{}/**SCHEMA_CONVERTERS*/,
		validators: /**SCHEMA_VALIDATORS*/{}/**SCHEMA_VALIDATORS*/

	};
});
