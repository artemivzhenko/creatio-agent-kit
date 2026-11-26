"""Freedom UI component types -> the element types of the UI test utility's page files (automatic-creatio-tests).

The framework addresses an element by its `element-name`, which is the `name` of the view-config
item (all 11 own controls of a two-tab test page matched what `analyse` wrote). None means the type
depends on the bound column or the control's options (see PageSchema.page_file).
"""

FRAMEWORK_TYPE: dict[str, str | None] = {
    "crt.Input": "Text",
    "crt.RichTextEditor": "RichText",
    "crt.EmailInput": "Email",
    "crt.PhoneInput": "Phone",
    "crt.WebInput": "Link",
    "crt.NumberInput": None,       # Integer for an Integer column, else Decimal
    "crt.DateTimePicker": None,    # pickerType date / time / datetime, else the column's type
    "crt.Checkbox": "Boolean",
    "crt.ComboBox": "Lookup",
    "crt.Button": "Button",
    "crt.TabContainer": "Tab",     # one tab of a tab panel
    "crt.DataGrid": "DataGrid",
    "crt.EntityStageProgressBar": "CasesBar",
    "crt.ButtonToggleGroup": "ToggleTab",
}
PICKER_TYPE = {"date": "Date", "time": "Time", "datetime": "DateTime"}

# What `analyse` found on pages of a template that the page's own schema never lists (the template's elements).
# Read off the analysed pages of the test bed; a page that removes or hides one drops it.
TEMPLATE_ELEMENTS: dict[str, list[dict]] = {
    "PageWithTabsFreedomTemplate": [
        {"code": "AttachmentAddButton", "label": "", "type": "Button"},
        {"code": "AttachmentRefreshButton", "label": "", "type": "Button"},
        {"code": "BackButton", "label": "", "type": "Button"},
        {"code": "CloseButton", "label": "Close", "type": "Button"},
        {"code": "SetRecordRightsButton", "label": "", "type": "Button"},
        {"code": "SaveButton", "label": "Save", "type": "Button", "pinned": True, "isSave": True},  # as the tester's page files have them
        {"code": "CancelButton", "label": "Cancel", "type": "Button", "pinned": True},
        {"code": "GeneralInfoTab", "label": "General information", "type": "Tab"},
        {"code": "CardButtonToggleGroup", "label": "", "type": "ToggleTab", "tabs": ["Feed", "Attachments"]},
    ],
    # a process's pre-configured page (S45-T09): the buttons a page task element completes on; a page with no data source saves nothing
    "BaseMiniPageTemplate": [
        {"code": "CancelButton", "label": "Cancel", "type": "Button"},
        {"code": "CloseButton", "label": "Close", "type": "Button"},
        {"code": "SaveButton", "label": "Save", "type": "Button"},
    ],
}

# UIds of base Freedom pages (SysSchema, ExtendParent false): the same row on every site; `pages.py replace` reads them when the
# workspace has no copy. Read on 8.3.2 (S48-T07); a page not listed is looked up on the site (--env).
BASE_PAGES: dict[str, str] = {
    "Accounts_FormPage": "22cc919e-9774-4117-b32d-39e829f2f197",
    "Contacts_FormPage": "e785a54d-7cc8-467f-9768-958ff8ad34d2",
    "Leads_FormPage": "925f6863-2ffd-49b9-b3b8-f12232583dfe",
    "Opportunities_FormPage": "d205e43b-228c-4725-aed2-d1c9dbef650e",
}
