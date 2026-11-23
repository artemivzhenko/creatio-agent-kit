// --- How to send several queries in one request (BatchQuery) -----------------
// Terrasoft.BatchQuery packs Insert / Update / Delete / ESQ queries into a
// single round trip. Use it whenever you would otherwise fire N queries in a
// loop: it is faster and the whole batch reports one success flag.
//
//   const bq =Ext.create("Terrasoft.BatchQuery");
//   bq.add(query1);
//   bq.add(query2);
//   bq.execute(function(response) { ... }, this);
//
// response.success       - false if the batch failed
// response.errorInfo     - error details
// response.queryResults  - array of per-query results, in the order added; for
//                          an ESQ inside the batch read
//                          response.queryResults[i].rows
//
// A batch is NOT a transaction: a partial failure can leave some rows written.
// If atomicity matters, do the work in a business process or a server service.
//
// Pair batches with the body mask so the user sees that something is running -
// see Dialogs/HowToShowBodyMask.js.
// Style: frontend guide 1.1, 2.5, 2.6, 8

define("UsrMyEntity1Page", [], function() {
	return {
		entitySchemaName: "UsrMyEntity",
		methods: {

			// Update many rows in one request.
			applyServiceChanges: function(changes) {
				if (!changes.length) {
					return;
				}
				this.showBodyMask();

				const bq = Ext.create("Terrasoft.BatchQuery");

				changes.forEach((change) => {
					const update = Ext.create("Terrasoft.UpdateQuery", {
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
						return;
					}
					this.sandbox.publish("FactoriesReload", null, ["order-factories"]);
				}, this);
			},

			// Replace a set of links: delete the old ones and insert the new ones
			// in a single batch.
			replaceAccountLinks: function(accountIds) {
				const orderId = this.get("Id");
				const bq = Ext.create("Terrasoft.BatchQuery");

				const deleteQuery = Ext.create("Terrasoft.DeleteQuery", {
					rootSchemaName: "UsrAccountInMyEntity"
				});
				deleteQuery.filters.add("OrderFilter", Terrasoft.createColumnFilterWithParameter(
					Terrasoft.ComparisonType.EQUAL, "UsrMyEntity", orderId));
				bq.add(deleteQuery);

				accountIds.forEach((accountId) => {
					const insertQuery = Ext.create("Terrasoft.InsertQuery", {
						rootSchemaName: "UsrAccountInMyEntity"
					});
					insertQuery.setParameterValue("UsrAccount", accountId, Terrasoft.DataValueType.GUID);
					insertQuery.setParameterValue("UsrMyEntity", orderId, Terrasoft.DataValueType.GUID);
					bq.add(insertQuery);
				});

				bq.execute(function(result) {
					if (!result.success) {
						this.showInformationDialog(result.errorInfo.message);
					}
				}, this);
			}
		},
		diff: /**SCHEMA_DIFF*/[]/**SCHEMA_DIFF*/
	};
});
