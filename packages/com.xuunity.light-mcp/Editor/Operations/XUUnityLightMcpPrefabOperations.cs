using System;
using UnityEngine;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Helpers;

namespace XUUnity.LightMcp.Editor.Operations
{
    internal sealed class XUUnityLightMcpPrefabSnapshotOperation : IXUUnityLightMcpOperation
    {
        public string OperationName => "unity.prefab.snapshot";

        public XUUnityLightMcpResponse Execute(XUUnityLightMcpRequest request)
        {
            var args = string.IsNullOrWhiteSpace(request.args_json)
                ? new XUUnityLightMcpPrefabArgs()
                : JsonUtility.FromJson<XUUnityLightMcpPrefabArgs>(request.args_json) ?? new XUUnityLightMcpPrefabArgs();

            var payload = new XUUnityLightMcpUiTreePayload
            {
                operation = OperationName,
                project_root = XUUnityLightMcpFileIpcPaths.ProjectRootPath,
                generated_at_utc = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                max_depth = Math.Max(1, args.maxDepth),
                max_nodes = Math.Max(1, args.maxNodes),
                component_detail_backends = XUUnityLightMcpUiComponentReaderRegistry.BackendIds()
            };
            payload.target.kind = XUUnityLightMcpUiRead.TargetPrefabAsset;
            payload.target.requested_value = args.prefabPath ?? "";

            var loaded = XUUnityLightMcpPrefabInspector.Load(args.prefabPath);
            if (loaded.Error != null)
            {
                payload.errors.Add(loaded.Error);
                payload.proof_class = XUUnityLightMcpUiRead.ProofError;
                return Respond(request, payload);
            }

            payload.target.prefab_path = loaded.NormalizedPath;
            payload.target.resolved_root_count = 1;
            payload.target.backend = XUUnityLightMcpUiRead.BackendUgui;
            payload.target.backend_status = XUUnityLightMcpUiComponentReaderRegistry.HasReaders
                ? "component_details_available"
                : "transform_only";

            var options = new XUUnityLightMcpUiTreeOptions
            {
                TargetKind = XUUnityLightMcpUiRead.TargetPrefabAsset,
                TargetValue = loaded.NormalizedPath,
                MaxDepth = args.maxDepth,
                MaxNodes = args.maxNodes,
                IncludeInactive = args.includeInactive,
                IncludeBounds = args.includeBounds,
                IncludeText = args.includeText
            };

            var result = new XUUnityLightMcpUiTreeResult { Target = payload.target };
            var rootPath = XUUnityLightMcpUiTreeBuilder.BuildPath(loaded.Root.transform);
            result.RootPaths.Add(rootPath);
            XUUnityLightMcpUiTreeBuilder.Traverse(
                loaded.Root.transform,
                rootPath,
                "",
                0,
                0,
                Math.Max(1, args.maxDepth),
                Math.Max(1, args.maxNodes),
                options,
                result);

            payload.nodes = result.Nodes;
            payload.root_paths = result.RootPaths;
            payload.node_count = result.Nodes.Count;
            payload.truncated = result.Truncated;
            payload.truncation_reason = result.TruncationReason;
            payload.warnings = result.Warnings;
            payload.errors.AddRange(result.Errors);
            payload.success = payload.errors.Count == 0;
            payload.proof_class = XUUnityLightMcpUiProofClass.Resolve(
                payload.success,
                result.Nodes.Count,
                result.Truncated,
                result.ComponentDetailsComplete);

            if (args.includeBounds)
            {
                payload.warnings.Add(XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "prefab_bounds_are_not_screen_space",
                    "A prefab asset is not instantiated in a Canvas, so its bounds are layout-local, not screen pixels.",
                    "Use unity.ui.get_bounds against the live scene for screen-space geometry."));
            }

            return Respond(request, payload);
        }

        static XUUnityLightMcpResponse Respond(XUUnityLightMcpRequest request, XUUnityLightMcpUiTreePayload payload)
        {
            return XUUnityLightMcpResponseWriter.Success(
                request.request_id,
                "unity.prefab.snapshot",
                JsonUtility.ToJson(payload)
            );
        }
    }

    internal sealed class XUUnityLightMcpPrefabValidateOperation : IXUUnityLightMcpOperation
    {
        public string OperationName => "unity.prefab.validate";

        public XUUnityLightMcpResponse Execute(XUUnityLightMcpRequest request)
        {
            var args = string.IsNullOrWhiteSpace(request.args_json)
                ? new XUUnityLightMcpPrefabArgs()
                : JsonUtility.FromJson<XUUnityLightMcpPrefabArgs>(request.args_json) ?? new XUUnityLightMcpPrefabArgs();

            var payload = new XUUnityLightMcpPrefabValidatePayload
            {
                project_root = XUUnityLightMcpFileIpcPaths.ProjectRootPath,
                generated_at_utc = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                prefab_path = args.prefabPath ?? ""
            };

            var loaded = XUUnityLightMcpPrefabInspector.Load(args.prefabPath);
            if (loaded.Error != null)
            {
                payload.errors.Add(loaded.Error);
                payload.status = "blocked";
                payload.proof_class = XUUnityLightMcpUiRead.ProofError;
                payload.recommended_next_action = "supply_an_existing_project_relative_prefab_path";
                return Respond(request, payload);
            }

            payload.prefab_path = loaded.NormalizedPath;
            payload.prefab_guid = loaded.Guid;
            XUUnityLightMcpPrefabInspector.Inspect(loaded.Root, args.reportUnassignedReferences, payload);

            if (!XUUnityLightMcpUiComponentReaderRegistry.HasReaders)
            {
                payload.lanes_not_evaluated.Add("unresolved_font_or_material");
                payload.warnings.Add(XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "ui_component_details_unavailable",
                    "No uGUI component reader is registered; font and material resolution was not checked.",
                    "Install com.unity.ugui so the optional uGUI module compiles."));
            }

            payload.defect_types = XUUnityLightMcpPrefabInspector.DistinctDefectTypes(payload.defects);
            var errorCount = 0;
            foreach (var defect in payload.defects)
            {
                if (string.Equals(defect.severity, "error", StringComparison.Ordinal))
                {
                    errorCount++;
                }
            }

            payload.passed = errorCount == 0;
            payload.status = payload.passed ? "passed" : "failed";
            payload.success = true;
            payload.proof_class = payload.lanes_not_evaluated.Count > 0
                ? XUUnityLightMcpUiRead.ProofSemanticPartial
                : XUUnityLightMcpUiRead.ProofSemanticTree;
            payload.recommended_next_action = payload.passed
                ? "none"
                : "repair_the_reported_defects_before_entering_playmode";

            return Respond(request, payload);
        }

        static XUUnityLightMcpResponse Respond(
            XUUnityLightMcpRequest request,
            XUUnityLightMcpPrefabValidatePayload payload)
        {
            return XUUnityLightMcpResponseWriter.Success(
                request.request_id,
                "unity.prefab.validate",
                JsonUtility.ToJson(payload)
            );
        }
    }
}
