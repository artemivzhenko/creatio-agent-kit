define("UsrMyPage_ListPage", /**SCHEMA_DEPS*/[]/**SCHEMA_DEPS*/, function/**SCHEMA_ARGS*/()/**SCHEMA_ARGS*/ {
	return {

		// --- How to style grid rows or cells by a value (custom css) ----------
		// Freedom UI has no per-row style property on crt.DataGrid. The pattern:
		//
		//   1. one <style> element in document.head, injected ONCE (it carries an
		//      id, so a second page instance finds it and adds nothing);
		//   2. a class per value (usr-status-done, usr-status-late);
		//   3. the cells of the column are found by their stable CSS hook
		//      td.cdk-column-<DataSourceName>_<ColumnName> and get the class that
		//      the value maps to.
		//
		// The cell text is the DISPLAY value, so for a lookup column the map is
		// keyed by the caption, not the Id. The grid re-renders rows on paging,
		// sorting and filtering, so a MutationObserver re-applies the classes
		// after each render; it is disconnected when the page is destroyed.
		// To find the hook of a column, open the page in the browser and inspect
		// a cell: the class list holds cdk-column-<DS>_<Column>.
		// Style: frontend guide 3.2, 3.4

		viewConfigDiff: /**SCHEMA_VIEW_CONFIG_DIFF*/[]/**SCHEMA_VIEW_CONFIG_DIFF*/,
		viewModelConfigDiff: /**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/[]/**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/,
		modelConfigDiff: /**SCHEMA_MODEL_CONFIG_DIFF*/[]/**SCHEMA_MODEL_CONFIG_DIFF*/,

		handlers: /**SCHEMA_HANDLERS*/[
			{
				request: "crt.HandleViewModelInitRequest",
				handler: async (request, next) => {
					// The data source and column names of YOUR grid.
					const cellSelector = "td.cdk-column-UsrOrdersDS_UsrStatus";
					// Displayed value -> class.
					const classByValue = {
						"Done": "usr-status-done",
						"Late": "usr-status-late"
					};

					// 1. The style element, once per document.
					const styleId = "usr-grid-row-style";
					if (!document.getElementById(styleId)) {
						const style = document.createElement("style");
						style.id = styleId;
						style.textContent =
							cellSelector + ".usr-status-done { background: #e6f4ea; }" +
							cellSelector + ".usr-status-late { background: #fde8e8; font-weight: 600; }";
						document.head.appendChild(style);
					}

					// 2. The class per value, now and after every render.
					const paint = () => {
						document.querySelectorAll(cellSelector).forEach(cell => {
							const cls = classByValue[(cell.textContent || "").trim()];
							Object.values(classByValue).forEach(c => cell.classList.toggle(c, c === cls));
						});
					};
					paint();
					const observer = new MutationObserver(paint);
					observer.observe(document.body, { childList: true, subtree: true });
					request.$context.UsrGridStyleObserver = observer;

					return next?.handle(request);
				}
			},
			{
				request: "crt.HandleViewModelDestroyRequest",
				handler: async (request, next) => {
					// Stop watching when the page goes away; the <style> stays, it is shared.
					request.$context.UsrGridStyleObserver?.disconnect();
					return next?.handle(request);
				}
			}
		]/**SCHEMA_HANDLERS*/,

		// Traps:
		// - Observing document.body is wide; if the grid has a stable container,
		//   observe that element instead (inspect the page for its tag).
		// - Do not set cell.style in the handler: the grid reuses cell elements,
		//   a leftover inline style lands on the wrong row. Toggle classes only.
		// - Text matching breaks when the caption is localised; key the map by
		//   the caption of the culture the page runs in, or compute the class
		//   from a column that holds a code.

		converters: /**SCHEMA_CONVERTERS*/{}/**SCHEMA_CONVERTERS*/,
		validators: /**SCHEMA_VALIDATORS*/{}/**SCHEMA_VALIDATORS*/

	};
});
