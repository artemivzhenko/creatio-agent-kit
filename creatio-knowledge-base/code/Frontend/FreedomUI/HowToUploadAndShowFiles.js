define("UsrMyPage_FormPage", /**SCHEMA_DEPS*/["@creatio-devkit/common"]/**SCHEMA_DEPS*/, function/**SCHEMA_ARGS*/(sdk)/**SCHEMA_ARGS*/ {
	return {

		// --- How to show attachments and upload a file -------------------------
		// crt.FileList renders the files of the page record, but only with its
		// data wired: `items` is a collection attribute over an attachments data
		// source, `primaryColumnName` that collection's Id attribute, `columns`
		// at least the Name column, and `masterRecordColumnValue` +
		// `recordColumnName` tie the files to the record. A bare
		// {"type": "crt.FileList", "items": "$SomeName"} with no columns stops the
		// WHOLE page from opening (TypeError "... is not iterable" in
		// _setPredefinedColumnDefinitions; 8.2.3, S40-T05).
		//
		// WHICH FILE TABLE: an object with its own <Entity>File keeps files there
		// (recordColumnName = its master lookup); an object without one keeps them
		// in SysFile, matched by RecordId (and RecordSchemaName) - what a Freedom
		// page created from a template gets. Check which exists before copying a
		// list from another page.
		//
		// THE DATA: a record template (PageWithTabsFreedomTemplate) already ships
		// the `AttachmentList` collection attribute and `AttachmentListDS`; reuse
		// them as below - settled on 8.2.3: this list showed the record's SysFile
		// file. On a page whose template ships neither, the collection attribute
		// (Id, Name, CreatedOn, CreatedBy, Size + sortingConfig) and the data
		// source are the page's own inserts (not exercised by the kit).
		//
		// The upload action is a stock request pointed at the list BY NAME:
		//   "clicked": { "request": "crt.UploadFileRequest",
		//                "params": { "viewElementName": "FileList_9ko9jdd" } }
		// A typo fails silently - the button does nothing and no error appears.
		// The record must be SAVED before a file can be attached.
		//
		// CHECKING WHETHER FILES EXIST before allowing an action is a query of the
		// file table with sdk.Model, not a read of the view element.
		// Style: frontend guide 3.2, 3.3, 3.4, 3.5

		viewConfigDiff: /**SCHEMA_VIEW_CONFIG_DIFF*/[

			{
				"operation": "insert",
				"name": "FileList_9ko9jdd",
				"values": {
					"type": "crt.FileList",
					"masterRecordColumnValue": "$Id",
					// SysFile.RecordId; the master lookup of <Entity>File when the object has one
					"recordColumnName": "RecordId",
					"items": "$AttachmentList",
					"primaryColumnName": "AttachmentListDS_Id",
					"viewType": "gallery",
					"tileSize": "small",
					"columns": [
						{
							"id": "5d2a1c3e-0000-4000-8000-000000000061",
							"code": "AttachmentListDS_Name",
							"caption": "#ResourceString(AttachmentListDS_Name)#",
							"dataValueType": 28
						}
					]
				},
				"parentName": "MainContainer",
				"propertyName": "items",
				"index": 0
			},

			{
				"operation": "insert",
				"name": "Button_UploadFile",
				"values": {
					"type": "crt.Button",
					"caption": "#ResourceString(Button_UploadFile_caption)#",
					"iconPosition": "only-text",
					"clicked": {
						"request": "crt.UploadFileRequest",
						// Must match the FileList element name above.
						"params": { "viewElementName": "FileList_9ko9jdd" }
					}
				},
				"parentName": "MainContainer",
				"propertyName": "items",
				"index": 1
			}

		]/**SCHEMA_VIEW_CONFIG_DIFF*/,

		viewModelConfigDiff: /**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/[]/**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/,
		modelConfigDiff: /**SCHEMA_MODEL_CONFIG_DIFF*/[]/**SCHEMA_MODEL_CONFIG_DIFF*/,

		handlers: /**SCHEMA_HANDLERS*/[

			// Refuse an action while the record has no attachments.
			{
				request: "usr.SubmitForApprovalRequest",
				handler: async (request, next) => {
					const recordId = await request.$context.PDS_Id_a1b2c3d;

					const fileModel = await sdk.Model.create("UsrRequestFile");
					const files = await fileModel.load({
						attributes: ["Id"],
						parameters: [{
							type: sdk.ModelParameterType.Filter,
							value: await (new sdk.FilterGroup()).addSchemaColumnFilterWithParameter(
								sdk.ComparisonType.Equal, "UsrRequest", recordId)
						}]
					});

					if (!files.length) {
						const dialogService = new sdk.DialogService();
						await dialogService.open({
							message: await request.$context.Resources.Strings.NoFilesAttachedMessage,
							actions: [
								{
									key: "OK",
									config: {
										color: "primary",
										caption: await request.$context.Resources.Strings.OkButtonCaption
									}
								}
							]
						});
						// Stop here: do not pass the request on.
						return false;
					}

					return next?.handle(request);
				}
			}

		]/**SCHEMA_HANDLERS*/,

		converters: /**SCHEMA_CONVERTERS*/{}/**SCHEMA_CONVERTERS*/,
		validators: /**SCHEMA_VALIDATORS*/{}/**SCHEMA_VALIDATORS*/

	};
});
