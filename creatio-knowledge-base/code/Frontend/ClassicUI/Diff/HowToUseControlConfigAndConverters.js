// --- controlConfig, bindConfig converters, classes and hints -----------------
// `values` in a diff entry has two levels:
//
//   values.<prop>              properties the FRAMEWORK understands
//                              (bindTo, layout, enabled, visible, caption...)
//   values.controlConfig.<prop> properties passed straight to the CONTROL
//                              instance - this is how you reach control-specific
//                              options that have no diff-level equivalent
//
// Useful controlConfig keys seen in production schemas:
//   className          swap the control class entirely, e.g.
//                      "Terrasoft.UsrExtendableLookupEdit"
//                      (see Modules/HowToCreateCustomControl.js)
//   imageConfig        image of a button, bound to Resources.Images.<Name>
//   rightIconClasses   CSS classes for the icon on the right of an edit
//   rightIconClick     method bound to the right-icon click
//   cleariconclick     method bound to the clear ("x") icon - note the all
//                      lowercase spelling, it is not camelCase
//   imageLoaded/images rich-text notes image handling; bind to the base methods
//                      insertImagesToNotes and NotesImagesCollection
//
// Diff-level companions:
//   hasClearIcon: true          show the clear icon on an edit
//   labelConfig: {visible:false} hide the field label (full-width notes)
//   classes: { wrapperClass: ["my-class"] }  attach CSS classes; pair it with a
//                               CSS module (Modules/HowToUseCssAndCustom...)
//   hint: { bindTo: "Resources.Strings.<Name>" }  tooltip on a button
//
// CONVERTERS. Classic UI can transform a bound value inline, which is the
// equivalent of a Freedom UI converter:
//
//   "visible": {
//       "bindTo": "IsRead",
//       "bindConfig": { converter: function(value) { return !value; } }
//   }
//
// The converter runs with the view model as `this`, so it can read other
// columns. Keep it pure and cheap - it is called on every change. Anything
// heavier belongs in a virtual attribute recomputed by a dependency.
// Style: frontend guide 2.1, 2.3

define("UsrMyEntity1Page", ["UsrExtendableLookupEdit"], function() {
	return {
		entitySchemaName: "UsrMyEntity",
		methods: {
			openColumnExplorer: function() {},
			onMarkAsReadClick: function() {}
		},
		diff: /**SCHEMA_DIFF*/[
			{
				// Field rendered by a CUSTOM control, with right and clear icons.
				"operation": "insert",
				"name": "UsrColumnCaption",
				"parentName": "Header",
				"propertyName": "items",
				"values": {
					"layout": { "colSpan": 12, "rowSpan": 1, "column": 0, "row": 0, "layoutName": "Header" },
					"bindTo": "UsrColumnCaption",
					"hasClearIcon": true,
					"controlConfig": {
						"className": "Terrasoft.UsrExtendableLookupEdit",
						"rightIconClasses": ["custom-right-item", "lookup-edit-right-icon"],
						"rightIconClick": { "bindTo": "openColumnExplorer" },
						// Base method of the edit page.
						"cleariconclick": { "bindTo": "clearField" }
					}
				},
				"index": 0
			},
			{
				// Icon-only button with a hint, custom wrapper class, and a
				// converter that inverts the bound boolean.
				"operation": "insert",
				"name": "UsrIsReadButton",
				"parentName": "NotificationItemTopContainer",
				"propertyName": "items",
				"values": {
					"itemType": Terrasoft.ViewItemType.BUTTON,
					"style": Terrasoft.controls.ButtonEnums.style.TRANSPARENT,
					"click": { "bindTo": "onMarkAsReadClick" },
					"controlConfig": {
						"imageConfig": { "bindTo": "Resources.Images.UsrNotReadIcon" }
					},
					"classes": {
						"wrapperClass": ["usr-right-panel-reminding-wrap"]
					},
					"hint": { "bindTo": "Resources.Strings.UsrMarkAsReadHint" },
					// Show the button only while the item is UNREAD.
					"visible": {
						"bindTo": "IsRead",
						"bindConfig": {
							converter: function(value) {
								return !value;
							}
						}
					}
				}
			},
			{
				// Full-width rich text notes with image support.
				"operation": "insert",
				"name": "Notes",
				"parentName": "NotesControlGroup",
				"propertyName": "items",
				"values": {
					"bindTo": "UsrNotes",
					"dataValueType": 1,   // TEXT
					"contentType": 4,     // RICH_TEXT
					"layout": { "column": 0, "row": 0, "colSpan": 24 },
					"labelConfig": { "visible": false },
					"controlConfig": {
						"imageLoaded": { "bindTo": "insertImagesToNotes" },
						"images": { "bindTo": "NotesImagesCollection" }
					}
				},
				"index": 0
			}
		]/**SCHEMA_DIFF*/
	};
});
