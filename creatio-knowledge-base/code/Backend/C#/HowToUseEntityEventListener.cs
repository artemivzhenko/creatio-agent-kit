using System;
using System.Linq;
using Terrasoft.Core;
using Terrasoft.Core.Configuration;
using Terrasoft.Core.Entities;
using Terrasoft.Core.Entities.Events;

/// <summary>
/// Template for an EntityEventListener — handles insert, update, save, and delete lifecycle events
/// for any entity in Creatio.
/// Decorate the class with [EntityEventListener(SchemaName = "...")] to bind it to a specific entity.
/// Inherit from BaseEntityEventListener and override only the methods you need.
/// Before-events (OnInserting, OnUpdating, OnSaving, OnDeleting) run before the DB write —
/// use them for validation and data enrichment.
/// After-events (OnInserted, OnUpdated, OnSaved, OnDeleted) run after the DB write —
/// use them for side effects like sending notifications or updating related records.
/// Insert or update, and did this column change (OnSaving runs for both): entity.StoringState == StoringObjectState.New
/// is the insert; entity.GetChangedColumnValues().Any(c => c.Name == "UsrAmount") says the column changed in THIS save -
/// recompute a derived column only then. GetOldTypedColumnValue answers the value before the save, not whether it
/// changed (a save that rewrites the same value is not a change); see Events/HowToReadOldColumnValueInEventListener.
/// </summary>
namespace Terrasoft.Configuration {

    [EntityEventListener(SchemaName = "EntityName")]
    public class EntityNameEntityEventListener : BaseEntityEventListener {

        public override void OnInserting(object sender, EntityBeforeEventArgs e) {
            base.OnInserting(sender, e);
            var entity = (Entity)sender;
            var userConnection = entity.UserConnection;
            // custom logic before insert
        }

        public override void OnInserted(object sender, EntityAfterEventArgs e) {
            base.OnInserted(sender, e);
            var entity = (Entity)sender;
            var userConnection = entity.UserConnection;
            // custom logic after insert
        }

        public override void OnUpdating(object sender, EntityBeforeEventArgs e) {
            base.OnUpdating(sender, e);
            var entity = (Entity)sender;
            var userConnection = entity.UserConnection;
            // custom logic before update
        }

        public override void OnUpdated(object sender, EntityAfterEventArgs e) {
            base.OnUpdated(sender, e);
            var entity = (Entity)sender;
            var userConnection = entity.UserConnection;
            // custom logic after update
        }

        public override void OnSaving(object sender, EntityBeforeEventArgs e) {
            base.OnSaving(sender, e);
            var entity = (Entity)sender;
            var userConnection = entity.UserConnection;
            // custom logic before save (insert or update)
        }

        // Insert or update, and did this column change: recompute a derived column only when it must
        private static void RecomputeAmountWithTax(Entity entity) {
            bool isNew = entity.StoringState == StoringObjectState.New;
            bool amountChanged = entity.GetChangedColumnValues().Any(c => c.Name == "UsrAmount");
            if (isNew || amountChanged) {
                decimal amount = entity.GetTypedColumnValue<decimal>("UsrAmount");
                entity.SetColumnValue("UsrAmountWithTax", amount * 1.2m); // a made-up rate: the point is the guard
            }
        }

        public override void OnSaved(object sender, EntityAfterEventArgs e) {
            base.OnSaved(sender, e);
            var entity = (Entity)sender;
            var userConnection = entity.UserConnection;
            // custom logic after save (insert or update)
        }

        public override void OnDeleting(object sender, EntityBeforeEventArgs e) {
            base.OnDeleting(sender, e);
            var entity = (Entity)sender;
            var userConnection = entity.UserConnection;
            // custom logic before delete
        }

        public override void OnDeleted(object sender, EntityAfterEventArgs e) {
            base.OnDeleted(sender, e);
            var entity = (Entity)sender;
            var userConnection = entity.UserConnection;
            // custom logic after delete
        }

        public override void OnDeleteFailed(object sender, EntityErrorEventArgs e) {
            base.OnDeleteFailed(sender, e);
            var entity = (Entity)sender;
            // custom logic when delete fails
        }
    }
}
