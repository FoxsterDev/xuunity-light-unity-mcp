using UnityEngine;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Helpers;

namespace XUUnity.LightMcp.Editor.Operations
{
    internal sealed class XUUnityLightMcpProjectActionCurrencyOperation : IXUUnityLightMcpOperation
    {
        public const string RegisteredOperationName = "unity.project_action.currency";

        public string OperationName => RegisteredOperationName;

        public XUUnityLightMcpResponse Execute(XUUnityLightMcpRequest request)
        {
            var args = string.IsNullOrWhiteSpace(request.args_json)
                ? new XUUnityLightMcpProjectActionCurrencyArgs()
                : JsonUtility.FromJson<XUUnityLightMcpProjectActionCurrencyArgs>(request.args_json)
                    ?? new XUUnityLightMcpProjectActionCurrencyArgs();
            var actionId = (args.actionId ?? "").Trim();
            var catalogPath = (args.catalogPath ?? "").Trim();
            var requiresFreshAssets = false;
            var resolvedCatalogPath = catalogPath;

            if (!string.IsNullOrWhiteSpace(actionId))
            {
                if (!ProjectActionCatalogLoader.TryLoad(
                        catalogPath,
                        out var catalog,
                        out var errorCode,
                        out var errorMessage))
                {
                    return XUUnityLightMcpResponseWriter.Error(request.request_id, errorCode, errorMessage);
                }

                if (!catalog.TryResolve(actionId, out var action))
                {
                    return XUUnityLightMcpResponseWriter.Error(
                        request.request_id,
                        "unknown_project_action",
                        $"Project action '{actionId}' is not declared in project_actions.yaml.");
                }

                actionId = action.ActionId;
                requiresFreshAssets = action.RequiresFreshAssets;
                resolvedCatalogPath = catalog.CatalogPath;
            }

            var payload = XUUnityLightMcpProjectActionCurrency.Capture(
                actionId,
                resolvedCatalogPath,
                requiresFreshAssets);
            return XUUnityLightMcpResponseWriter.Success(
                request.request_id,
                OperationName,
                JsonUtility.ToJson(payload));
        }
    }
}
