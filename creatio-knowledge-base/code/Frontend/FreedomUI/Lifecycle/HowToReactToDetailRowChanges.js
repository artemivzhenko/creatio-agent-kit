define("UsrOrder_FormPage", /**SCHEMA_DEPS*/["@creatio-devkit/common"]/**SCHEMA_DEPS*/, function/**SCHEMA_ARGS*/(sdk)/**SCHEMA_ARGS*/ {
	return {

		viewConfigDiff: /**SCHEMA_VIEW_CONFIG_DIFF*/[]/**SCHEMA_VIEW_CONFIG_DIFF*/,
		viewModelConfigDiff: /**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/[]/**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/,
		modelConfigDiff: /**SCHEMA_MODEL_CONFIG_DIFF*/[]/**SCHEMA_MODEL_CONFIG_DIFF*/,

		// --- How to react to a detail's row changes (three hooks) ---------------
		// A parent value that depends on the rows of a detail (a count, a total) has three moments to be
		// recomputed. Each is a handler; each ends with `return next?.handle(request)`.
		//
		// 1. SAVE. crt.SaveRecordRequest (clio get-request-info crt.SaveRecordRequest; HowToInterceptSave.js).
		//    Before `next` the values set on request.$context are saved with the record: read the rows with
		//    sdk.Model, set the parent's attribute, let the save persist it. PROVED on 8.2.3 (S42-T02): the
		//    order's quantity was set to the number of its link rows, the backend check-record read it back.
		//    crt.SaveDataRequest is the per-data-source request underneath it, and clio's catalogue says the
		//    page save emits it once per data source; on 8.2.3 a handler on it did NOT fire for the Save of an
		//    existing record (two runs, gap line 8). Hook the page save, not the data source.
		//
		// 2. A ROW LEAVES THE COLLECTION. crt.RemoveCollectionItemsRequest. observed in a client page,
		//    no entry in get-request-info: request.collectionAttributeName names the collection the
		//    row was removed from. A handler registered for it loads without error; no UI run removed a row
		//    (the test utility has no row delete on a collection of a form), so the contents of
		//    `request` are not confirmed. After `next` the row is gone: recompute there, then dispatch
		//    your own request through the chain
		//    (sdk.HandlerChainService.instance.process({ type: "usr.RecalculateRequest", $context: request.$context,
		//    scopes: [...request.scopes] })) so the same recalculation serves all three hooks.
		//
		// 3. A ROW IS ACTIVATED. crt.DataGridActivateRowBusinessRulesRequest. PROVED to fire on 8.2.3 (the
		//    page load fires it twice per grid, console log): request.dataGridViewElementName is the grid's
		//    name ("UsrOrdersGrid"). Filter on it, the request fires for every grid of the page. Not in
		//    get-request-info.
		//
		// Await what you wait for: a handler that returns before an async recalculation ends lets the next
		// handler see the old value, `await` the sdk.Model calls inside the handler.
		// Style: frontend guide 3.4, 3.5

		handlers: /**SCHEMA_HANDLERS*/[
			{
				request: "usr.RecalculateRequest",
				handler: async (request, next) => {
					const id = await request.$context.Id;
					const filter = new sdk.FilterGroup();
					await filter.addSchemaColumnFilterWithParameter(sdk.ComparisonType.Equal, "UsrOrder", id);
					const links = await sdk.Model.create("UsrOrderLink");
					const rows = await links.load({
						attributes: ["Id"],
						parameters: [{ type: sdk.ModelParameterType.Filter, value: filter }]
					});
					request.$context.UsrQuantity = rows.length;
					return next?.handle(request);
				}
			},
			{
				request: "crt.SaveRecordRequest",
				handler: async (request, next) => {
					await sdk.HandlerChainService.instance.process({ type: "usr.RecalculateRequest", $context: request.$context, scopes: [...request.scopes] });
					return next?.handle(request);
				}
			},
			{
				request: "crt.RemoveCollectionItemsRequest",
				handler: async (request, next) => {
					const result = await next?.handle(request);
					if (request.collectionAttributeName === "UsrOrdersGrid") {
						await sdk.HandlerChainService.instance.process({ type: "usr.RecalculateRequest", $context: request.$context, scopes: [...request.scopes] });
					}
					return result;
				}
			},
			{
				request: "crt.DataGridActivateRowBusinessRulesRequest",
				handler: async (request, next) => {
					if (request.dataGridViewElementName === "UsrOrdersGrid") {
						// logic that belongs to this grid only goes here, before the chain continues
					}
					return next?.handle(request);
				}
			}
		]/**SCHEMA_HANDLERS*/,

		converters: /**SCHEMA_CONVERTERS*/{}/**SCHEMA_CONVERTERS*/,
		validators: /**SCHEMA_VALIDATORS*/{}/**SCHEMA_VALIDATORS*/

	};
});
