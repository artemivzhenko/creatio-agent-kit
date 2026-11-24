using System.ServiceModel;
using System.ServiceModel.Activation;
using System.ServiceModel.Web;
using Terrasoft.Web.Common;
using Terrasoft.Web.Common.ServiceRouting; // [DefaultServiceRoute], [SspServiceRoute]: CS0246 without it

/// <summary>
/// Pattern: expose a custom web service to portal (SSP) users.
///
/// By default, custom services are only accessible to internal (non-portal) users.
/// Add [SspServiceRoute] alongside [DefaultServiceRoute] to enable portal-side access.
///
/// URL mapping:
///   Internal users  → /0/rest/MyPortalService/...   (settled on 8.2.3, S40-T05; .svc does not answer)
///   Portal (SSP)    → the ssp route of the same service (not exercised by the kit)
///
/// Both routes point to the same service class; Creatio enforces authentication
/// separately for each URL prefix.
///
/// The ...Namespace suffix is a convention, not a requirement: a service in plain Terrasoft.Configuration
/// is routed as well (8.2.3, S40-T05).
/// </summary>
namespace Terrasoft.Configuration.MyPortalServiceNamespace {

    [ServiceContract]
    [DefaultServiceRoute]
    [SspServiceRoute]
    [AspNetCompatibilityRequirements(RequirementsMode = AspNetCompatibilityRequirementsMode.Required)]
    public class MyPortalService : BaseService {

        [OperationContract]
        [WebInvoke(Method = "GET",
            RequestFormat  = WebMessageFormat.Json,
            BodyStyle      = WebMessageBodyStyle.Wrapped,
            ResponseFormat = WebMessageFormat.Json)]
        public string Ping() {
            return "ok";
        }
    }
}
