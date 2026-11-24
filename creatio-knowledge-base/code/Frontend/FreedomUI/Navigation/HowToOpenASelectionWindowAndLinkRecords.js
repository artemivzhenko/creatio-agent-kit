define("UsrOrder_FormPage", /**SCHEMA_DEPS*/["@creatio-devkit/common"]/**SCHEMA_DEPS*/, function/**SCHEMA_ARGS*/(sdk)/**SCHEMA_ARGS*/ {
	return {

		// --- How to open a selection window and link the records the user picks ----
		// crt.OpenSelectionWindowRequest is the current record picker. It replaces the
		// deprecated crt.OpenLookupPageRequest (HowToOpenLookupPageAndCreateLinks.js still shows
		// that one: its afterClosed gets the raw items and is skipped on cancel).
		// Contract: clio get-request-info crt.OpenSelectionWindowRequest.
		//
		//   entitySchemaName  the object the user PICKS FROM (Contact), never the link object
		//   caption           window title (a string; the platform derives one when omitted)
		//   features          { create: { enabled }, select: { multiple, selectAll } }
		//                     multiple is off unless true
		//   filtersConfig     { filterAttributes: [{ name, loadOnChange }],
		//                       attributesConfig: { <name>: { value: <sdk.FilterGroup> } } }
		//   selectionState    optional pre-check { type: "specific", selected: [ids] }
		//   afterClosed       ALWAYS called, with a result: result.canceled, then
		//                     await result.getLookupValues() -> [{ value, displayValue }]
		//
		// It is dispatched from a handler, not bound to `clicked`: the callback has no place in a
		// binding's params. Without `scopes: [...request.scopes]` the page's own handlers are skipped.
		//
		// HIDING WHAT IS ALREADY LINKED. sdk.FilterGroup has addNotExistsFilter(path, subFilter)
		// (seen on 8.2.3: the method list of FilterGroup.prototype also holds addExistsFilter,
		// addSchemaColumnInFilterWithParameters, addPrimarySchemaColumnInFilter, addSchemaColumnIsNullFilter,
		// addSchemaColumnIsNotNullFilter, addSchemaColumnBetweenFilterWithParameters). The path walks the
		// backward reference "[<LinkObject>:<column of the link that points at the picked object>].Id",
		// the subfilter keeps the links of THIS master: the window then lists the contacts that
		// have no link to the order. observed, not in the clio catalogue; proved on 8.2.3 (S42-T02):
		// a contact that was linked was missing from the window, the others were listed.
		//
		// WRITING THE LINKS is the handler's job: sdk.Model.create("<LinkObject>") and insert one
		// row per pick; nothing refreshes a detail, dispatch crt.LoadDataRequest for its data source.
		// Read the master id BEFORE the window opens (request.$context.Id) and close over it.
		// PROVED (S44-T08, 8.2.3): the Select click. A case ticked a row of the window, pressed Select, the handler's
		// insert loop wrote the link row (counted over OData) and the page's save recalculated from it. The picks reach
		// afterClosed as result.getLookupValues(); a window closed with nothing ticked gives canceled=false and an empty list,
		// so check the length before inserting.
		// Style: frontend guide 3.4, 3.5

		viewConfigDiff: /**SCHEMA_VIEW_CONFIG_DIFF*/[
			{
				"operation": "insert",
				"name": "Button_AddLinks",
				"values": {
					"type": "crt.Button",
					"caption": "#ResourceString(Button_AddLinks_caption)#",
					"iconPosition": "only-text",
					"color": "default",
					"clicked": { "request": "usr.AddLinksRequest" }
				},
				"parentName": "SideAreaProfileContainer",
				"propertyName": "items",
				"index": 8
			}
		]/**SCHEMA_VIEW_CONFIG_DIFF*/,
		viewModelConfigDiff: /**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/[]/**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/,
		modelConfigDiff: /**SCHEMA_MODEL_CONFIG_DIFF*/[]/**SCHEMA_MODEL_CONFIG_DIFF*/,

		handlers: /**SCHEMA_HANDLERS*/[
			{
				request: "usr.AddLinksRequest",
				handler: async (request, next) => {
					const masterId = await request.$context.Id;
					if (!masterId) {
						return next?.handle(request);
					}

					// Links of this master: the subfilter of the not-exists filter.
					const linksOfMaster = new sdk.FilterGroup();
					await linksOfMaster.addSchemaColumnFilterWithParameter(
						sdk.ComparisonType.Equal, "UsrOrder", masterId);
					const notLinked = new sdk.FilterGroup();
					await notLinked.addNotExistsFilter("[UsrOrderLink:UsrLinkedContact].Id", linksOfMaster);

					await sdk.HandlerChainService.instance.process({
						type: "crt.OpenSelectionWindowRequest",
						entitySchemaName: "Contact",
						caption: "Select contacts",
						features: {
							create: { enabled: false },
							select: { multiple: true, selectAll: false }
						},
						filtersConfig: {
							filterAttributes: [{ name: "NotLinked", loadOnChange: false }],
							attributesConfig: { NotLinked: { value: notLinked } }
						},
						afterClosed: async (result) => {
							if (result.canceled) {
								return;
							}
							const picked = await result.getLookupValues();
							const links = await sdk.Model.create("UsrOrderLink");
							for (const item of picked) {
								await links.insert({ UsrOrder: masterId, UsrLinkedContact: item.value });
							}
							await sdk.HandlerChainService.instance.process({
								type: "crt.LoadDataRequest",
								dataSourceName: "LinksGridDS",
								$context: request.$context,
								scopes: [...request.scopes]
							});
						},
						$context: request.$context,
						scopes: [...request.scopes]
					});

					return next?.handle(request);
				}
			}
		]/**SCHEMA_HANDLERS*/,

		converters: /**SCHEMA_CONVERTERS*/{}/**SCHEMA_CONVERTERS*/,
		validators: /**SCHEMA_VALIDATORS*/{}/**SCHEMA_VALIDATORS*/

	};
});
