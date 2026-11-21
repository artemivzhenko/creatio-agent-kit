define("UsrMyEntity_FormPage", /**SCHEMA_DEPS*/["@creatio-devkit/common"]/**SCHEMA_DEPS*/, function/**SCHEMA_ARGS*/(sdk)/**SCHEMA_ARGS*/ {
	return {

		viewConfigDiff: /**SCHEMA_VIEW_CONFIG_DIFF*/[]/**SCHEMA_VIEW_CONFIG_DIFF*/,
		viewModelConfigDiff: /**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/[]/**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/,
		modelConfigDiff: /**SCHEMA_MODEL_CONFIG_DIFF*/[]/**SCHEMA_MODEL_CONFIG_DIFF*/,

		// --- How to load records from an entity using sdk.Model --------------
		// Use sdk.Model when you need to query any entity with custom filters
		// from inside a handler, without declaring a DataSource in modelConfigDiff.
		//
		// sdk.Model.create("SchemaName") - initializes access to the entity.
		// sdk.FilterGroup              - builds one or more filter conditions.
		// addSchemaColumnFilterWithParameter(type, column, value) - adds a filter.
		// load({ attributes, parameters }) - executes the query and returns records.
		//
		// Requires: @creatio-devkit/common in SCHEMA_DEPS (sdk argument).
		//
		// Traps:
		// - TRAP (8.x, seen on an environment): sdk.Model.load({ primaryColumnValue: id }) does NOT filter and returns
		//   every row ("primaryColumnValue returns all rows"). To read one record by Id, load through a FilterGroup:
		//   addSchemaColumnFilterWithParameter(sdk.ComparisonType.Equal, "Id", id), as above.
		// - VERIFIED (8.3, headless browser): the same Model.create("<Entity>") + model.load({ attributes: ["Id", "UsrCol"] })
		//   works from inside an Angular element of a remote module on a list page (see Frontend/RemoteModule) and returns the
		//   rows as plain objects keyed by attribute name. Only text columns and the call without a filter were exercised.
		// - GAP (@creatio-devkit/common 0.822): DataSourceLoadOptions, DataSourceSortingConfig, DataSourceParameters and
		//   ComparisonType are re-exported from @creatio/base as private types, and @creatio/base is not shipped with the devkit,
		//   so the shape of a sortingConfig / pagingConfig for model.load is not in the typings and no call with them is
		//   verified here; test one on a page before relying on it.
		// Style: frontend guide 3.4, 3.5

		handlers: /**SCHEMA_HANDLERS*/[
			{
				request: "crt.HandleViewModelInitRequest",
				handler: async (request, next) => {
					const result = await next?.handle(request);

					const typeId  = await request.$context.PDS_Type_someAttr;
					const thisId  = await request.$context.PDS_Id_someAttr;

					// Initialize model for the target entity
					const model = await sdk.Model.create("Contact");

					// Build a filter group
					const filters = new sdk.FilterGroup();
					await filters.addSchemaColumnFilterWithParameter(
						sdk.ComparisonType.Equal,
						"Type",
						typeId
					);

					// Load records - specify only the columns you need
					const records = await model.load({
						attributes: ["Id", "Name"],
						parameters: [{
							type: sdk.ModelParameterType.Filter,
							value: filters
						}]
					});

					request.$context.OtherContactNames = records
						.filter(item => item.Id !== thisId)
						.map(item => item.Name)
						.join(", ");

					return result;
				}
			}
		]/**SCHEMA_HANDLERS*/,

		converters: /**SCHEMA_CONVERTERS*/{}/**SCHEMA_CONVERTERS*/,
		validators: /**SCHEMA_VALIDATORS*/{}/**SCHEMA_VALIDATORS*/

	};
});
