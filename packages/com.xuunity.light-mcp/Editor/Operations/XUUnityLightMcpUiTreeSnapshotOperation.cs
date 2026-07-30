using System;
using UnityEngine;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Helpers;

namespace XUUnity.LightMcp.Editor.Operations
{
    internal sealed class XUUnityLightMcpUiTreeSnapshotOperation : IXUUnityLightMcpOperation
    {
        public string OperationName => "unity.ui.tree_snapshot";

        public XUUnityLightMcpResponse Execute(XUUnityLightMcpRequest request)
        {
            var args = string.IsNullOrWhiteSpace(request.args_json)
                ? new XUUnityLightMcpUiTreeArgs()
                : JsonUtility.FromJson<XUUnityLightMcpUiTreeArgs>(request.args_json) ?? new XUUnityLightMcpUiTreeArgs();

            var options = new XUUnityLightMcpUiTreeOptions
            {
                TargetKind = args.targetKind,
                TargetValue = args.targetValue,
                MaxDepth = args.maxDepth,
                MaxNodes = args.maxNodes,
                IncludeInactive = args.includeInactive,
                IncludeBounds = args.includeBounds,
                IncludeText = args.includeText
            };

            var result = XUUnityLightMcpUiTreeBuilder.Build(options);
            var payload = new XUUnityLightMcpUiTreePayload
            {
                operation = OperationName,
                project_root = XUUnityLightMcpFileIpcPaths.ProjectRootPath,
                generated_at_utc = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                target = result.Target,
                nodes = result.Nodes,
                root_paths = result.RootPaths,
                node_count = result.Nodes.Count,
                max_depth = Math.Max(1, args.maxDepth),
                max_nodes = Math.Max(1, args.maxNodes),
                truncated = result.Truncated,
                truncation_reason = result.TruncationReason,
                warnings = result.Warnings,
                errors = result.Errors
            };
            payload.component_detail_backends = XUUnityLightMcpUiComponentReaderRegistry.BackendIds();
            payload.success = result.Errors.Count == 0;
            payload.proof_class = XUUnityLightMcpUiProofClass.Resolve(
                payload.success,
                result.Nodes.Count,
                result.Truncated,
                result.ComponentDetailsComplete);

            if (!result.ComponentDetailsComplete)
            {
                payload.warnings.Add(XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "ui_component_details_unavailable",
                    "No uGUI component reader is registered; text, font, and interactable state are not reported.",
                    "Install com.unity.ugui so the optional uGUI module compiles."));
            }

            return XUUnityLightMcpResponseWriter.Success(
                request.request_id,
                OperationName,
                JsonUtility.ToJson(payload)
            );
        }
    }

    internal static class XUUnityLightMcpUiProofClass
    {
        public static string Resolve(bool success, int nodeCount, bool truncated, bool componentDetailsComplete)
        {
            if (!success)
            {
                return XUUnityLightMcpUiRead.ProofError;
            }

            if (nodeCount == 0)
            {
                return XUUnityLightMcpUiRead.ProofUnavailable;
            }

            return truncated || !componentDetailsComplete
                ? XUUnityLightMcpUiRead.ProofSemanticPartial
                : XUUnityLightMcpUiRead.ProofSemanticTree;
        }
    }
}
