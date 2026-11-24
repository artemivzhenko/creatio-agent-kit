using System;
using System.IO;
using System.ServiceModel;
using System.ServiceModel.Activation;
using System.ServiceModel.Web;
using System.Text;
using Terrasoft.Common;
using Terrasoft.Web.Common;

/// <summary>
/// Demonstrates how to return a file (a download) from a configuration web service.
/// The method returns a Stream; the content type comes from MimeTypeDetector.GetMimeType(fileName) - on HasError fall
/// back to application/octet-stream - and Content-Disposition: attachment; filename="..." makes the browser save it.
/// The headers are set on the runtime's response object, and that object differs between the two runtimes: on .NET
/// Framework WebOperationContext.Current.OutgoingResponse, on .NET (Core) HttpContextAccessor.GetInstance().Response -
/// one source compiled for both carries #if NETFRAMEWORK / #else around those lines (a package built for one runtime only
/// may keep its branch). Set the headers before returning the stream. URL: /0/rest/UsrReportFileService/GetReport.
/// </summary>
namespace Terrasoft.Configuration.UsrReportFileService {

    [ServiceContract]
    [AspNetCompatibilityRequirements(RequirementsMode = AspNetCompatibilityRequirementsMode.Required)]
    public class UsrReportFileService : BaseService {

        private static string ContentTypeOf(string fileName) {
            MimeTypeResult mime = MimeTypeDetector.GetMimeType(fileName);
            return mime.HasError ? "application/octet-stream" : mime.Type;
        }

        private static void SetDownloadHeaders(string fileName, long length) {
            string disposition = "attachment; filename=\"" + fileName + "\"";
#if NETFRAMEWORK
            var response = WebOperationContext.Current.OutgoingResponse;
            response.ContentType = ContentTypeOf(fileName);
            response.Headers.Add("Content-Disposition", disposition);
            response.ContentLength = length;
#else
            var response = Terrasoft.Web.Http.Abstractions.HttpContextAccessor.GetInstance().Response;
            response.ContentType = ContentTypeOf(fileName);
            response.AddHeader("Content-Disposition", disposition);
#endif
        }

        [OperationContract]
        [WebGet(UriTemplate = "GetReport")]
        public Stream GetReport() {
            const string fileName = "UsrReport.csv";
            byte[] bytes = Encoding.UTF8.GetBytes("Number;Amount\r\nUSR-1;100\r\n");
            SetDownloadHeaders(fileName, bytes.Length);
            return new MemoryStream(bytes);
        }
    }
}
