// --- How to block the UI while an async operation runs (body mask) -----------
// The view model draws the "loading" overlay over the whole page:
//
//   this.showBodyMask();
//   this.hideBodyMask();
//
// Terrasoft.MaskHelper.showBodyMask runs underneath; the PascalCase
// Terrasoft.MaskHelper.ShowBodyMask / HideBodyMask still works but is deprecated.
//
// Rules that matter:
//   1. Every showBodyMask must have a hideBodyMask on EVERY exit path - the
//      success branch, the error branch, and the early return. A leaked mask
//      locks the page and the user has to reload.
//   2. Hide the mask BEFORE showing a dialog, otherwise the dialog is rendered
//      behind a greyed-out page.
//   3. Nested masks do not stack: a second Show is a no-op and the first Hide
//      removes the overlay. Do not rely on pairing across nested async calls;
//      keep one mask per user-visible operation.
//
// Use it for: batch writes, business process starts the user waits for, service
// calls, multi-step validation chains. Do not use it for a fast ESQ that only
// refreshes a hidden flag.
// Style: frontend guide 2.5, 2.6, 8

define("UsrMyEntity1Page", [], function() {
	return {
		entitySchemaName: "UsrMyEntity",
		methods: {

			loadServicesAndShowWindow: function() {
				this.showBodyMask();

				const esq = Ext.create("Terrasoft.EntitySchemaQuery", {
					rootSchemaName: "UsrMyDetailEntity"
				});
				esq.addColumn("Id");
				esq.addColumn("UsrService.Name", "ServiceName");
				esq.filters.addItem(esq.createColumnFilterWithParameter(
					Terrasoft.ComparisonType.EQUAL, "UsrMyEntity", this.get("Id")));

				esq.getEntityCollection(function(result) {
					// Hide first, so any dialog below is visible.
					this.hideBodyMask();

					if (!result.success) {
						this.showConfirmationDialog(result.errorInfo.message, function() {}, ["Ok"]);
						return;
					}
					const items = result.collection.getItems();
					if (!items.length) {
						this.showInformationDialog(this.get("Resources.Strings.NoDataFoundMessage"));
						return;
					}
					this.renderServicesWindow(items);
				}, this);
			},

			// Batch write with the mask released on both branches.
			saveChanges: function(changes) {
				if (!changes.length) {
					// Early return: nothing was shown, nothing to hide.
					return;
				}
				this.showBodyMask();

				const bq = Ext.create("Terrasoft.BatchQuery");
				changes.forEach((change) => {
					const update =Ext.create("Terrasoft.UpdateQuery", {
						rootSchemaName: "UsrMyDetailEntity"
					});
					update.setParameterValue(change.field, change.value, change.type);
					update.filters.add("IdFilter", Terrasoft.createColumnFilterWithParameter(
						Terrasoft.ComparisonType.EQUAL, "Id", change.id));
					bq.add(update);
				});

				bq.execute(function(result) {
					this.hideBodyMask();
					if (!result.success) {
						this.showConfirmationDialog(result.errorInfo.message, function() {}, ["Ok"]);
					}
				}, this);
			},

			renderServicesWindow: function(items) {}
		},
		diff: /**SCHEMA_DIFF*/[]/**SCHEMA_DIFF*/
	};
});
