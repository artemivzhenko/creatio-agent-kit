// --- How to auto-generate a record number (getIncrementCode) -----------------
// Terrasoft.BasePageV2.getIncrementCode is the base method that produces the
// next number from the numbering MASK configured for the entity:
//
//   this.getIncrementCode(function(response) {
//       this.set("UsrNumber", response);
//   }, this);
//
// The callback runs with the view model as `this`, and `response` is the ready
// string. The mask itself is configured outside the schema - in the object
// designer / the "code mask" system setting for the entity - so the page only
// asks for the next value.
//
// WHEN TO CALL IT. Only for a record that does not have a number yet, which
// means inside onEntityInitialized guarded by the card state:
//
//   if (this.isAddMode() || this.isCopyMode()) { ... }
//
// Without the guard an existing record is renumbered every time it is opened.
// isCopyMode() matters: a copy inherits the source number and must get a new
// one.
//
// The number is generated on the CLIENT before the save, so two users creating
// a record at the same moment can receive the same value. When the number must
// be strictly unique, generate it server-side in a business process or an entity
// event listener instead - see Backend/C#/Events/.
// Style: frontend guide 2.4, 2.5

define("UsrMyEntity1Page", [], function() {
	return {
		entitySchemaName: "UsrMyEntity",
		methods: {

			onEntityInitialized: function() {
				this.callParent(arguments);

				// Only for a new record or a copy of an existing one.
				if (this.isAddMode() || this.isCopyMode()) {
					this.getIncrementCode(function(response) {
						this.set("UsrNumber", response);
					}, this);
				}
			},

			// Same call in a flow where the number must exist before an action.
			ensureNumberThen: function(callback, scope) {
				if (this.get("UsrNumber")) {
					Ext.callback(callback, scope || this);
					return;
				}
				this.getIncrementCode(function(response) {
					this.set("UsrNumber", response);
					Ext.callback(callback, scope || this);
				}, this);
			}
		},
		diff: /**SCHEMA_DIFF*/[]/**SCHEMA_DIFF*/
	};
});
