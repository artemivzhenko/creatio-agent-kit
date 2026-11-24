using System;
using System.Linq;
using System.Runtime.Serialization;
using System.ServiceModel;
using System.ServiceModel.Activation;
using System.ServiceModel.Web;
using Terrasoft.Core;
using Terrasoft.Core.Entities;
using Terrasoft.Web.Common;
using Terrasoft.Web.Http.Abstractions;

/// <summary>
/// Demonstrates how to serve a call that arrives with no Creatio session (an external system, a webhook) and an API key.
/// The first line gives the request an identity: SessionHelper.SpecifyWebOperationIdentity(HttpContextAccessor.GetInstance(),
/// SystemUserConnection.CurrentUser) - without it the platform code under the method has no user and fails on the first
/// query. Then the key is checked BEFORE any work (a system setting holds it; compare in constant time), and the work runs
/// on SystemUserConnection - the only connection there is, so every query is system-wide and the method itself must limit
/// what it returns. Answer a typed DTO and a status code, never an exception text. How the route is opened to calls
/// without a session is site configuration and not shown here; this recipe is the code side only.
/// </summary>
namespace Terrasoft.Configuration.UsrOrderStatusApi {

    [DataContract]
    public class UsrOrderStatusAnswer {
        [DataMember(Name = "found")] public bool Found { get; set; }
        [DataMember(Name = "status")] public string Status { get; set; }
    }

    [ServiceContract]
    [AspNetCompatibilityRequirements(RequirementsMode = AspNetCompatibilityRequirementsMode.Required)]
    public class UsrOrderStatusApi : BaseService {

        private const string ApiKeySetting = "UsrOrderStatusApiKey";

        private SystemUserConnection SystemConnection =>
            (SystemUserConnection)AppConnection.SystemUserConnection;

        // Constant-time compare: a plain string comparison leaks how many leading characters matched.
        private static bool SameKey(string a, string b) {
            if (a == null || b == null || a.Length != b.Length) {
                return false;
            }
            int diff = 0;
            for (int i = 0; i < a.Length; i++) {
                diff |= a[i] ^ b[i];
            }
            return diff == 0;
        }

        [OperationContract]
        [WebInvoke(Method = "POST", RequestFormat = WebMessageFormat.Json, ResponseFormat = WebMessageFormat.Json,
            BodyStyle = WebMessageBodyStyle.Wrapped)]
        public UsrOrderStatusAnswer GetStatus(string apiKey, string orderNumber) {
            // 1. An identity for this request: the system user (there is no session to take one from)
            SessionHelper.SpecifyWebOperationIdentity(HttpContextAccessor.GetInstance(), SystemConnection.CurrentUser);
            // 2. The key first; a wrong key learns nothing, not even whether the order exists
            string expected = Terrasoft.Core.Configuration.SysSettings.GetValue(SystemConnection, ApiKeySetting, string.Empty);
            if (string.IsNullOrEmpty(expected) || !SameKey(apiKey, expected)) {
                HttpContextAccessor.GetInstance().Response.StatusCode = 401;
                return new UsrOrderStatusAnswer { Found = false };
            }
            // 3. The work, narrowed to what this API may show: one order's status by its number
            var esq = new EntitySchemaQuery(SystemConnection.EntitySchemaManager, "UsrOrder");
            string status = esq.AddColumn("UsrStatus.Name").Name;
            esq.Filters.Add(esq.CreateFilterWithParameters(FilterComparisonType.Equal, "UsrNumber", orderNumber ?? string.Empty));
            Entity order = esq.GetEntityCollection(SystemConnection).FirstOrDefault();
            return order == null
                ? new UsrOrderStatusAnswer { Found = false }
                : new UsrOrderStatusAnswer { Found = true, Status = order.GetTypedColumnValue<string>(status) };
        }
    }
}
