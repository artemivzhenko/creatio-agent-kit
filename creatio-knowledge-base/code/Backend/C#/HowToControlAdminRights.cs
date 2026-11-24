using System;
using Terrasoft.Core;
using Terrasoft.Core.Entities;

/// <summary>
/// Demonstrates UseAdminRights — the switch that decides whether a query or a save checks the caller's rights, and the
/// related Entity helpers for creating records.
///
/// THE NAME READS BACKWARDS. EntitySchemaQuery and Entity default to UseAdminRights = true, and TRUE MEANS THE RIGHTS ARE
/// CHECKED ("use the administration of rights"): the query reads the schema only when the user may read it and adds the
/// record-rights condition for an object administrated by records; a save checks the operation and column rights. FALSE
/// SWITCHES ALL OF IT OFF - the query returns every row, the save writes whatever it is given. Read from the platform's
/// own code (Terrasoft.Core 8.2.3 and 8.3.2: EntitySchemaQuery.AddRightCondition returns at once when !UseAdminRights;
/// Entity checks GetIsEntitySchema...Allowed only when UseAdminRights), S42-T01 / N-27. An earlier form of this recipe
/// said the opposite.
///
///   esq.UseAdminRights = true;       // the default: the user sees only the rows they may see
///   esq.UseAdminRights = false;      // an elevation: every row, whoever asks - write why next to it
///
/// A user in the System administrators role sees every row either way: the rights condition is not built for them
/// (a probe on the test site counted a record with no right rows as 1 for Supervisor, both ways) - so an elevation bug
/// never shows when you test as Supervisor. Test a rights path as an ordinary user.
///
/// A related but different question is WHICH CONNECTION you run on:
///   UserConnection                      the caller, with their permissions
///   AppConnection.SystemUserConnection  the Supervisor context
/// See HowToUseSystemUserConnection.
///
/// CREATING A RECORD WITH DEFAULTS:
///   SetDefColumnValues()  fills the columns that have default values configured on the
///                         object - lookup defaults, current date, current user, and the
///                         process/system columns. Without it a record created in code
///                         differs from one created through the UI.
///   Save(false)           saves WITHOUT raising entity events. Use it to avoid triggering
///                         listeners when you are already inside one; Save() (or Save(true))
///                         raises them normally. Skipping events also skips validation done
///                         in listeners, so do not use it as a shortcut around a rule you
///                         find inconvenient.
///
/// CREATING AN ENTITY BY SCHEMA NAME, when the entity is only known at runtime:
///   UserConnection.EntitySchemaManager.GetInstanceByName(name).CreateEntity(userConnection)
/// </summary>
namespace Terrasoft.Configuration
{

	public class UsrEntityHelper
	{

		protected UserConnection UserConnection;

		public UsrEntityHelper(UserConnection userConnection) {
			UserConnection = userConnection;
		}

		/// <summary>
		/// Creates a record of any entity, with platform defaults applied, under the rights
		/// of the current user.
		/// </summary>
		public Guid CreateDefaultRecord(string entitySchemaName) {
			var entity = UserConnection.EntitySchemaManager
				.GetInstanceByName(entitySchemaName)
				.CreateEntity(UserConnection);

			// The default (true) checks the caller's rights: kept, said out loud.
			entity.UseAdminRights = true;

			// Apply the defaults configured on the object.
			entity.SetDefColumnValues();

			// false - do not raise entity events for this write.
			entity.Save(false);

			return entity.PrimaryColumnValue;
		}

		/// <summary>
		/// A read that must not show the user rows they cannot access: the default.
		/// </summary>
		public Entity GetFileEntity(Guid fileId) {
			var esq = new EntitySchemaQuery(UserConnection.EntitySchemaManager, "UsrApplicationFile");

			// Always select the primary column, even when it is not added explicitly.
			esq.PrimaryQueryColumn.IsAlwaysSelect = true;

			// true (the default) - the record-rights condition is added for this user.
			esq.UseAdminRights = true;

			esq.AddColumn("Name");
			esq.AddColumn("UsrApplication");

			return esq.GetEntity(UserConnection, fileId);
		}

		/// <summary>
		/// A deliberate elevation. The comment is the point: it tells the next reader that
		/// the rights were switched off on purpose.
		/// </summary>
		public void WriteAuditRow(Guid recordId, string action) {
			var entity = UserConnection.EntitySchemaManager
				.GetInstanceByName("UsrAuditLog")
				.CreateEntity(UserConnection);

			// Elevated on purpose: every user may append to the audit log, even though
			// nobody has write access to it directly.
			entity.UseAdminRights = false;

			entity.SetDefColumnValues();
			entity.SetColumnValue("UsrRecordId", recordId);
			entity.SetColumnValue("UsrAction", action);
			entity.Save(false);
		}

		/// <summary>
		/// Updating an existing record under the caller's rights.
		/// </summary>
		public bool UpdateRecord(string entitySchemaName, Guid recordId, string columnName, object value) {
			var entity = UserConnection.EntitySchemaManager
				.GetInstanceByName(entitySchemaName)
				.CreateEntity(UserConnection);

			entity.UseAdminRights = true;

			// FetchFromDB returns false when the record does not exist OR the user may not
			// see it - the two cases are indistinguishable by design.
			if (!entity.FetchFromDB(recordId)) {
				return false;
			}

			entity.SetColumnValue(columnName, value);
			// Save() raises entity events; use it when listeners should react.
			entity.Save();
			return true;
		}
	}
}
