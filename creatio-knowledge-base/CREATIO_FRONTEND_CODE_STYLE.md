# Creatio Front-End Code Style & Architecture Guide

Non-functional rules for writing client code for Creatio, derived from the platform's own sources (8.3: the core
client library, the compiled Classic and Freedom UI schemas, the SDK bundles, the shipped tooling configs and the
official project templates). Four kinds of code are covered: Classic UI schemas (7.x style, `define` + `Terrasoft.*`),
Freedom UI schemas (8.x, `/**SCHEMA_DEPS*/` + handlers), Angular remote modules and mobile handler modules
(TypeScript on `@creatio-devkit/common` / `@creatio/mobile-common`). Where the platform is inconsistent the rule
below names the dominant form and says so. Recipes show what to call; this guide says how the code must look.

---

## 1. Formatting

### 1.1 Schema JavaScript (Classic and Freedom UI)

- **Tabs** for indentation, lines up to **120** columns (the platform's `.prettierrc`: `useTabs`, `tabWidth 4`,
  `printWidth 120`, `trailingComma es5`). Continuation lines get one extra tab.
- **Double quotes** for every string; single quotes only inside a string or a comment.
- K&R braces, `} else {` on one line, braces on every `if`, `function(` without a space, `if (` with one.
- `===` / `!==` always.
- `const` and `let` in new code; `var` only when editing old code around it. Arrow functions for inline callbacks;
  `function` where `this` is the view model (Classic `methods`, Freedom validators).
- No `"use strict"`, no file header, no copyright banner: a schema file starts with its `define`.
- No trailing comma after the last member of an object in a schema: the designer rewrites these blocks and
  keeps them as JSON. The `.prettierrc`'s `trailingComma: es5` is the core library's setting: prettier is not run
  over schema files.
- A template literal for a string that holds double quotes or several lines (an HTML fragment); otherwise double
  quotes.
- A `TODO` carries a ticket id: `// TODO: PRJ-123 remove after the lookup is renamed`.

### 1.2 TypeScript (remote modules and mobile)

From the official template configs (`.editorconfig`, `tsconfig.json`):

- Two spaces, single quotes, semicolons, trailing commas in multi-line literals, a final newline.
- `strict: true`, `noImplicitOverride`, `noImplicitReturns`, `noPropertyAccessFromIndexSignature`,
  `strictTemplates`: the generated project is strict and stays strict.
- File names kebab-case with the type as suffix: `order-total.component.ts`, `order-total.component.spec.ts`,
  `recalculate-order.handler.ts`, `order.service.ts`, `recalculate-order.request.ts`.

---

## 2. Classic UI schemas

### 2.1 Skeleton

```javascript
define("UsrOrderPage", ["BusinessRuleModule", "UsrOrderPageResources", "ServiceHelper", "css!UsrOrderPageCSS"],
	function(BusinessRuleModule, resources, ServiceHelper) {
		return {
			entitySchemaName: "UsrOrder",
			messages: {
				/**
				 * @message OrderTotalChanged
				 * Published after the order total is recalculated.
				 */
				"OrderTotalChanged": {
					mode: Terrasoft.MessageMode.BROADCAST,
					direction: Terrasoft.MessageDirectionType.PUBLISH
				}
			},
			attributes: {
				/** Whether the discount block is shown. */
				"IsDiscountVisible": {
					dataValueType: Terrasoft.DataValueType.BOOLEAN,
					value: false
				},
				"Total": {
					dependencies: [{columns: ["Amount", "Discount"], methodName: "onTotalSourceChanged"}]
				}
			},
			rules: {},
			details: /**SCHEMA_DETAILS*/{}/**SCHEMA_DETAILS*/,
			modules: /**SCHEMA_MODULES*/{}/**SCHEMA_MODULES*/,
			mixins: {
				TimezoneMixin: "Terrasoft.TimezoneMixin"
			},
			methods: {},
			diff: /**SCHEMA_DIFF*/[]/**SCHEMA_DIFF*/
		};
	});
```

- `define("<Schema>", [deps], function(args))`: the schema name in double quotes; dependencies that are used as
  values come first and are bound to parameters, the rest (`css!X`, mixins loaded for their side effect) go last
  and stay unbound. The resources module is bound as `resources`.
- Do not list `"ext-base"`, `"terrasoft"` or `"sandbox"`: `Ext`, `Terrasoft` and `this.sandbox` are available.
  Only legacy utility modules still import `ext-base` / `terrasoft` as `Ext, Terrasoft`.
- A page, section or detail schema returns a plain object. Block order (the designer's order, and `diff` is last
  in nine of ten platform layers): `entitySchemaName, messages, attributes, rules, details, modules, mixins,
  methods, dataModels, diff`. Keep the designer markers `/**SCHEMA_DETAILS*/`, `/**SCHEMA_MODULES*/`,
  `/**SCHEMA_BUSINESS_RULES*/`, `/**SCHEMA_DIFF*/` on the blocks the designer owns; an empty diff is
  `/**SCHEMA_DIFF*/[]/**SCHEMA_DIFF*/`.
- A layer that adds nothing returns `{}`.
- Quoting: attribute, message and diff keys are quoted strings (`"IsDiscountVisible"`, `"operation"`); the config
  keys inside them are bare (`dataValueType`, `value`, `mode`). The platform mixes both; choose this form for
  the hand-written blocks; a block the designer owns (`details`, `modules`, `businessRules`, the wizard's `diff`)
  keeps the designer's quoted keys and spacing, so a later designer save produces no diff noise.

### 2.2 Modules, mixins and utilities

A reusable module is a class, not a bag of functions:

```javascript
define("UsrOrderUtilities", [], function() {
	Ext.define("Terrasoft.configuration.mixins.UsrOrderUtilities", {
		alternateClassName: "Terrasoft.UsrOrderUtilities",

		//region Methods: Public

		/**
		 * Returns the order total with the discount applied.
		 * @param {Number} amount Order amount.
		 * @param {Number} discount Discount percent.
		 * @return {Number} The total.
		 */
		getTotal: function(amount, discount) {
			return amount - amount * discount / 100;
		}

		//endregion

	});
	return Terrasoft.UsrOrderUtilities;
});
```

- `Ext.define("Terrasoft.configuration[.mixins].<Name>", {...})` with `alternateClassName: "Terrasoft.<Name>"`;
  `singleton: true` for a helper with no state per page. Return the class (mixin), the singleton, or
  `Ext.create(...)` for a stateful utility instance.
- Member order inside `Ext.define`: `extend`, `alternateClassName`, `singleton`, `statics`, `mixins`, then
  properties, constructor, methods.
- Object-typed properties default to `null` and are created in `init` or the constructor
  (`this.validationConfig = this.validationConfig || {};`), never as a shared literal on the prototype.
- Regions inside `methods` and classes: `//region <Kind>: <Visibility>` ... `//endregion`, kinds `Properties`,
  `Constructors`, `Methods`, visibility `Private`, `Protected`, `Public`, in that order.
- The UpperCamel exports of old utility modules (`LookupUtilities.Open`) are legacy; new code exposes lowerCamel
  methods on a class.

### 2.3 Naming

- Methods are lowerCamel verbs; the prefixes the platform uses, in order of frequency: `get`, `on` (event and
  change handlers: `onBirthdateChanged`, `onCallClick`), `init`, `set`, `is`, `add`, `load`, `update`, `show`,
  `open`, `check`, `subscribe`, `save`, `create`, `run`, `can`, `validate`, `clear`, `prepare`, `hide`, `handle`.
- A private method starts with `_` and is tagged `@private`: `_initCommunicationSynchronization`.
- Attributes are UpperCamel strings; booleans start with `Is`, `Can`, `Use`, `Show`: `"IsEmailDetailVisible"`,
  `"CanEditMasterRecord"`. Attribute config keys: `dataValueType`, `value`, `type`
  (`Terrasoft.ViewModelColumnType.VIRTUAL_COLUMN`), `dependencies`, `lookupListConfig`, `onChange`.
- Messages are UpperCamel (`"UpdatePageHeaderCaption"`, `"CardSaved"`), each with a `@message` doc block and
  `mode` (`PTP`, `BROADCAST`) plus `direction` (`PUBLISH`, `SUBSCRIBE`, `BIDIRECTIONAL`).
- Diff element names are UpperCamel with the role as suffix: `"DiscountContainer"`, `"RecalculateButton"`,
  `"DeliveryTab"`, `"TotalsControlGroup"`. Diff key order in Classic: `"operation"`, `"name"` / `"parentName"`,
  `"propertyName"`, `"values"`, then `"index"` (Freedom UI orders them differently, 3.2).
- CSS classes are kebab-case: `"wrapClass": ["order-totals-container"]`.
- Business rule names say what they do: `"FiltrationCityByCountry"`, `"BindParameterEnabledDiscountToIsVip"`.
- Localizable strings: in `diff` `{"bindTo": "Resources.Strings.X"}`; in `methods` `this.get("Resources.Strings.X")`
  and `this.get("Resources.Images.X")`; in a mixin or utility `resources.localizableStrings.X`. Never a caption
  literal.
- The `$` shorthand for attributes (`this.$IsDiscountVisible`) is accepted in new platform code.

### 2.4 Inheritance and lifecycle

- A synchronous override calls `this.callParent(arguments)` first, then adds its work; when the parent's result is
  needed: `const items = this.callParent(arguments); items.addItem(...); return items;`.
- `this.callParent(arguments)` followed by synchronous wiring (subscriptions, attribute defaults) is the normal
  `init`; the parent receives the caller's callback untouched. Wrap the continuation only when your work must run
  after the parent's asynchronous part has finished (data the parent loads) or is asynchronous itself:

```javascript
init: function(callback, scope) {
	this.callParent([function() {
		this.subscribeOrderEvents();
		callback.call(scope);
	}, this]);
},
```

- `destroy` cleans up first and calls `callParent` last; `onEntityInitialized` calls `callParent` first.
- A mixin method is called explicitly: `this.mixins.TimezoneMixin.init.call(this);`,
  `this.mixins.GridUtilities.destroy.call(this);`.
- Sandbox: `this.sandbox.subscribe("OrderTotalChanged", this.onOrderTotalChanged, this, [detailId]);`,
  `this.sandbox.publish("UpdateCardProperty", config, [this.sandbox.id]);`, `this.sandbox.loadModule("Rights",
  {renderTo: ..., id: ..., keepAlive: true})`. Subscribe once, in `subscribeSandboxEvents` (pages) or `init`;
  never call `init` again from a server message handler (it duplicates every subscription, P-6.4).
- Helpers: `Ext.create("Terrasoft.BaseViewModelCollection")`, `Terrasoft.each(items, fn, this)`,
  `Ext.isEmpty(value)`, `Ext.callback(callback, scope)`, `Terrasoft.chain(stepA, stepB, this)`. Use `this.Ext`,
  `this.Terrasoft`, `this.sandbox` inside a view model where they are declared; the bare globals are accepted.
- Feature and setting reads: `Terrasoft.Features.getIsEnabled("X")` or `this.getIsFeatureEnabled("X")`;
  `Terrasoft.SysSettings.querySysSettings(["UsrDefaultCurrency"], function(values) {...}, this)`.

### 2.5 Data access and services

- Async style is **callback + scope** (`callback, scope` are the last two parameters, invoked with
  `Ext.callback(callback, scope || this, [result])`); multi-step flows use `Terrasoft.chain`. No promises, no
  `async`/`await` in Classic schemas.

```javascript
loadOrderProducts: function(callback, scope) {
	const esq = this.Ext.create("Terrasoft.EntitySchemaQuery", {rootSchemaName: "UsrOrderProduct"});
	esq.addColumn("Product");
	esq.addAggregationSchemaColumn("Amount", this.Terrasoft.AggregationType.SUM, "AmountSum");
	esq.filters.addItem(this.Terrasoft.createColumnFilterWithParameter(
		this.Terrasoft.ComparisonType.EQUAL, "Order", this.get("Id")));
	esq.getEntityCollection(function(result) {
		if (!result.success) {
			return;
		}
		this.set("Total", result.collection.getItems()[0].get("AmountSum"));
		Ext.callback(callback, scope);
	}, this);
},
```

- Every ESQ callback opens with a `result.success` check. Guard a column that may be missing on an environment
  with `esq.rootSchema.findSchemaColumnByPath(path)` before adding it.
- A service call on a view model: `this.callService(config, this.onServiceResponse, this)`; a config that is reused
  or longer than a few lines comes from a `get<Name>ServiceConfig()` returning `{serviceName, methodName, data:
  {request: {...}}}`, a one-off config is inline. In a module without a view model:
  `ServiceHelper.callService({serviceName, methodName, data, callback, scope})`.
- Validation: register in `setValidationConfig` after `callParent`:
  `this.addColumnValidator("Email", EmailHelper.getEmailValidator);`. A validator returns `{invalidMessage}`
  (optionally `fullInvalidMessage`) built from a resource string, and `{invalidMessage: ""}` (or `{}`) when valid;
  never nothing. In a save interceptor a failed query is a failed validation, not a pass.
- Business rules in `rules`: `"<Attribute>": {"<RuleName>": {ruleType: BusinessRuleModule.enums.RuleType.X, ...}}`
  with `BusinessRuleModule.enums.RuleType` (`BINDPARAMETER`, `FILTRATION`, `AUTOCOMPLETE`,
  `POPULATE_ATTRIBUTE`), `.ValueType`, `.Property` (`VISIBLE`, `ENABLED`, `REQUIRED`, `READONLY`); hand-written
  `businessRules` add `logical: Terrasoft.LogicalOperatorType.AND`.

### 2.6 User messages, masks, errors and logging

- On a view model: `this.showInformationDialog(message)`, `this.showConfirmationDialog(message, function(returnCode)
  {...}, [Terrasoft.MessageBoxButtons.YES, Terrasoft.MessageBoxButtons.NO])`; compare
  `returnCode === Terrasoft.MessageBoxButtons.YES.returnCode`. Outside a view model `Terrasoft.showInformation`,
  `Terrasoft.showConfirmation`. The message text is always a resource string.
- Masks: `this.showBodyMask({selector, timeout: 0})` / `this.hideBodyMask()`; `Terrasoft.MaskHelper.showBodyMask`
  underneath. The PascalCase `MaskHelper.ShowBodyMask` is deprecated.
- Throw the typed exceptions: `throw new Terrasoft.ArgumentNullOrEmptyException({argumentName: "config"})`,
  `Terrasoft.ItemNotFoundException`, `Terrasoft.UnsupportedTypeException`, `Terrasoft.InvalidOperationException`,
  `Terrasoft.NotImplementedException`; the message from `Terrasoft.Resources.Exception.*`. Not `new Error(...)`.
- Log through the object: `this.log(message, Terrasoft.LogMessageType.WARNING)`, `this.warning(message)`,
  `this.error(message)`; a strict check only in debug: `if (Terrasoft.isDebug) { throw ... } else { this.error(...) }`.
  No `console.*` in schema code.
- Retiring a method: keep it, tag `@deprecated <version> Use <new> instead.` (or `@obsolete`), log
  `Ext.String.format(Terrasoft.Resources.ObsoleteMessages.ObsoleteMethodMessage, "old", "new")` and delegate.

### 2.7 JSDoc

The platform documents nearly every method (JSDuck tags plus the custom `@virtual`, `@overridden`, `@message`).
Package code does the same; a knowledge-base recipe shows the form once and teaches through its header prose:

```javascript
/**
 * @inheritdoc Terrasoft.BasePageV2#onEntityInitialized
 * @override
 */
onEntityInitialized: function() {
	this.callParent(arguments);
	this.updateDiscountVisibility();
},

/**
 * Returns the discount percent for the order's customer.
 * @protected
 * @virtual
 * @param {String} customerId Customer identifier.
 * @param {Function} callback Callback function.
 * @param {Object} scope Scope of callback function.
 */
getCustomerDiscount: function(customerId, callback, scope) {
```

- An override: `@inheritdoc <Class>#<member>` plus `@override` (the platform also writes `@overridden`; `@override`
  is the more common one). An extension point: `@protected` + `@virtual`. A private method: `@private`.
- `@param {Type} name Description.` with capitalised types (`{String}`, `{Boolean}`, `{Object}`, `{Function}`,
  `{Terrasoft.BaseViewModel}`), `[name]` for an optional parameter, `@return {Type} Description.` (not `@returns`).
- The description is one sentence in the third person ending with a period: `Returns ...`, `Initializes ...`,
  `Handles ...`, `Opens ...`. Attributes get a one-line `/** ... */`, messages a `@message Name` block.
- `@deprecated 8.1 Use getTotal instead.` carries the version and the replacement.

---

## 3. Freedom UI schemas

### 3.1 Skeleton

```javascript
define("UsrOrders_FormPage", /**SCHEMA_DEPS*/["@creatio-devkit/common"]/**SCHEMA_DEPS*/, function/**SCHEMA_ARGS*/(sdk)/**SCHEMA_ARGS*/ {
	return {
		viewConfigDiff: /**SCHEMA_VIEW_CONFIG_DIFF*/[
			{
				"operation": "insert",
				"name": "Button_Recalculate",
				"values": {
					"type": "crt.Button",
					"caption": "#ResourceString(Button_Recalculate_caption)#",
					"color": "primary",
					"clicked": {
						"request": "usr.RecalculateOrderRequest"
					}
				},
				"parentName": "ActionButtonsContainer",
				"propertyName": "items",
				"index": 0
			}
		]/**SCHEMA_VIEW_CONFIG_DIFF*/,
		viewModelConfigDiff: /**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/[
			{
				"operation": "merge",
				"path": ["attributes"],
				"values": {
					"Total": {"modelConfig": {"path": "PDS.UsrTotal"}},
					"IsDiscountVisible": {"value": false}
				}
			}
		]/**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/,
		modelConfigDiff: /**SCHEMA_MODEL_CONFIG_DIFF*/[]/**SCHEMA_MODEL_CONFIG_DIFF*/,
		handlers: /**SCHEMA_HANDLERS*/[
			{
				request: "usr.RecalculateOrderRequest",
				handler: async (request, next) => {
					const amount = await request.$context.Amount;
					request.$context.Total = amount - amount * (await request.$context.Discount) / 100;
					return next?.handle(request);
				}
			}
		]/**SCHEMA_HANDLERS*/,
		converters: /**SCHEMA_CONVERTERS*/{}/**SCHEMA_CONVERTERS*/,
		validators: /**SCHEMA_VALIDATORS*/{}/**SCHEMA_VALIDATORS*/
	};
});
```

- The `define` line and the six blocks in this order, every block present even when empty, every block wrapped
  in its marker on both sides: `viewConfigDiff`, `viewModelConfigDiff`, `modelConfigDiff`, `handlers`,
  `converters`, `validators` (the last one without a trailing comma). The `...Diff` trio is the form for a layer
  over an existing page (293 of 372 platform layers); `viewModelConfig` / `modelConfig` without `Diff` only when
  the layer defines the whole object.
- Dependencies: `"@creatio-devkit/common"` bound as `sdk` (the platform also writes `devkit` and `common`; use
  `sdk`), then `css!X` and component modules unbound.
- The declarative blocks are JSON: double-quoted keys and values, no trailing commas, no comments, no functions.
  Handlers use bare keys `request:` / `handler:`.
- No JSDoc in Freedom UI schemas; a `//` comment only for the why the code cannot show
  (`// Do not refresh page data while composer is visible.`) or a ticketed TODO. A page in a package carries no
  comment inside the declarative blocks (the designer drops them); a recipe may, it teaches there.

### 3.2 View config

- A diff item's keys in this order: `"operation"`, `"name"`, `"values"`, `"parentName"`, `"propertyName"`,
  `"index"`. `merge` carries `values` only; `move` carries `parentName`, `propertyName`, `index`; `remove` the
  name only. `propertyName` is `items`, `tools` (toolbar) or `menuItems`.
- Inside `values`, `layoutConfig` (`column`, `row`, `colSpan`, `rowSpan`) then `type` first, then the rest.
- Element names are `<Type>_<Purpose>` in UpperCamel: `Button_Recalculate`, `TabContainer_Delivery`,
  `GridContainer_Totals`, `MenuItem_ShowDuplicates`, `Label_Warning`; a field element is named after its column
  (`"name": "UsrDeliveryDate"`). The designer's `Type_<7 random chars>` names are kept as they are, never typed by
  hand.
- Bindings: `"$Attribute"`; control attributes follow the designer's prefixes
  (`$StringAttribute_...`, `$LookupAttribute_...`, `$PDS_...`, `$PageParameters_...`).
- Captions: `"#ResourceString(Element_property)#"` for captions, titles, placeholders and tooltips
  (`Button_Recalculate_caption`, `TabContainer_Delivery_caption`); `"$Resources.Strings.X"` for a field label and
  for elements inherited from a base template. Never a caption literal, not even `"OK"` in a dialog action.
- Boolean and filter bindings go through the built-in converters with the pipe syntax:
  `"visible": "$HasUnsavedData | crt.InvertBooleanValue"`, `"visible": "$CardState | crt.IsEqual : 'edit'"`,
  `"filters": "$Items | crt.ToCollectionFilters : 'Items' : $Items_SelectionState | crt.SkipIfSelectionEmpty : $Items_SelectionState"`.
  A static value is a literal (`"visible": true`).
- `clicked` is `{"request": "<type>", "params": {...}}` or an array of them run in sequence; `clickMode`
  `"default"` or `"menu"`. A process: `{"request": "crt.RunBusinessProcessRequest", "params": {"processName":
  "UsrRecalculateOrder", "processRunType": "ForTheSelectedPage", "recordIdProcessParameterName": "OrderId"}}`.

### 3.3 View model and model config

- An attribute bound to the record: `"Total": {"modelConfig": {"path": "PDS.UsrTotal"}}`; a page-only attribute:
  `"IsDiscountVisible": {"value": false}` (no `dataValueType`); a related column: in the data source's
  `attributes` as `{"path": "PrimaryContact.JobTitle", "type": "ForwardReference"}`.
- A collection: `"isCollection": true, "modelConfig": {"path": "<Name>DS", "filterAttributes": [{"name":
  "<Name>_PredefinedFilter", "loadOnChange": true}], "sortingConfig": {...}}`, its item attributes
  `"<Name>DS_<Column>": {"modelConfig": {"path": "<Name>DS.<Column>"}}`.
- Validators inside an attribute are a keyed map: `"validators": {"required": {"type": "crt.Required"},
  "maxLength": {"type": "crt.MaxLength", "params": {"maxLength": 250}}}`; built-ins `crt.Required`,
  `crt.MaxLength`, `crt.RegExp`, `crt.StringUrlValidator`, `crt.IsJsonValidator`.
- `modelConfigDiff` order: first the merge at `"path": []` with `primaryDataSourceName` and `dependencies`, then
  the merge at `"path": ["dataSources"]`. The primary data source is `PDS`, every other one `<Name>DS`, type
  `crt.EntityDataSource` with `entitySchemaName`, scope `page` (a detail's data source `viewElement`).
- Merge paths: `"path": ["attributes"]` with the attributes as `values` (the dominant form) or `"path": []` with
  `"values": {"attributes": {...}}`; nested collections `["attributes", "Items", "viewModelConfig", "attributes"]`.

### 3.4 Handlers and requests

- A handler is `{request: "<type>", handler: async (request, next) => {...}}`; always `next?.handle(request)`
  with optional chaining, and the result returned: `return next?.handle(request);` (`return await` only when a
  `try`/`finally` needs the awaited value).
- **Call `next` last** when the handler prepares state or guards (`crt.HandleViewModelInitRequest` setting
  page-only attributes, a validation that may veto: report through `crt.NotificationRequest` and `return false`
  without `next`). Exception in `crt.HandleViewModelInitRequest`: a handler that reads data-source attributes
  (`PDS.*`, `$context.Id`) calls `next` first, they exist only after the base init. **Call `next` first** when the handler needs the base result (`crt.LoadDataRequest`,
  `crt.SaveRecordRequest` post-processing): `const result = await next?.handle(request); ...; return result;`.
  Wrap with a mask: `const mask = new sdk.MaskService(); const id = mask.showBodyMask({delay: 0}); await next?.handle(request); mask.hideBodyMask(id);` (`sdk` from `@creatio-devkit/common`; `MaskService` has `showMask`, `hideMask`, `showBodyMask`, `hideBodyMask` and `showBodyMask` returns an object that `hideBodyMask` took, seen on 8.2.3, S42-T02; hide in a `finally` when the chain may throw).
  A handler that replaces the chain does not call `next` and takes `(request)` only.
- `crt.HandleViewModelAttributeChangeRequest`: filter first, `if (request.attributeName === "Discount") {...}` or
  `const changed = ["Amount", "Discount"]; if (changed.includes(request.attributeName)) {...}`; a data source
  guard `if (request.dataSourceName !== "PDS") { return next?.handle(request); }`.
- Attributes: read with `await request.$context.Amount` (or `await request.$context[name]`), write by assignment
  `request.$context.Total = total;` (or `await request.$context.set("Total", total)` for a dynamic name).
  Resources: `await request.$context.Resources.Strings.RecalculatedMessage`.
- Executing another request: inside a handler `await request.$context.executeRequest({type:
  "usr.RecalculateOrderRequest", orderId})`; where no `$context` is at hand (a remote element, a service)
  `await sdk.HandlerChainService.instance.process({type: "crt.LoadDataRequest", config: {loadType: "reload"},
  dataSourceName: "PDS", $context: request.$context})`. Not `new HandlerChainService()`, not
  `$context.handlerChain`. `process` reaches the page's own `SCHEMA_HANDLERS` only with `scopes: [...request.scopes]`;
  without it a `usr.*` request the page handles resolves to `undefined` and nothing runs, while `executeRequest`
  fills the scopes itself (settled on 8.2.3, S40-T05). So `executeRequest` stays the form inside a handler; pass
  `scopes` whenever `process` must reach a page handler.
- Request names are `<vendor>.<Verb><Noun>Request` in PascalCase; the SDK enforces `Vendor.Name` and PascalCase
  for `crt`. `crt.` is the platform's prefix: custom requests, converters and validators are `usr.*`
  (`usr.RecalculateOrderRequest`, `usr.ToOrderStatusCaption`, `usr.OrderNumberValidator`).
- A converter in `converters`: `"usr.ToOrderStatusCaption": value => value?.displayValue ?? ""`.
- A validator in `validators` is a factory of a `function(control)` returning `null` or an error keyed by the
  validator's own name, with the message passed through `params`:

```javascript
"usr.OrderNumberValidator": {
	"validator": function(config) {
		return function(control) {
			return /^ORD-\d{6}$/.test(control.value) ? null : {"usr.OrderNumberValidator": {message: config.message}};
		};
	},
	"params": [{"name": "message"}],
	"async": false
}
```

  used as `"validators": {"orderNumber": {"type": "usr.OrderNumberValidator", "params": {"message":
  "#ResourceString(OrderNumberInvalid)#"}}}`; enable one at runtime with
  `await request.$context.enableAttributeValidator("Number", "orderNumber")`.

### 3.5 Data, services, errors

- The usual path is declarative: data sources in `modelConfigDiff`, reload with `crt.LoadDataRequest`
  (`config: {loadType: "reload"}`, `dataSourceName`), delete with `crt.DeleteDataRequest` and a
  `ModelParameterType.PrimaryColumnValue` parameter, records with `crt.CreateRecordRequest`,
  `crt.UpdateRecordRequest`, `crt.SaveRecordRequest`, `crt.OpenPageRequest`, `crt.ClosePageRequest`.
- Filtering a lookup: a `sdk.FilterGroup` with `sdk.ComparisonType` / `sdk.LogicalOperatorType`, pushed as
  `request.parameters.push({type: "filter", value: filter})` in `crt.LoadDataRequest`; not a pasted serialized
  filter JSON.
- Reading records from a handler: `const model = await sdk.Model.create("UsrOrder"); await model.load({attributes:
  ["Number"], parameters: [{type: sdk.ModelParameterType.Filter, value: filter}]})`; `load` without a filter
  returns every row (P-8.1).
- Platform services: `new sdk.FeatureService().getFeatureState("X")`, `new sdk.SysSettingsService().getByCode("X")`
  (check `.value`), `new sdk.RightsService().getCanExecuteOperation("CanRecalculate")`,
  `new sdk.HttpClientService().post("/rest/UsrOrderService/Recalculate", data)` for an own service; not the
  Classic `Terrasoft.Features`, `Terrasoft.createFilterGroup`, `Terrasoft.showInformation`.
- `async`/`await` throughout, no `.then` chains. `try`/`catch` only where a failure is reported to the user:
  `catch (e) { await request.$context.executeRequest({type: "crt.NotificationRequest", message:
  await request.$context.Resources.Strings.RecalculateFailed}); return false; }`. A success check reads the result:
  `if (!result.success) {...}`.
- Messages: `crt.NotificationRequest` (`message`), `crt.ShowDialogRequest` (`dialogConfig: {data: {title,
  message, actions: [{key: "OK", config: {color: "primary", caption}}]}}`; the platform's 8.3 schemas use this
  shape, `message` / `actions` at the top level is the older form) with resource strings.
- A legacy `Terrasoft.*` call stays only where the SDK has no counterpart (`Terrasoft.ServerChannel` for server
  messages, `Terrasoft.getFileContentUrl` for a package file), with a one-line comment saying so; navigation goes
  through `crt.OpenPageRequest` or the Shell hash (`#Section/<ListPage>`, P-C2), never `Terrasoft.workspaceBaseUrl`
  + `window.open`.
- No `document.*`, no jQuery, no `setTimeout` waits, no `window.location.reload`, no `console.*`, no GUID literals
  (read the lookup value by code or a system setting), no `var`.

---

## 4. Angular remote modules

From the official template (`angular.json`, `.editorconfig`, `tsconfig.json`, the Academy component):

- `prefix: "usr"`: selectors `usr-<name>`, Freedom UI types `usr.<Name>`, the module bootstrapped as the package
  name (`bootstrapCrtModule("usr_order_module", AppModule, {resolveDependency: token =>
  this._injector.get(token)})`).
- A view element stacks the Angular and the Crt decorators, in this order:

```typescript
@Component({
  selector: 'usr-order-total',
  templateUrl: './order-total.component.html',
  styleUrls: ['./order-total.component.scss'],
  encapsulation: ViewEncapsulation.ShadowDom,
})
@CrtViewElement({
  selector: 'usr-order-total',
  type: 'usr.OrderTotal',
})
@CrtInterfaceDesignerItem({
  toolbarConfig: {
    caption: 'Order total',
    name: 'OrderTotal',
    icon: require('!!raw-loader?{esModule:false}!./icon.svg'),
    defaultPropertyValues: { value: '' },
  },
})
export class OrderTotalComponent {
  @Input() @CrtInput() public value: string = '';
  @Output() @CrtOutput() public valueChange = new EventEmitter<string>();
  @Input() @CrtValidationInput() public valueValidationInfo!: CrtValidationInfo;

  constructor(private readonly _injector: Injector) {}
}
```

- Fields before the constructor; `public` written out on inputs and outputs; injected privates `_camelCase`,
  `readonly`.
- A request handler: `@CrtRequestHandler({type: 'usr.RecalculateOrderHandler', requestType: RECALCULATE_ORDER,
  scopes: PAGE_SCOPES})` on `class RecalculateOrderHandler extends BaseRequestHandler<RecalculateOrderRequest>`
  with `public async handle(request): Promise<unknown> { ...; return this.next?.handle(request); }`; request
  types and scopes are `UPPER_SNAKE` constants (`export const RECALCULATE_ORDER = 'usr.RecalculateOrderRequest';`).
- A service: `@Injectable({providedIn: 'root'})`, `private readonly _http = new HttpClientService();`; everything
  from `@creatio-devkit/common` in one named import.
- The module: `@CrtModule({viewElements: [...], requestHandlers: [...]})` above `@NgModule`, then
  `customElements.define('usr-order-total', element)` in `ngDoBootstrap`.
- `:host { box-sizing: border-box; }` when the element takes `width: 100%` with a padding (P-C5). A page resource
  string reaches an element through `"#ResourceString(Key)#"` on its input (P-C3). A plain `href` inside the
  shadow DOM navigates the Shell (P-C2).
- Tests are Jasmine on Karma, `*.spec.ts` next to the component, the root `describe` named after the class.

## 5. Mobile handler modules

From the official `ts_sdk_template_module` configs and the kit's template:

- `tsconfig`: `strict`, `experimentalDecorators`, `emitDecoratorMetadata`, target `es2019`; `@creatio/mobile-common`
  is an external (`crtSdk`); the build writes `main.js` and `main.debug.js` into `out/mobile/<module>`.
- Classes carry the `Usr` prefix: `UsrMobileModule`, `UsrRecalculateOrderRequest`, `UsrRecalculateOrderHandler`.
- A request is a decorated class: `@CrtRequest({type: RECALCULATE_ORDER}) export class UsrRecalculateOrderRequest
  extends BaseRequest`; the handler as in section 4; the module
  `@CrtModule({requestHandlers: [...]}) export class UsrMobileModule implements DoBootstrap { public bootstrap():
  void { bootstrapCrtModule('UsrMobileModule', UsrMobileModule); } }`.
- Logging through `Logger.console(\`[UsrMobileModule] ...\`)`; chained requests through
  `HandlerChainService.instance.process({...})`.

---

## 6. Where the code lives and how it is tested

- A Classic schema is `Schemas/<Name>/<Name>.js` with its resources; a module or mixin is a client module schema
  of the same shape. A Freedom UI page is `Schemas/<Page>/<Page>.js` plus `metadata.json` (its business rules in
  the addon `<Page>BusinessRule`, P-2.11). A remote module and a mobile module are TypeScript projects whose build
  output the package ships (the `RemoteModule` and `Mobile` recipes say where).
- Client unit tests in the platform are Jasmine on Karma: `*.unit.spec.js` (logic) and `*.ui.spec.js` (DOM) next
  to the source, the root `describe` named after the file, nested `describe("when ...")`, data-driven
  `testCases` arrays. In the kit a page is proven by the UI test utility's `.act` cases
  (`cases_from_package`, the creatio-tests server) and a handler's effect by an OData or process case.
- A Freedom UI page's request names, element names and resource keys are what the `.act` cases and the describe
  tools address: keep them stable once a case exists.

---

## 7. Platform facts (seen on 8.3, ids in `get_recipe("platform-facts")`)

- Control ids in Classic are `{Schema}{DiffName}{Control}-el`, labels `{Schema}{Name}Label`; a `CheckBoxEdit` is a
  hidden input; a value commits on focus out; a DCM stage click saves the record; toolbar buttons are reliable by
  `[data-item-marker="<Name>Button"]`, the id form is not always rendered; a zero-width field is in the DOM but
  invisible; a dirty card hides `CloseButton`; a lookup searches on `keyup` and Enter opens the selection window;
  tabs are `li[data-item-index]` with gaps for hidden tabs (P-7).
- Calling a Classic page's `init()` again from a `Terrasoft.ServerChannel` handler duplicates its sandbox and
  channel subscriptions (P-6.3, P-6.4).
- `sdk.Model.load({primaryColumnValue})` does not filter: filter by Id through a `FilterGroup` (P-8.1);
  `Model.create('<Entity>')` + `load({attributes})` returns plain objects keyed by attribute (P-C1).
- A designer list page keeps `SectionContentWrapper`; an element inserted under it with `propertyName: items`
  renders full width without `layoutConfig` (P-C4).
- The devkit typings do not describe `model.load` options (P-C6).
- From a remote element without `$context`, `HandlerChainService.instance.process({type:
  'crt.UpdateRecordRequest', ...})` is the way to write a record (N-2); a record URL is
  `#Card/<FormPage>/edit/<Id>` (N-4).

---

## 8. Anti-patterns

| Do not | Do instead |
|---|---|
| A caption literal in `diff` or `values` (`"caption": "Save"`) | `Resources.Strings.X` / `#ResourceString(X)#` |
| `Terrasoft.showInformation`, `Terrasoft.Features`, `Terrasoft.createFilterGroup` inside a Freedom UI handler | `crt.NotificationRequest`, `sdk.FeatureService`, `sdk.FilterGroup` |
| `next.handle(request)` without `?.`, or `next` forgotten in a pre-processing handler | `return next?.handle(request);` |
| `new HandlerChainService()`, `$context.handlerChain.process` | `request.$context.executeRequest({...})` / `HandlerChainService.instance.process({..., $context})` |
| A GUID literal in a condition | The lookup value by code, a system setting, or a constant with a comment |
| `await new Promise(resolve => setTimeout(resolve, 500))` to wait for the page | React to the request that signals the state (`crt.HandleViewModelInitRequest`, attribute change) |
| `document.querySelector`, `Ext.get("...")`, jQuery in a schema | A binding, an attribute, a `crt.*` request, the control's API |
| `callback.call(scope, ...)` passed where a function is expected | Pass the function, `Ext.callback` inside |
| `self = this` closures | `scope` as the last argument, arrow functions |
| `console.log` / `window.console.warn` | `this.log(...)`, `this.warning(...)`; in TS `Logger.console` |
| `throw new Error("...")` in Classic code | The typed `Terrasoft.*Exception` with a resource message |
| `var` and `let` mixed in one handler; an undeclared `result = await ...` | `const` / `let` |
| `return next?.handle(request);;`, a trailing comma before `]/**SCHEMA_HANDLERS*/` | Clean syntax: the designer re-serializes these blocks |
| `MaskHelper.ShowBodyMask`, `LookupUtilities.Open` (UpperCamel legacy API) | `this.showBodyMask(...)`; `this.openLookup(config, callback, scope)` on a view model (`LookupUtilities.Open` stays in a module without one) |
| A DOM-level technique a custom control or modal needs (`Ext.get`, `self` for DOM handlers) | Allowed there, with one comment line saying why; nowhere else |
| A `#ResourceString(...)#` with no entry in the page's `resource.<culture>.xml` (`$Resources.Strings.null`) | Add the string before referencing it |

---

## 9. Review checklist

- [ ] Tabs, 120 columns, double quotes in schema JS; two spaces and single quotes in TS; `===`; `const`/`let`.
- [ ] Classic: `define` with used deps bound first, `resources` bound; blocks in the designer order, `diff` last,
      markers kept; attribute/message/diff keys quoted, config keys bare.
- [ ] Classic: `callParent` first (last in `destroy`); async overrides wrap the continuation; mixin methods called
      with `.call(this)`; subscriptions once, never a repeated `init`.
- [ ] Classic: callback + scope, `result.success` first in every ESQ callback, `Terrasoft.chain` for steps,
      `this.callService` with a `get...ServiceConfig`.
- [ ] Classic: JSDoc on every method - `@inheritdoc X#m` + `@override`, `@protected @virtual` on extension points,
      `@private` with `_name`, `@param {Type} name Description.`, `@return`; `@message` on every message.
- [ ] Freedom: the six blocks in order with their markers, JSON in the declarative blocks, no JSDoc, `sdk` as the
      devkit argument.
- [ ] Freedom: element names `Type_Purpose`, diff keys in order, captions through `#ResourceString(X)#`,
      bindings with `$` and the `crt.*` converter pipes, `clicked` as `{request, params}`.
- [ ] Freedom: attributes with `modelConfig.path` or `value`, validators as a keyed map, `PDS` and `<Name>DS`.
- [ ] Freedom: `async (request, next)`, `next?.handle` last for preparation and guards, first for post-processing,
      attribute filter before work, `await` on reads, assignment on writes, `$context.executeRequest` for chained
      requests.
- [ ] Freedom: custom requests, converters and validators `usr.<PascalCase>`; validators as a factory returning
      `null` or `{"usr.X": {message}}`; errors to the user through `crt.NotificationRequest` with a resource string.
- [ ] No DOM access, jQuery, `setTimeout` waits, `console.*`, GUID literals, caption literals, legacy `Terrasoft.*`
      calls in Freedom UI.
- [ ] Remote module: `usr-` selector and `usr.` type, decorators stacked, `@Input() @CrtInput() public`,
      `_injector` private readonly, `UPPER_SNAKE` request constants, `*.spec.ts`; mobile classes `Usr*` with
      `@CrtRequest`.
- [ ] Element names, request names and resource keys a test case addresses are unchanged.

## 10. clio's guidance alongside this guide

clio's MCP server ships the Freedom UI articles `page-modification` (and `-overview`, `-components`, `-containers`,
`-field-contract`, `-standard-components`, `-template-supplied-parts`), `page-schema-handlers`, `esq-filters-frontend`,
`business-rules`, read with `get-guidance name=<guide>`; `get-component-info` and `get-request-info` give the catalogue of
the site's exact version. Row by row: `dev/tasks/S40-clio-mcp-fifth-server/compare-pages.md` (2026-11-23). Until a
disagreement is settled on a site (S40-T05) this guide wins; these are the points to take from the articles now:

- **A rule before a handler.** Visibility, read-only, required by a field value, a filled state, the user, a role, a
  date or a system setting; setting or clearing a dependent field; restricting a lookup - all of it is a business rule
  (`rules.py`: `set-values`, `apply-static-filter`), not a `$Flag` attribute with a handler and not a
  `crt.LoadDataRequest` filter handler. A handler is for what no rule expresses (a computed value, a request to the
  server, a dialog). State actions of a rule are one-way: write the inverse rule too.
- **Markers survive, helpers do not.** An Interface Designer save keeps only the code inside the five markers; a helper
  or constant above `return` in the `define` factory is deleted by the next save. Keep page logic inside the handler
  array, shared code in a remote module (clio, docs; N-20 in the facts register).
- **Apply order of `viewConfigDiff`.** A `merge` or `move` on a component the same body inserts is discarded, `move` next
  to `remove` is dropped; `viewModelConfigDiff` / `modelConfigDiff` merges never create a missing path segment; an unknown
  `crt.*` type saves with `success: true` and renders a placeholder - check the type in `get-component-info` first.
- **Requests.** `crt.RunBusinessProcessRequest` needs `processRunType`, and its parameter keys are the process
  parameter codes (a wrong key is dropped silently); `crt.CreateRecordRequest` on an entity without a registered page
  fails only on click; `HandlerChainService.instance.process` without `scopes: [...request.scopes]` never reaches the
  page's own handlers (settled on 8.2.3 in S40-T05: `undefined` without scopes, the handler's value with them and
  through `executeRequest`; this guide keeps `executeRequest` inside handlers, 3.4). Imperatively from a handler,
  `crt.RunBusinessProcessRequest` ran without `processRunType` on 8.2.3 (`success: true`); the declarative button
  keeps it. `request.silent` is still set on 8.2.3: `true` for the change requests of the page load, `false` for a
  user's edit. A field binds its value through `control`; `"value"` on a `crt.Input` stops the page from opening.
- **Feed and attachments.** `crt.Feed` and `crt.FileList` are merged or inserted depending on the template; `FileList`
  needs its `AttachmentListDS`, the collection attribute, `columns` and `recordColumnName`, and the file entity is
  `<Entity>File` when it exists, `SysFile` with `RecordId` otherwise (settled on 8.2.3: a bare `FileList` stops the
  page from opening; the wired one showed the record's `SysFile` file - recipe `HowToUploadAndShowFiles`, P-8.7).
- **Serialized filters** (`Items_PredefinedFilter`, widgets): lookup equality is an `In` filter with an object value,
  dates are JSON-encoded strings, a backward reference carries `subFilters` inside the SubQuery.

What this guide keeps that the articles lack: the attribute `change` key, `events$` / `finish-load-model-attributes`,
forward-reference data-source attributes, `sdk.ComparisonType` casing, the selection filter converter chain, the 8.2.3
six-operator designer limit, `set-values` skipped on load of an existing record, P-8.1.
