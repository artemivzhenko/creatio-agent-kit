using System;
using Terrasoft.Core;
using Terrasoft.Core.Entities;
using Terrasoft.Messaging.Common;

/// <summary>
/// Demonstrates how to send a message to one user's browser session with MsgChannelManager, and why
/// MsgChannelUtilities.PostMessage reaches only the user the code runs as.
/// MsgChannelUtilities.PostMessage(userConnection, sender, text) posts to the channel of
/// userConnection.CurrentUser and, when that user is offline, only logs "Channel not found for user".
/// A process started from a Quartz job or a background ProcessExecutor runs as the job's user (Supervisor),
/// so a popup user task built on PostMessage reaches Supervisor and nobody else - a "to whom" parameter
/// that only goes into the message body is discarded by every other client.
/// To reach a given contact: their SysAdminUnit by ContactId -> MsgChannelManager.Instance.FindItemByUId(
/// sysAdminUnitId) -> channel.PostMessage(new SimpleMessage { Id, Body, Header.Sender }). No channel = offline:
/// always null-check. The "Sender" in the header is the message type key the frontend listens for.
/// A local build (net472) needs references to Terrasoft.Messaging.Common.dll,
/// Terrasoft.Messaging.Common.Standard.dll (SimpleMessage is type-forwarded there) and netstandard; without
/// them: CS1069 "forwarded to assembly 'Terrasoft.Messaging.Common.Standard'" and CS0103 'MsgChannelManager'.
/// Seen on 8.3 (source of MsgChannelUtilities.CrtBase.cs, a captured popup message, a local dotnet build).
/// For broadcasting to ALL connected users use MsgChannelUtilities.PostMessageToAll() - see HowToPostMessageToFrontend.
/// </summary>
class HowToPostMessageToCurrentUser {

    // 1. Send a message to the user the code runs as (in a job: the job's user, not the person who scheduled it)
    public void NotifyCurrentUser(UserConnection userConnection, string messageType, string body) {
        var channel = MsgChannelManager.Instance.FindItemByUId(userConnection.CurrentUser.Id);
        if (channel == null) {
            // No active browser session: the message cannot be delivered
            return;
        }
        var message = new SimpleMessage {
            Id     = Guid.NewGuid(),
            Body   = body,
            Header = { Sender = messageType }
        };
        channel.PostMessage(message);
    }

    // 2. Send a message to a specific user by their SysAdminUnit Id (the user's Id, not the contact's)
    public bool NotifyUserById(Guid sysAdminUnitId, string messageType, string body) {
        var channel = MsgChannelManager.Instance.FindItemByUId(sysAdminUnitId);
        if (channel == null) {
            return false;
        }
        channel.PostMessage(new SimpleMessage {
            Id     = Guid.NewGuid(),
            Body   = body,
            Header = { Sender = messageType }
        });
        return true;
    }

    // 3. Send a message to a contact: every user (SysAdminUnit) of that contact that has a channel
    public int NotifyContact(UserConnection userConnection, Guid contactId, string messageType, string body) {
        var esq = new EntitySchemaQuery(userConnection.EntitySchemaManager, "SysAdminUnit");
        esq.PrimaryQueryColumn.IsAlwaysSelect = true;
        esq.Filters.Add(esq.CreateFilterWithParameters(FilterComparisonType.Equal, "Contact", contactId));
        int sent = 0;
        foreach (var unit in esq.GetEntityCollection(userConnection)) {
            if (NotifyUserById(unit.PrimaryColumnValue, messageType, body)) {
                sent++;
            }
        }
        return sent;
    }
}
