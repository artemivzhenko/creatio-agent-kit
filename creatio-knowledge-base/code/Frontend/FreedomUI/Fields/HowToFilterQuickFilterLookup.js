define("UsrOrder_ListPage", /**SCHEMA_DEPS*/["@creatio-devkit/common"]/**SCHEMA_DEPS*/, function/**SCHEMA_ARGS*/(sdk)/**SCHEMA_ARGS*/ {
	return {

		// --- How to filter the list of a quick filter's lookup by a page value ----
		// A lookup quick filter (crt.QuickFilter, filterType "lookup") shows a chip whose drop-down lists the
		// records of config.entitySchemaName. To narrow that LIST (not the grid) by another value of the page -
		// a country the user typed, a status a button set - there are two routes.
		//
		// 1. STATIC: config.recordsFilter on the chip (clio get-component-info crt.QuickFilter, section 4.3:
		//    "static filter applied to the lookup query"). Fixed at design time, no page value. Not tried here.
		//
		// 2. DYNAMIC, from a handler. PROVED on the test site (8.2.3, S44-T04; platform fact P-8.8): the chip
		//    generates, from its name, an inner combobox and its list:
		//        <Chip>_ComboBox                 the combobox element (element-name in the DOM)
		//        <Chip>_ComboBox_List            the list attribute
		//        <Chip>_ComboBox_List_Filter     the filter attribute of that list   <- set this
		//        <Chip>_ComboBox_List_Sorting    its sorting
		//        <Chip>_ComboBox_List_DS         the data source that loads it       <- reload this
		//        <Chip>_Value, <Chip>_Items      the chosen values / the filter the chip gives the GRID
		//    Set the filter attribute to an sdk.FilterGroup and dispatch crt.LoadDataRequest for the _List_DS:
		//    the open list changed from 5 values to 3 to 1 as the filter did. The request itself carries no
		//    filter (its parameters are null); the filter lives in the attribute.
		//
		//    A second way, observed: a handler on crt.LoadDataRequest for the _List_DS pushing
		//    { type: "filter", value: <copy of the FilterGroup> } into request.parameters (the pattern of
		//    HowToFilterLookupField.js). It filtered the list's own first load. Two traps there: pass a COPY
		//    (Object.assign({}, group) with .items set back), the group itself gave "No data"; and a reload sent
		//    from a handler did not refresh the shown list, so use the filter attribute for a value that changes.
		//
		// THE CHIP FILTERS THE GRID ONLY WHEN REGISTERED (clio, section 2.2): the chip's exposed attribute must be in
		// the collection's modelConfig.filterAttributes, and a `merge` REPLACES that array - list the ones the page
		// already has. Without it the chip renders, takes values and filters nothing, with no error.
		//
		// NAMES: <Chip> is the chip's element `name` (here QuickFilterByContact); the generated names above were read
		// from $context and dataSchemas of the running page (Object.getOwnPropertyNames($context),
		// Object.keys($context.dataSchemas)); read them once on your page before trusting a suffix.
		// NOT TRIED: triggering the filter from crt.HandleViewModelAttributeChangeRequest (the proof used buttons
		// that call the same code); the framework's analyse sees no element on a Freedom UI list page.
		// Style: frontend guide 3.4, 3.5

		viewConfigDiff: /**SCHEMA_VIEW_CONFIG_DIFF*/[
			{
				"operation": "insert",
				"name": "QuickFilterByContact",
				"parentName": "LeftFilterContainerInner",
				"propertyName": "items",
				"index": 1,
				"values": {
					"type": "crt.QuickFilter",
					"filterType": "lookup",
					"config": {
						"caption": "#ResourceString(QuickFilterByContact_config_caption)#",
						"icon": "person-button-icon",
						"iconPosition": "left-icon",
						"entitySchemaName": "Contact"
					},
					"_filterOptions": {
						"expose": [
							{
								"attribute": "QuickFilterByContact_Items",
								"converters": [
									{
										"converter": "crt.QuickFilterAttributeConverter",
										"args": [
											{
												"target": { "viewAttributeName": "Items", "filterColumn": "UsrContact" },
												"quickFilterType": "lookup"
											}
										]
									}
								]
							}
						],
						"from": "QuickFilterByContact_Value"
					}
				}
			}
		]/**SCHEMA_VIEW_CONFIG_DIFF*/,

		viewModelConfigDiff: /**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/[
			{
				"operation": "merge",
				"path": ["attributes"],
				"values": { "ContactNameContains": { "value": "Super" } }
			},
			{
				// the full list of the page's filter attributes plus the chip's
				"operation": "merge",
				"path": ["attributes", "Items", "modelConfig"],
				"values": {
					"filterAttributes": [
						{ "name": "FolderTree_active_folder_filter", "loadOnChange": true },
						{ "name": "Items_PredefinedFilter", "loadOnChange": true },
						{ "name": "SearchFilter_Items", "loadOnChange": true },
						{ "name": "QuickFilterByContact_Items", "loadOnChange": true }
					]
				}
			}
		]/**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/,
		modelConfigDiff: /**SCHEMA_MODEL_CONFIG_DIFF*/[]/**SCHEMA_MODEL_CONFIG_DIFF*/,

		handlers: /**SCHEMA_HANDLERS*/[
			{
				request: "crt.HandleViewModelAttributeChangeRequest",
				handler: async (request, next) => {
					const result = await next?.handle(request);
					if (request.attributeName !== "ContactNameContains") {
						return result;
					}
					const context = request.$context;
					const text = await context.ContactNameContains;

					const filter = new sdk.FilterGroup();
					await filter.addSchemaColumnFilterWithParameter(sdk.ComparisonType.Contain, "Name", text);
					context.QuickFilterByContact_ComboBox_List_Filter = filter;

					await sdk.HandlerChainService.instance.process({
						type: "crt.LoadDataRequest",
						dataSourceName: "QuickFilterByContact_ComboBox_List_DS",
						$context: context,
						scopes: [...request.scopes]
					});
					return result;
				}
			}
		]/**SCHEMA_HANDLERS*/,

		converters: /**SCHEMA_CONVERTERS*/{}/**SCHEMA_CONVERTERS*/,
		validators: /**SCHEMA_VALIDATORS*/{}/**SCHEMA_VALIDATORS*/

	};
});
