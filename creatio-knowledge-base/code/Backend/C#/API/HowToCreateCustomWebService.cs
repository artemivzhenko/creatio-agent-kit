using System;
using System.ServiceModel;
using System.ServiceModel.Activation;
using System.ServiceModel.Web;
using Terrasoft.Core;
using Terrasoft.Core.Entities;
using Terrasoft.Web.Common;
using Terrasoft.Web.Common.ServiceRouting; // [DefaultServiceRoute], [SspServiceRoute]: CS0246 without it

/// <summary>
/// Pattern: minimal Creatio custom web service.
///
/// Inherit from BaseService — it exposes UserConnection without any constructor work.
/// Decorate with [ServiceContract] + [DefaultServiceRoute] + [AspNetCompatibilityRequirements].
///
/// Each endpoint method needs:
///   [OperationContract]
///   [WebInvoke(Method = "GET"|"POST", RequestFormat/ResponseFormat = WebMessageFormat.Json,
///              BodyStyle = WebMessageBodyStyle.Wrapped)]
///
/// The ...Namespace suffix is a convention, not a requirement: a service in plain Terrasoft.Configuration
/// is routed as well (8.2.3, S40-T05).
///
/// URL: /0/rest/<Service>/<Method> on .NET Framework (/rest/... on .NET). Settled on 8.2.3 (S40-T05):
/// a service answers there both from Files/cs of an assembly package (after push-pkg alone) and from a
/// source code schema (after compile-configuration); /0/ServiceModel/<Service>.svc/... answers neither (404/500).
///   GET /0/rest/UsrContactLookupService/GetContactIdByName?Name=John
///
/// POST body must be JSON-wrapped:  { "Name": "John" }
/// (BodyStyle.Wrapped adds an extra object layer — use BodyStyle.Bare for naked JSON)
/// </summary>
namespace Terrasoft.Configuration.UsrContactLookupServiceNamespace {

    [ServiceContract]
    [DefaultServiceRoute]
    [AspNetCompatibilityRequirements(RequirementsMode = AspNetCompatibilityRequirementsMode.Required)]
    public class UsrContactLookupService : BaseService {

        [OperationContract]
        [WebInvoke(Method = "GET",
            RequestFormat  = WebMessageFormat.Json,
            BodyStyle      = WebMessageBodyStyle.Wrapped,
            ResponseFormat = WebMessageFormat.Json)]
        public string GetContactIdByName(string name) {
            var esq = new EntitySchemaQuery(UserConnection.EntitySchemaManager, "Contact");
            var idCol = esq.AddColumn("Id");
            esq.AddColumn("Name");
            esq.Filters.Add(
                esq.CreateFilterWithParameters(FilterComparisonType.Equal, "Name", name));

            var entities = esq.GetEntityCollection(UserConnection);
            if (entities.Count == 0)
                return string.Empty;

            return entities[0].GetTypedColumnValue<Guid>(idCol.Name).ToString();
        }
    }
}
