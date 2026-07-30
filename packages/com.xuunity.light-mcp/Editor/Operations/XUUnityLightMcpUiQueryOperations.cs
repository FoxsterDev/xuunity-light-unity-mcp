using System;
using System.Collections.Generic;
using UnityEngine;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Helpers;

namespace XUUnity.LightMcp.Editor.Operations
{
    internal abstract class XUUnityLightMcpUiQueryOperationBase : IXUUnityLightMcpOperation
    {
        public abstract string OperationName { get; }

        protected virtual bool RequiresSelector => true;

        protected virtual bool RequiresSingleMatch => false;

        public XUUnityLightMcpResponse Execute(XUUnityLightMcpRequest request)
        {
            var args = string.IsNullOrWhiteSpace(request.args_json)
                ? new XUUnityLightMcpUiQueryArgs()
                : JsonUtility.FromJson<XUUnityLightMcpUiQueryArgs>(request.args_json) ?? new XUUnityLightMcpUiQueryArgs();
            args.selector ??= new XUUnityLightMcpUiSelectorArgs();

            var payload = new XUUnityLightMcpUiQueryPayload
            {
                operation = OperationName,
                project_root = XUUnityLightMcpFileIpcPaths.ProjectRootPath,
                generated_at_utc = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                selector = args.selector,
                component_detail_backends = XUUnityLightMcpUiComponentReaderRegistry.BackendIds()
            };

            if (RequiresSelector && XUUnityLightMcpUiSelectorMatcher.IsEmpty(args.selector))
            {
                payload.errors.Add(XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "ui_selector_invalid",
                    "A selector with at least one constraint is required.",
                    "Supported fields: name, type, path, pathContains, textEquals, textContains, requireVisible, requireInteractable."));
                payload.proof_class = XUUnityLightMcpUiRead.ProofError;
                return Respond(request, payload);
            }

            var result = XUUnityLightMcpUiTreeBuilder.Build(new XUUnityLightMcpUiTreeOptions
            {
                TargetKind = args.targetKind,
                TargetValue = args.targetValue,
                MaxDepth = args.maxDepth,
                MaxNodes = args.maxNodes,
                IncludeInactive = args.includeInactive,
                IncludeBounds = true,
                IncludeText = true
            });

            payload.target = result.Target;
            payload.scanned_node_count = result.Nodes.Count;
            payload.warnings = result.Warnings;
            payload.errors.AddRange(result.Errors);

            var matches = XUUnityLightMcpUiSelectorMatcher.Match(
                result.Nodes,
                args.selector,
                args.maxMatches,
                out var matchTruncated);

            payload.matches = matches;
            payload.match_count = matches.Count;
            payload.exists = matches.Count > 0;
            payload.ambiguous = matches.Count > 1;
            payload.truncated = matchTruncated || result.Truncated;
            payload.success = payload.errors.Count == 0;
            payload.proof_class = XUUnityLightMcpUiProofClass.Resolve(
                payload.success,
                result.Nodes.Count,
                payload.truncated,
                result.ComponentDetailsComplete);

            if (!result.ComponentDetailsComplete)
            {
                payload.warnings.Add(XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "ui_component_details_unavailable",
                    "No uGUI component reader is registered; text and interactable selectors cannot match.",
                    "Install com.unity.ugui so the optional uGUI module compiles."));
            }

            if (payload.ambiguous)
            {
                payload.warnings.Add(XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "selector_ambiguous",
                    $"Selector matched {matches.Count} nodes.",
                    "Narrow the selector or set allowMany when several matches are expected."));
            }

            if (RequiresSingleMatch && payload.success)
            {
                EnforceSingleMatch(args, payload);
            }

            if (payload.success)
            {
                Finalize(args, payload);
            }

            return Respond(request, payload);
        }

        protected virtual void Finalize(XUUnityLightMcpUiQueryArgs args, XUUnityLightMcpUiQueryPayload payload)
        {
        }

        static void EnforceSingleMatch(XUUnityLightMcpUiQueryArgs args, XUUnityLightMcpUiQueryPayload payload)
        {
            if (payload.match_count == 0)
            {
                payload.success = false;
                payload.proof_class = XUUnityLightMcpUiRead.ProofError;
                payload.errors.Add(XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "ui_node_not_found",
                    "The selector matched no node."));
                return;
            }

            if (payload.match_count > 1 && !args.allowMany)
            {
                payload.success = false;
                payload.proof_class = XUUnityLightMcpUiRead.ProofError;
                payload.errors.Add(XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "selector_ambiguous",
                    $"The selector matched {payload.match_count} nodes; set allowMany to accept several."));
            }
        }

        XUUnityLightMcpResponse Respond(XUUnityLightMcpRequest request, XUUnityLightMcpUiQueryPayload payload)
        {
            return XUUnityLightMcpResponseWriter.Success(
                request.request_id,
                OperationName,
                JsonUtility.ToJson(payload)
            );
        }
    }

    internal sealed class XUUnityLightMcpUiQueryOperation : XUUnityLightMcpUiQueryOperationBase
    {
        public override string OperationName => "unity.ui.query";
    }

    internal sealed class XUUnityLightMcpUiExistsOperation : XUUnityLightMcpUiQueryOperationBase
    {
        public override string OperationName => "unity.ui.exists";
    }

    internal sealed class XUUnityLightMcpUiGetTextOperation : XUUnityLightMcpUiQueryOperationBase
    {
        public override string OperationName => "unity.ui.get_text";

        protected override bool RequiresSingleMatch => true;

        protected override void Finalize(XUUnityLightMcpUiQueryArgs args, XUUnityLightMcpUiQueryPayload payload)
        {
            var texts = new List<string>();
            var missingText = new List<string>();
            foreach (var match in payload.matches)
            {
                if (match.has_text)
                {
                    texts.Add(match.text);
                    continue;
                }

                missingText.Add(match.path);
            }

            payload.texts = texts;
            if (texts.Count == 0)
            {
                payload.success = false;
                payload.proof_class = XUUnityLightMcpUiRead.ProofError;
                payload.errors.Add(XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "ui_text_unavailable",
                    "The matched node exposes no semantic text.",
                    string.Join(", ", missingText)));
                return;
            }

            payload.has_text = true;
            payload.text = texts[0];
        }
    }

    internal sealed class XUUnityLightMcpUiGetBoundsOperation : XUUnityLightMcpUiQueryOperationBase
    {
        public override string OperationName => "unity.ui.get_bounds";

        protected override bool RequiresSingleMatch => true;

        protected override void Finalize(XUUnityLightMcpUiQueryArgs args, XUUnityLightMcpUiQueryPayload payload)
        {
            foreach (var match in payload.matches)
            {
                if (!match.has_bounds)
                {
                    continue;
                }

                payload.has_bounds = true;
                payload.bounds = match.bounds;
                return;
            }

            payload.success = false;
            payload.proof_class = XUUnityLightMcpUiRead.ProofError;
            payload.errors.Add(XUUnityLightMcpUiTreeBuilder.Diagnostic(
                "ui_bounds_unavailable",
                "The matched node has no RectTransform, so it has no screen-space bounds."));
        }
    }
}
