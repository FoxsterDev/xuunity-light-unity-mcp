using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;
using XUUnity.LightMcp.Editor.Core;

namespace XUUnity.LightMcp.Editor.Helpers
{
    internal sealed class XUUnityLightMcpUiTreeOptions
    {
        public string TargetKind = XUUnityLightMcpUiRead.TargetActiveScene;
        public string TargetValue = "";
        public int MaxDepth = XUUnityLightMcpUiRead.DefaultMaxDepth;
        public int MaxNodes = XUUnityLightMcpUiRead.DefaultMaxNodes;
        public bool IncludeInactive;
        public bool IncludeBounds = true;
        public bool IncludeText = true;
    }

    internal sealed class XUUnityLightMcpUiTreeResult
    {
        public XUUnityLightMcpUiTargetInfo Target = new();
        public List<XUUnityLightMcpUiNode> Nodes = new();
        public List<string> RootPaths = new();
        public List<XUUnityLightMcpUiDiagnostic> Warnings = new();
        public List<XUUnityLightMcpUiDiagnostic> Errors = new();
        public bool Truncated;
        public string TruncationReason = "";
        public bool ComponentDetailsComplete = true;
    }

    internal static class XUUnityLightMcpUiTreeBuilder
    {
        static readonly Vector3[] WorldCorners = new Vector3[4];

        public static XUUnityLightMcpUiTreeResult Build(XUUnityLightMcpUiTreeOptions options)
        {
            var result = new XUUnityLightMcpUiTreeResult();
            var effective = options ?? new XUUnityLightMcpUiTreeOptions();
            var maxDepth = Math.Max(1, effective.MaxDepth);
            var maxNodes = Math.Max(1, effective.MaxNodes);

            result.Target.kind = string.IsNullOrWhiteSpace(effective.TargetKind)
                ? XUUnityLightMcpUiRead.TargetActiveScene
                : effective.TargetKind.Trim();
            result.Target.requested_value = effective.TargetValue ?? "";
            result.Target.backend = XUUnityLightMcpUiRead.BackendUgui;
            result.Target.backend_status = XUUnityLightMcpUiComponentReaderRegistry.HasReaders
                ? "component_details_available"
                : "transform_only";
            result.Target.capture_width = Screen.width;
            result.Target.capture_height = Screen.height;

            var roots = ResolveRoots(result, effective);
            result.Target.resolved_root_count = roots.Count;
            if (roots.Count == 0)
            {
                return result;
            }

            for (var i = 0; i < roots.Count; i++)
            {
                var root = roots[i];
                if (root == null)
                {
                    continue;
                }

                var rootPath = BuildPath(root.transform);
                result.RootPaths.Add(rootPath);
                Traverse(
                    root.transform,
                    rootPath,
                    "",
                    0,
                    i,
                    maxDepth,
                    maxNodes,
                    effective,
                    result);

                if (result.Truncated)
                {
                    break;
                }
            }

            return result;
        }

        static List<GameObject> ResolveRoots(XUUnityLightMcpUiTreeResult result, XUUnityLightMcpUiTreeOptions options)
        {
            var kind = result.Target.kind;
            var value = (options.TargetValue ?? "").Trim();

            if (string.Equals(kind, XUUnityLightMcpUiRead.TargetGameObjectPath, StringComparison.Ordinal))
            {
                var found = GameObject.Find(value);
                if (found == null)
                {
                    result.Errors.Add(Diagnostic("ui_target_not_found", $"No GameObject at path '{value}'."));
                    return new List<GameObject>();
                }

                CaptureSceneInfo(result, found.scene);
                return new List<GameObject> { found };
            }

            if (string.Equals(kind, XUUnityLightMcpUiRead.TargetGameObjectName, StringComparison.Ordinal))
            {
                return ResolveByName(result, value, options.IncludeInactive);
            }

            if (string.Equals(kind, XUUnityLightMcpUiRead.TargetPrefabAsset, StringComparison.Ordinal))
            {
                result.Errors.Add(Diagnostic(
                    "ui_target_not_found",
                    "Prefab targets are served by unity.prefab.snapshot, not the scene UI tree."));
                return new List<GameObject>();
            }

            return ResolveActiveSceneCanvases(result, options.IncludeInactive);
        }

        static List<GameObject> ResolveByName(
            XUUnityLightMcpUiTreeResult result,
            string value,
            bool includeInactive)
        {
            var matches = new List<GameObject>();
            var scene = SceneManager.GetActiveScene();
            CaptureSceneInfo(result, scene);
            if (!scene.IsValid())
            {
                result.Errors.Add(Diagnostic("ui_target_not_found", "No valid active scene."));
                return matches;
            }

            foreach (var root in scene.GetRootGameObjects())
            {
                CollectByName(root.transform, value, includeInactive, matches);
            }

            if (matches.Count == 0)
            {
                result.Errors.Add(Diagnostic("ui_target_not_found", $"No GameObject named '{value}'."));
                return matches;
            }

            if (matches.Count > 1)
            {
                result.Target.ambiguous = true;
                result.Warnings.Add(Diagnostic(
                    "ui_target_ambiguous",
                    $"GameObject name '{value}' matched {matches.Count} objects.",
                    "Prefer targetKind=game_object_path for a unique target."));
            }

            return matches;
        }

        static void CollectByName(Transform transform, string value, bool includeInactive, List<GameObject> matches)
        {
            if (transform == null)
            {
                return;
            }

            if (!includeInactive && !transform.gameObject.activeInHierarchy)
            {
                return;
            }

            if (string.Equals(transform.gameObject.name, value, StringComparison.Ordinal))
            {
                matches.Add(transform.gameObject);
            }

            for (var i = 0; i < transform.childCount; i++)
            {
                CollectByName(transform.GetChild(i), value, includeInactive, matches);
            }
        }

        static List<GameObject> ResolveActiveSceneCanvases(XUUnityLightMcpUiTreeResult result, bool includeInactive)
        {
            var roots = new List<GameObject>();
            var scene = SceneManager.GetActiveScene();
            CaptureSceneInfo(result, scene);
            if (!scene.IsValid())
            {
                result.Errors.Add(Diagnostic("ui_target_not_found", "No valid active scene."));
                return roots;
            }

            foreach (var root in scene.GetRootGameObjects())
            {
                var canvases = root.GetComponentsInChildren<Canvas>(true);
                foreach (var canvas in canvases)
                {
                    if (canvas == null || !canvas.isRootCanvas)
                    {
                        continue;
                    }

                    if (!includeInactive && !canvas.gameObject.activeInHierarchy)
                    {
                        continue;
                    }

                    roots.Add(canvas.gameObject);
                }
            }

            if (roots.Count == 0)
            {
                result.Warnings.Add(Diagnostic(
                    "ui_snapshot_empty",
                    "The active scene has no root Canvas.",
                    "uGUI is the only supported backend in this slice."));
            }

            return roots;
        }

        static void CaptureSceneInfo(XUUnityLightMcpUiTreeResult result, Scene scene)
        {
            if (!scene.IsValid())
            {
                return;
            }

            result.Target.scene_name = scene.name ?? "";
            result.Target.scene_path = scene.path ?? "";
        }

        public static void Traverse(
            Transform transform,
            string path,
            string parentPath,
            int depth,
            int siblingIndex,
            int maxDepth,
            int maxNodes,
            XUUnityLightMcpUiTreeOptions options,
            XUUnityLightMcpUiTreeResult result)
        {
            if (transform == null)
            {
                return;
            }

            var gameObject = transform.gameObject;
            if (!options.IncludeInactive && !gameObject.activeInHierarchy)
            {
                return;
            }

            if (result.Nodes.Count >= maxNodes)
            {
                result.Truncated = true;
                result.TruncationReason = "max_nodes_reached";
                return;
            }

            var node = BuildNode(transform, path, parentPath, depth, siblingIndex, options, result);
            result.Nodes.Add(node);

            if (depth + 1 > maxDepth - 1)
            {
                if (transform.childCount > 0)
                {
                    node.children_truncated = true;
                    result.Truncated = true;
                    result.TruncationReason = string.IsNullOrEmpty(result.TruncationReason)
                        ? "max_depth_reached"
                        : result.TruncationReason;
                }

                return;
            }

            for (var i = 0; i < transform.childCount; i++)
            {
                var child = transform.GetChild(i);
                if (child == null)
                {
                    continue;
                }

                Traverse(
                    child,
                    path + "/" + SanitizeSegment(child.gameObject.name),
                    path,
                    depth + 1,
                    i,
                    maxDepth,
                    maxNodes,
                    options,
                    result);

                if (result.Truncated && result.Nodes.Count >= maxNodes)
                {
                    node.children_truncated = true;
                    return;
                }
            }
        }

        static XUUnityLightMcpUiNode BuildNode(
            Transform transform,
            string path,
            string parentPath,
            int depth,
            int siblingIndex,
            XUUnityLightMcpUiTreeOptions options,
            XUUnityLightMcpUiTreeResult result)
        {
            var gameObject = transform.gameObject;
            var node = new XUUnityLightMcpUiNode
            {
                node_id = XUUnityLightMcpUiRead.BackendUgui + ":" + path,
                path = path,
                parent_path = parentPath,
                depth = depth,
                sibling_index = siblingIndex,
                child_count = transform.childCount,
                name = gameObject.name ?? "",
                type = transform is RectTransform ? "RectTransform" : "Transform",
                active_self = gameObject.activeSelf,
                active_in_hierarchy = gameObject.activeInHierarchy,
                render_order = siblingIndex
            };

            ApplyCanvasContext(transform, node);
            ApplyAlphaAndRaycasts(transform, node);
            if (options.IncludeBounds && transform is RectTransform rectTransform)
            {
                ApplyBounds(rectTransform, node);
            }

            node.visible = node.active_in_hierarchy && node.effective_alpha > 0f;

            var components = gameObject.GetComponents<Component>();
            var missingComponentCount = 0;
            foreach (var component in components)
            {
                if (component == null)
                {
                    missingComponentCount++;
                    node.components.Add("<missing script>");
                    continue;
                }

                var typeName = component.GetType().Name;
                node.components.Add(typeName);
                if (!options.IncludeText && IsTextLikeName(typeName))
                {
                    continue;
                }

                if (XUUnityLightMcpUiComponentReaderRegistry.Describe(component, node))
                {
                    node.component_details_complete = true;
                }
            }

            if (missingComponentCount > 0)
            {
                result.Warnings.Add(Diagnostic(
                    "ui_missing_script_component",
                    $"'{path}' has {missingComponentCount} missing script component(s).",
                    "Run unity.prefab.validate on the owning prefab for the typed defect."));
            }

            if (!XUUnityLightMcpUiComponentReaderRegistry.HasReaders)
            {
                result.ComponentDetailsComplete = false;
            }

            return node;
        }

        static bool IsTextLikeName(string typeName)
        {
            return typeName.IndexOf("Text", StringComparison.Ordinal) >= 0;
        }

        static void ApplyCanvasContext(Transform transform, XUUnityLightMcpUiNode node)
        {
            var canvas = transform.GetComponentInParent<Canvas>();
            if (canvas == null)
            {
                return;
            }

            node.canvas_path = BuildPath(canvas.transform);
            var rootCanvas = canvas.isRootCanvas ? canvas : canvas.rootCanvas;
            node.canvas_sort_order = rootCanvas != null ? rootCanvas.sortingOrder : canvas.sortingOrder;
        }

        static void ApplyAlphaAndRaycasts(Transform transform, XUUnityLightMcpUiNode node)
        {
            var alpha = 1f;
            var blocksRaycasts = true;
            var interactableKnown = false;
            var interactable = true;
            var current = transform;

            while (current != null)
            {
                var group = current.GetComponent<CanvasGroup>();
                if (group != null)
                {
                    alpha *= group.alpha;
                    blocksRaycasts = blocksRaycasts && group.blocksRaycasts;
                    interactable = interactable && group.interactable;
                    interactableKnown = true;
                    if (group.ignoreParentGroups)
                    {
                        break;
                    }
                }

                current = current.parent;
            }

            node.effective_alpha = Mathf.Clamp01(alpha);
            node.blocks_raycasts = blocksRaycasts;
            if (interactableKnown && !interactable)
            {
                node.interactable = false;
                node.interactable_known = true;
            }
        }

        static void ApplyBounds(RectTransform rectTransform, XUUnityLightMcpUiNode node)
        {
            if (!TryScreenRect(rectTransform, out var rect))
            {
                return;
            }

            node.has_bounds = true;
            node.bounds = rect;
            var canvas = rectTransform.GetComponentInParent<Canvas>();
            node.bounds_space = canvas != null && canvas.renderMode == RenderMode.WorldSpace
                ? "world_projected_pixels"
                : "screen_pixels";
        }

        public static bool TryScreenRect(RectTransform rectTransform, out XUUnityLightMcpUiRect rect)
        {
            rect = new XUUnityLightMcpUiRect();
            if (rectTransform == null)
            {
                return false;
            }

            rectTransform.GetWorldCorners(WorldCorners);
            var canvas = rectTransform.GetComponentInParent<Canvas>();
            Camera camera = null;
            if (canvas != null && canvas.renderMode != RenderMode.ScreenSpaceOverlay)
            {
                camera = canvas.worldCamera;
            }

            var minX = float.MaxValue;
            var minY = float.MaxValue;
            var maxX = float.MinValue;
            var maxY = float.MinValue;
            for (var i = 0; i < WorldCorners.Length; i++)
            {
                var screenPoint = RectTransformUtility.WorldToScreenPoint(camera, WorldCorners[i]);
                minX = Mathf.Min(minX, screenPoint.x);
                minY = Mathf.Min(minY, screenPoint.y);
                maxX = Mathf.Max(maxX, screenPoint.x);
                maxY = Mathf.Max(maxY, screenPoint.y);
            }

            rect.x = Round(minX);
            rect.y = Round(minY);
            rect.width = Round(maxX - minX);
            rect.height = Round(maxY - minY);
            return true;
        }

        public static string BuildPath(Transform transform)
        {
            if (transform == null)
            {
                return "";
            }

            var segments = new List<string>();
            var current = transform;
            while (current != null)
            {
                segments.Add(SanitizeSegment(current.gameObject.name));
                current = current.parent;
            }

            segments.Reverse();
            return string.Join("/", segments);
        }

        public static string SanitizeSegment(string value)
        {
            var text = value ?? "";
            return text.Replace("/", "\\/");
        }

        public static XUUnityLightMcpUiDiagnostic Diagnostic(string code, string message, string detail = "")
        {
            return new XUUnityLightMcpUiDiagnostic
            {
                code = code ?? "",
                message = message ?? "",
                detail = detail ?? ""
            };
        }

        static float Round(float value)
        {
            return Mathf.Round(value * 100f) / 100f;
        }
    }
}
