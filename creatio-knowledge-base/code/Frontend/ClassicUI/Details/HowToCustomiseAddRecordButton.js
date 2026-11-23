// --- How to control the "add record" button of a detail ----------------------
// The stock button is named "AddRecordButton". Merge it in the detail diff and
// bind visible / enabled to virtual attributes, then override addRecord() to
// gate the action itself.
//
// Why both? The bindings grey the button out, but a disabled button gives the
// user no reason. Overriding addRecord lets you explain why the action is
// blocked, and it also covers the keyboard / API paths that bypass the button.
//
// addRecord() is the base method that creates a new detail record. If you
// override it you MUST call this.callParent(arguments) on every path that
// should proceed, otherwise adding rows stops working.
//
// A detail lives in its own sandbox module, so it cannot read the page columns
// directly. To decide whether adding is allowed it asks the page over the
// sandbox - see Messaging/HowToCommunicateDetailWithPage.js.
// Style: frontend guide 2.1, 2.3, 2.4, 2.6, 2.7

define("UsrMyDetail", [], function() {
	return {
		entitySchemaName: "UsrMyDetailEntity",

		messages: {
			/**
			 * @message GetColumnsValues
			 * Detail -> page request for column values.
			 */
			"GetColumnsValues": {
				mode: Terrasoft.MessageMode.PTP,
				direction: Terrasoft.MessageDirectionType.PUBLISH
			},
			/**
			 * @message SetDetailButtonState
			 * Page -> detail push of the button state.
			 */
			"SetDetailButtonState": {
				mode: Terrasoft.MessageMode.PTP,
				direction: Terrasoft.MessageDirectionType.SUBSCRIBE
			}
		},

		attributes: {
			"IsAddButtonVisible": {
				dataValueType: Terrasoft.DataValueType.BOOLEAN, value: true
			},
			"IsAddButtonEnabled": {
				dataValueType: Terrasoft.DataValueType.BOOLEAN, value: true
			},
			"ButtonBlockMessage": {
				dataValueType: Terrasoft.DataValueType.TEXT, value: ""
			}
		},

		methods: {

			init: function() {
				this.callParent(arguments);

				// The detail is created before the page finishes wiring its own
				// subscriptions; a short defer avoids a race on first render.
				setTimeout(() => {
					try {
						this.sandbox.subscribe("SetDetailButtonState", this.onSetButtonState, this);
						this.checkButtonStateOnInit();
					} catch (e) {
						this.error("UsrMyDetail: init failed: " + e);
					}
				}, 50);
			},

			// Page pushes { enabled, message } to the detail.
			onSetButtonState: function(state) {
				this.set("IsAddButtonEnabled", !!state.enabled);
				this.set("ButtonBlockMessage", state.message || "");
			},

			checkButtonStateOnInit: function() {
				const parentData = this.sandbox.publish(
					"GetColumnsValues", ["UsrService", "UsrMyEntity"], [this.sandbox.id]);
				if (!parentData) {
					return;
				}
				this.set("IsAddButtonEnabled", !!parentData.UsrService);
			},

			// Gate the action and explain the refusal.
			addRecord: function() {
				if (!this.get("IsAddButtonEnabled")) {
					this.showBlockedMessage();
					return;
				}
				try {
					this.callParent(arguments);
				} catch (e) {
					this.error("UsrMyDetail: addRecord failed: " + e);
				}
			},

			showBlockedMessage: function() {
				const message = this.get("ButtonBlockMessage");
				this.showInformationDialog(message ||
					this.get("Resources.Strings.CannotAddRecordMessage"));
			}
		},

		diff: /**SCHEMA_DIFF*/[
			{
				"operation": "merge",
				"name": "AddRecordButton",
				"values": {
					"visible": { "bindTo": "IsAddButtonVisible" },
					"enabled": { "bindTo": "IsAddButtonEnabled" }
				}
			}
		]/**SCHEMA_DIFF*/
	};
});
