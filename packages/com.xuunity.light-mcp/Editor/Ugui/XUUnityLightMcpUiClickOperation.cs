using System;
using UnityEditor;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Helpers;

namespace XUUnity.LightMcp.Editor.Ugui
{
    internal sealed class XUUnityLightMcpUiClickOperation : IXUUnityLightMcpOperation
    {
        public const string RegisteredOperationName = "unity.ui.click";

        public string OperationName => RegisteredOperationName;

        public XUUnityLightMcpResponse Execute(XUUnityLightMcpRequest request)
        {
            var args = string.IsNullOrWhiteSpace(request.args_json)
                ? new XUUnityLightMcpUiClickArgs()
                : JsonUtility.FromJson<XUUnityLightMcpUiClickArgs>(request.args_json) ?? new XUUnityLightMcpUiClickArgs();
            args.selector ??= new XUUnityLightMcpUiSelectorArgs();

            var payload = new XUUnityLightMcpUiClickPayload
            {
                project_root = XUUnityLightMcpFileIpcPaths.ProjectRootPath,
                generated_at_utc = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                requested_action = (args.action ?? "").Trim().ToLowerInvariant(),
                selector = args.selector,
                playmode_state = CurrentPlayModeState()
            };

            if (!string.Equals(payload.requested_action, "click", StringComparison.Ordinal))
            {
                return Refuse(
                    request,
                    payload,
                    "ui_action_not_permitted",
                    "Only the explicit action 'click' is permitted by this operation.");
            }

            if (!args.approve)
            {
                return Refuse(
                    request,
                    payload,
                    "ui_click_approval_required",
                    "Set approve=true to deliver a real pointer click; this operation mutates runtime UI state.");
            }

            if (XUUnityLightMcpUiSelectorMatcher.IsEmpty(args.selector))
            {
                return Refuse(
                    request,
                    payload,
                    "ui_selector_invalid",
                    "A selector with at least one constraint is required.");
            }

            var before = XUUnityLightMcpUiTreeBuilder.Build(new XUUnityLightMcpUiTreeOptions
            {
                TargetKind = args.targetKind,
                TargetValue = args.targetValue,
                SceneName = args.sceneName,
                IncludeDontDestroyOnLoad = args.includeDontDestroyOnLoad,
                MaxDepth = args.maxDepth,
                MaxNodes = args.maxNodes,
                IncludeInactive = true,
                IncludeBounds = true,
                IncludeText = true
            });
            payload.before_snapshot = Summarize(before);
            payload.search_target = before.Target;
            payload.search_node_count = before.Nodes.Count;
            payload.search_max_depth = Math.Max(1, args.maxDepth);
            payload.search_max_nodes = Math.Max(1, args.maxNodes);
            payload.search_truncated = before.Truncated;
            payload.search_truncation_reason = before.TruncationReason;
            payload.warnings.AddRange(before.Warnings);

            foreach (var diagnostic in before.Errors)
            {
                if (string.Equals(diagnostic.code, "ui_target_out_of_scope", StringComparison.Ordinal))
                {
                    return Refuse(request, payload, diagnostic.code, $"{diagnostic.message} {diagnostic.detail}".Trim());
                }
            }

            // The root-canvas out-of-scope case arrives as a warning, not an error, so a click that dropped
            // warnings refused with a bare "matched no node" and told the operator nothing about where it lives.
            foreach (var diagnostic in before.Warnings)
            {
                if (string.Equals(diagnostic.code, "ui_target_out_of_scope", StringComparison.Ordinal))
                {
                    return Refuse(request, payload, diagnostic.code, $"{diagnostic.message} {diagnostic.detail}".Trim());
                }
            }

            var matches = XUUnityLightMcpUiSelectorMatcher.Match(before.Nodes, args.selector, 8, out _);
            if (before.Truncated)
            {
                payload.match_count = matches.Count;
                var matchEvidence = matches.Count == 0
                    ? "The selector matched no node in the scanned prefix, so absence is unproven."
                    : $"The selector matched {matches.Count} node(s) in the scanned prefix, so uniqueness is unproven.";
                var scopeGap = XUUnityLightMcpUiTreeBuilder.DescribeSearchedScope(before.Target);
                return Refuse(
                    request,
                    payload,
                    "ui_selector_search_truncated",
                    $"{matchEvidence} The search scanned {before.Nodes.Count} node(s) "
                    + $"with maxDepth={payload.search_max_depth} and maxNodes={payload.search_max_nodes} "
                    + $"and stopped because {before.TruncationReason}. {scopeGap} "
                    + "Narrow targetKind/targetValue or sceneName, or raise maxDepth/maxNodes, then retry.");
            }

            if (matches.Count == 0)
            {
                var scopeGap = XUUnityLightMcpUiTreeBuilder.DescribeSearchedScope(before.Target);
                return Refuse(
                    request,
                    payload,
                    "ui_node_not_found",
                    $"The selector matched no node. {scopeGap}".Trim());
            }

            if (matches.Count > 1)
            {
                payload.match_count = matches.Count;
                return Refuse(
                    request,
                    payload,
                    "selector_ambiguous",
                    $"The selector matched {matches.Count} nodes; a click target must be unique.");
            }

            var node = matches[0];
            payload.match_count = 1;
            payload.target_node = node;

            if (!node.visible)
            {
                return Refuse(
                    request,
                    payload,
                    "ui_target_not_visible",
                    "The target is hidden, so a click would not be reachable by a user.");
            }

            if (!node.interactable)
            {
                return Refuse(
                    request,
                    payload,
                    "ui_target_not_interactable",
                    "The target reports interactable=false; delivering a click would fake user reachability.");
            }

            if (!node.blocks_raycasts)
            {
                return Refuse(
                    request,
                    payload,
                    "ui_target_does_not_block_raycasts",
                    "The target's CanvasGroup does not block raycasts, so a real pointer would pass through it.");
            }

            var targetTransform = before.ResolveTransform(node);
            var targetObject = targetTransform != null ? targetTransform.gameObject : null;
            if (targetObject == null)
            {
                return Refuse(
                    request,
                    payload,
                    "ui_target_not_found",
                    $"The matched path '{node.path}' could not be resolved back to a live GameObject.");
            }

            var selectable = targetObject.GetComponent<Selectable>();
            payload.target_component = selectable != null ? selectable.GetType().Name : "";
            if (selectable != null && !selectable.IsInteractable())
            {
                return Refuse(
                    request,
                    payload,
                    "ui_target_not_interactable",
                    "The target Selectable is not interactable at delivery time.");
            }

            var eventSystem = EventSystem.current;
            payload.event_system_present = eventSystem != null;
            payload.event_system_scope = "eventsystem_current_at_delivery";
            var pointer = new PointerEventData(eventSystem)
            {
                button = PointerEventData.InputButton.Left,
                position = new Vector2(
                    node.bounds.x + node.bounds.width / 2f,
                    node.bounds.y + node.bounds.height / 2f)
            };

            var handler = ExecuteEvents.GetEventHandler<IPointerClickHandler>(targetObject);
            if (handler == null)
            {
                return Refuse(
                    request,
                    payload,
                    "ui_target_has_no_click_handler",
                    "No IPointerClickHandler is present on the target or its ancestors.");
            }

            payload.delivered_to_path = XUUnityLightMcpUiTreeBuilder.BuildPath(handler.transform);
            payload.delivered = ExecuteEvents.Execute(handler, pointer, ExecuteEvents.pointerClickHandler);
            payload.delivery_mechanism = "event_system_pointer_click_handler";

            var after = XUUnityLightMcpUiTreeBuilder.Build(new XUUnityLightMcpUiTreeOptions
            {
                TargetKind = args.targetKind,
                TargetValue = args.targetValue,
                SceneName = args.sceneName,
                IncludeDontDestroyOnLoad = args.includeDontDestroyOnLoad,
                MaxDepth = args.maxDepth,
                MaxNodes = args.maxNodes,
                IncludeInactive = true,
                IncludeBounds = true,
                IncludeText = true
            });
            payload.after_snapshot = Summarize(after);
            payload.state_changed = !string.Equals(
                payload.before_snapshot.signature,
                payload.after_snapshot.signature,
                StringComparison.Ordinal);
            payload.effective = payload.delivered && payload.state_changed;
            payload.no_observable_effect = payload.delivered && !payload.state_changed;

            payload.success = payload.effective;
            payload.status = payload.effective
                ? "effective"
                : payload.delivered
                    ? "delivered_no_observable_effect"
                    : "not_delivered";
            payload.proof_class = payload.effective
                ? XUUnityLightMcpUiRead.ProofSemanticTree
                : XUUnityLightMcpUiRead.ProofSemanticPartial;
            if (!payload.delivered)
            {
                payload.errors.Add(XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "ui_click_not_delivered",
                    "The event system accepted the target but no handler consumed the click."));
            }
            else if (payload.no_observable_effect)
            {
                payload.warnings.Add(XUUnityLightMcpUiTreeBuilder.Diagnostic(
                    "ui_click_no_state_change",
                    "The handler consumed the synthetic pointer event, but the UI tree did not change. "
                    + "A handler may reject synthetic input when it validates pointerCurrentRaycast identity, "
                    + "or the effect may only be visible in logs or non-UI state. Verify with a UI query, "
                    + "an anchored log assertion, or a project-defined hook that calls the production API."));
            }

            return Respond(request, payload);
        }

        static string CurrentPlayModeState()
        {
            if (!EditorApplication.isPlayingOrWillChangePlaymode && !EditorApplication.isPlaying)
            {
                return "edit";
            }

            return EditorApplication.isPaused ? "paused" : "playing";
        }

        static XUUnityLightMcpUiClickSnapshotRef Summarize(XUUnityLightMcpUiTreeResult result)
        {
            var summary = new XUUnityLightMcpUiClickSnapshotRef
            {
                node_count = result.Nodes.Count,
                truncated = result.Truncated,
                truncation_reason = result.TruncationReason
            };

            var builder = new System.Text.StringBuilder();
            foreach (var node in result.Nodes)
            {
                builder.Append(node.path);
                builder.Append('|');
                builder.Append(node.active_in_hierarchy ? '1' : '0');
                builder.Append(node.visible ? '1' : '0');
                builder.Append(node.interactable ? '1' : '0');
                builder.Append(node.text);
                builder.Append(';');
            }

            summary.signature = XUUnityLightMcpUiClickSnapshotRef.Hash(builder.ToString());
            return summary;
        }

        static XUUnityLightMcpResponse Refuse(
            XUUnityLightMcpRequest request,
            XUUnityLightMcpUiClickPayload payload,
            string code,
            string message)
        {
            payload.success = false;
            payload.delivered = false;
            payload.effective = false;
            payload.no_observable_effect = false;
            payload.status = "refused";
            payload.refusal_code = code;
            payload.proof_class = XUUnityLightMcpUiRead.ProofError;
            payload.errors.Add(XUUnityLightMcpUiTreeBuilder.Diagnostic(code, message));
            return Respond(request, payload);
        }

        static XUUnityLightMcpResponse Respond(
            XUUnityLightMcpRequest request,
            XUUnityLightMcpUiClickPayload payload)
        {
            return XUUnityLightMcpResponseWriter.Success(
                request.request_id,
                RegisteredOperationName,
                JsonUtility.ToJson(payload)
            );
        }
    }
}
