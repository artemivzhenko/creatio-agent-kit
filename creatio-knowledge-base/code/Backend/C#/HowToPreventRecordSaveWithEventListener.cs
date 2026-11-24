using System;
using Terrasoft.Common;
using Terrasoft.Core.Entities;
using Terrasoft.Core.Entities.Events;

/// <summary>
/// Demonstrates how to refuse a record save from an EntityEventListener with a validation message, not an exception.
/// Subscribe `entity.Validating` in OnSaving and add an `EntityValidationMessage` (text, `MassageType` - sic -, the
/// failing column) to `entity.ValidationMessages`: the platform runs the validation after OnSaving, together with its own
/// required-column check, and aborts the insert or update. Settled on 8.2.3 (S40-T05): the save is refused on every path,
/// OData answers 500 with the text in `error.innererror.message`, DataService (what a Freedom UI page saves through)
/// answers `success: false`, `responseStatus.ErrorCode` "ValidateException" and the text in `Message`, and the page shows
/// that text in a toast and stays unsaved. A thrown exception refuses the save the same way (ErrorCode is then the
/// exception's class), but it pre-empts the required-column check and breaks the style guide's rule against throwing for
/// an expected business outcome (4.2). The listener instance is reused within one operation, so the handler is static.
/// </summary>
namespace Terrasoft.Configuration {

    [EntityEventListener(SchemaName = "UsrMyEntity")]
    public class UsrMyEntityEventListener : BaseEntityEventListener {

        public const string AmountColumnName = "UsrAmount";
        public const decimal MaxAmount = 1000000m;
        public const string TooBigAmountMessage = "The amount must not exceed one million";

        // 1. Subscribe in OnSaving: it runs for both insert and update, before the platform validates.
        public override void OnSaving(object sender, EntityBeforeEventArgs e) {
            base.OnSaving(sender, e);
            var entity = (Entity)sender;
            entity.Validating += ValidateAmount;
        }

        // 2. Add a message instead of throwing; the column makes the message point at the field.
        private static void ValidateAmount(object sender, EntityValidationEventArgs e) {
            var entity = (Entity)sender;
            // A column nobody set is "not loaded": reading it throws instead of returning the default.
            if (!entity.IsColumnValueLoaded(AmountColumnName)) {
                return;
            }
            if (entity.GetTypedColumnValue<decimal>(AmountColumnName) > MaxAmount) {
                entity.ValidationMessages.Add(new EntityValidationMessage {
                    Text = TooBigAmountMessage,
                    MassageType = MessageType.Error,
                    Column = entity.Schema.Columns.GetByName(AmountColumnName)
                });
            }
        }
    }
}
