// --- How to let the user pick an entity COLUMN (structure explorer) ----------
// When a record must store the NAME of a column rather than a value (log
// settings, dynamic filters, column mapping tables), open the structure
// explorer instead of writing your own picker:
//
//   this.Terrasoft.StructureExplorerUtilities.open({
//       moduleName:   "StructureExploreModuleV2",
//       moduleConfig: {
//           schemaName:   "Case",   // the entity whose columns are browsed
//           useBackwards: true,     // allow reverse (one-to-many) references
//           displayId:    true      // show Id columns in the tree
//       },
//       handlerMethod: this.onColumnSelected,   // called with the picked item
//       scope:         this
//   });
//
// Add "StructureExplorerUtilities" to the schema dependencies.
//
// THE SELECTED ITEM carries:
//   item.columnPath                 dotted path to the column
//   item.leftExpressionColumnPath   same path, older property name - read both
//   item.leftExpressionCaption      localized caption of the column
//   item.dataValueType              numeric Terrasoft.DataValueType
//
// LOOKUP COLUMNS need the "Id" suffix. A picked lookup returns the path of the
// reference itself; to store something a query can use you append "Id":
//
//   isLookup = dataValueType === Terrasoft.DataValueType.LOOKUP ||
//              dataValueType === Terrasoft.DataValueType.IMAGELOOKUP
//   columnName = isLookup ? columnPath + "Id" : columnPath
//
// Reopening the explorer after a rejected pick (duplicate, wrong type) is the
// friendly behaviour: the user stays in the flow instead of clicking the button
// again.
// Style: frontend guide 1.1, 2.4, 2.5

define("UsrColumnSettingPageV2", ["StructureExplorerUtilities"], function() {
	return {
		entitySchemaName: "UsrColumnSetting",
		methods: {

			// Bound from the right icon of the field - see
			// Diff/HowToUseControlConfigAndConverters.js
			openColumnExplorer: function() {
				const schemaName = "Case";
				if (Ext.isEmpty(schemaName)) {
					return;
				}
				this.Terrasoft.StructureExplorerUtilities.open({
					moduleName: "StructureExploreModuleV2",
					moduleConfig: {
						schemaName: schemaName,
						useBackwards: true,
						displayId: true
					},
					handlerMethod: this.onColumnSelected,
					scope: this
				});
			},

			onColumnSelected: function(item) {
				if (!item || !Ext.isObject(item)) {
					return;
				}
				const dataValueType = item.dataValueType;
				const isLookup = dataValueType === Terrasoft.DataValueType.LOOKUP ||
					dataValueType === Terrasoft.DataValueType.IMAGELOOKUP;

				// Both property names appear depending on the Creatio version.
				const columnPath = item.columnPath || item.leftExpressionColumnPath;
				const columnName = isLookup ? columnPath + "Id" : columnPath;
				const columnCaption = item.leftExpressionCaption || columnName;

				this.set("UsrColumnName", columnName);
				this.set("UsrColumnCaption", columnCaption);
			},

			// Reject duplicates and send the user straight back to the explorer.
			onColumnSelectedWithDuplicateCheck: function(item) {
				const columnName = item.columnPath || item.leftExpressionColumnPath;
				const columnCaption = item.leftExpressionCaption || columnName;

				this.findExistingColumn(columnName, function(isExists) {
					if (isExists) {
						this.showInformationDialog(
							this.get("Resources.Strings.UsrColumnAlreadyAddedCaption") +
							" " + columnCaption);
						this.openColumnExplorer();
						return;
					}
					this.set("UsrColumnName", columnName);
					this.set("UsrColumnCaption", columnCaption);
				}, this);
			},

			findExistingColumn: function(columnName, callback, scope) {
				const esq = Ext.create("Terrasoft.EntitySchemaQuery", {
					rootSchemaName: "UsrColumnSetting"
				});
				esq.addColumn("Id");
				esq.filters.add("byColumnName", Terrasoft.createColumnFilterWithParameter(
					Terrasoft.ComparisonType.EQUAL, "UsrColumnName", columnName));
				esq.getEntityCollection(function(result) {
					if (!result.success) {
						Ext.callback(callback, scope || this, [false]);
						return;
					}
					Ext.callback(callback, scope || this, [result.collection.getCount() > 0]);
				}, this);
			},

			// Turning a numeric dataValueType back into its name. `_` (lodash)
			// is available globally in Classic UI.
			getTypeNameByNumber: function(number) {
				const key = _.findKey(Terrasoft.DataValueType, (value) => value === number);
				return key ? key : "";
			}
		},
		diff: /**SCHEMA_DIFF*/[]/**SCHEMA_DIFF*/
	};
});
