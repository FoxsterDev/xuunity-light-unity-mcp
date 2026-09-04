using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;
using XUUnity.LightMcp.Editor.Bridge;
using XUUnity.LightMcp.Editor.Core;

namespace XUUnity.LightMcp.Editor.Operations
{
    internal sealed class XUUnityLightMcpEdm4uResolveOperation : IXUUnityLightMcpOperation
    {
        static readonly string[] AndroidForceResolveMenuCandidates =
        {
            "Assets/External Dependency Manager/Android Resolver/Force Resolve",
            "Assets/External Dependency Manager/Android Resolver/Resolve",
            "Assets/Play Services Resolver/Android Resolver/Force Resolve",
            "Assets/Play Services Resolver/Android Resolver/Resolve"
        };

        static readonly string[] AndroidResolveMenuCandidates =
        {
            "Assets/External Dependency Manager/Android Resolver/Resolve",
            "Assets/External Dependency Manager/Android Resolver/Force Resolve",
            "Assets/Play Services Resolver/Android Resolver/Resolve",
            "Assets/Play Services Resolver/Android Resolver/Force Resolve"
        };

        static readonly string[] VersionHandlerMenuCandidates =
        {
            "Assets/External Dependency Manager/Version Handler/Update",
            "Assets/Play Services Resolver/Version Handler/Update"
        };

        public string OperationName => "unity.edm4u.resolve";

        public XUUnityLightMcpResponse Execute(XUUnityLightMcpRequest request)
        {
            var args = string.IsNullOrWhiteSpace(request.args_json)
                ? new XUUnityLightMcpEdm4uResolveArgs()
                : JsonUtility.FromJson<XUUnityLightMcpEdm4uResolveArgs>(request.args_json) ?? new XUUnityLightMcpEdm4uResolveArgs();

            try
            {
                var platform = NormalizePlatform(args.platform);
                var activeBuildTargetBefore = EditorUserBuildSettings.activeBuildTarget;
                if (!TryValidateBuildTargetPrecondition(
                        platform,
                        activeBuildTargetBefore,
                        out var preconditionErrorCode,
                        out var preconditionErrorMessage))
                {
                    return XUUnityLightMcpResponseWriter.Error(
                        request.request_id,
                        preconditionErrorCode,
                        preconditionErrorMessage);
                }

                if (string.Equals(platform, "android", StringComparison.Ordinal)
                    && !XUUnityLightMcpBuildTargetGetOperation.IsPlatformSupportLoaded(BuildTarget.Android))
                {
                    return XUUnityLightMcpResponseWriter.Error(
                        request.request_id,
                        "edm4u_android_support_missing",
                        "Android EDM4U resolve requires the Unity Android Build Support module, but it is not loaded.");
                }

                var candidates = ResolveMenuCandidates(args, platform);
                if (candidates.Count == 0)
                {
                    return XUUnityLightMcpResponseWriter.Error(
                        request.request_id,
                        "edm4u_platform_not_supported",
                        $"No EDM4U resolve menu candidates are defined for platform '{platform}'.");
                }

                var payload = new XUUnityLightMcpEdm4uResolvePayload
                {
                    project_root = XUUnityLightMcpFileIpcPaths.ProjectRootPath,
                    platform = platform,
                    force = args.force,
                    required_build_target = string.Equals(platform, "android", StringComparison.Ordinal)
                        ? BuildTarget.Android.ToString()
                        : "",
                    active_build_target_before = activeBuildTargetBefore.ToString(),
                    active_build_target_after = activeBuildTargetBefore.ToString(),
                    build_target_precondition = string.Equals(platform, "android", StringComparison.Ordinal)
                        ? "confirmed"
                        : "not_applicable",
                    target_support_loaded = !string.Equals(platform, "android", StringComparison.Ordinal)
                        || XUUnityLightMcpBuildTargetGetOperation.IsPlatformSupportLoaded(BuildTarget.Android),
                    request_completed_at_utc = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                    asset_refresh_before_requested = args.refreshBefore,
                    asset_refresh_after_requested = args.refreshAfter,
                    settle_request_id = request.request_id,
                };

                XUUnityLightMcpBridgeRuntimeState.BeginRefreshSettleTracking(request.request_id, true, false);

                if (args.refreshBefore)
                {
                    XUUnityLightMcpLifecycleMonitor.MarkAssetRefreshRequested();
                    AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);
                }

                foreach (var candidate in candidates)
                {
                    var menuPath = candidate ?? "";
                    if (string.IsNullOrWhiteSpace(menuPath))
                    {
                        continue;
                    }

                    var executed = EditorApplication.ExecuteMenuItem(menuPath);
                    payload.attempted_menu_items.Add(new XUUnityLightMcpMenuItemAttempt
                    {
                        menu_path = menuPath,
                        executed = executed,
                    });

                    if (!executed)
                    {
                        continue;
                    }

                    payload.executed_menu_path = menuPath;
                    payload.outcome = "resolve_requested";
                    XUUnityLightMcpBridgeRuntimeState.MarkPackageOperationStarted(
                        $"EDM4U.{platform}",
                        "resolve_menu_executed");
                    break;
                }

                if (string.IsNullOrWhiteSpace(payload.executed_menu_path))
                {
                    return XUUnityLightMcpResponseWriter.Error(
                        request.request_id,
                        "edm4u_menu_not_found",
                        $"No EDM4U menu item executed for platform '{platform}'.");
                }

                if (args.refreshAfter)
                {
                    XUUnityLightMcpLifecycleMonitor.MarkAssetRefreshRequested();
                    AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);
                }

                payload.editor_is_compiling_after_request = EditorApplication.isCompiling;
                payload.editor_is_updating_after_request = EditorApplication.isUpdating;
                payload.playmode_state_after_request = XUUnityLightMcpPlayModeStateOperation.ResolvePlayModeState();
                payload.settle_phase = XUUnityLightMcpBridgeRuntimeState.RefreshSettlePhase;
                payload.active_build_target_after = EditorUserBuildSettings.activeBuildTarget.ToString();

                return XUUnityLightMcpResponseWriter.Success(
                    request.request_id,
                    OperationName,
                    JsonUtility.ToJson(payload));
            }
            catch (Exception ex)
            {
                return XUUnityLightMcpResponseWriter.Error(request.request_id, "edm4u_resolve_failed", ex.Message);
            }
        }

        internal static bool TryValidateBuildTargetPrecondition(
            string platform,
            BuildTarget activeBuildTarget,
            out string errorCode,
            out string errorMessage)
        {
            errorCode = "";
            errorMessage = "";

            if (!string.Equals(NormalizePlatform(platform), "android", StringComparison.Ordinal)
                || activeBuildTarget == BuildTarget.Android)
            {
                return true;
            }

            errorCode = "edm4u_android_target_not_active";
            errorMessage =
                $"Android EDM4U resolve requires active BuildTarget.Android, but Unity reports '{activeBuildTarget}'. " +
                "Switch first with unity_build_target_switch (target Android) or request-build-target-switch --target Android, " +
                "wait for Unity to settle, then retry the resolve.";
            return false;
        }

        internal static string NormalizePlatform(string platform)
        {
            var value = string.IsNullOrWhiteSpace(platform)
                ? "android"
                : platform.Trim().ToLowerInvariant();

            return value switch
            {
                "android" => "android",
                "versionhandler" => "version_handler",
                "version-handler" => "version_handler",
                "version_handler" => "version_handler",
                _ => value,
            };
        }

        static List<string> ResolveMenuCandidates(XUUnityLightMcpEdm4uResolveArgs args, string platform)
        {
            var result = new List<string>();
            if (args.menuPathCandidates != null && args.menuPathCandidates.Length > 0)
            {
                foreach (var candidate in args.menuPathCandidates)
                {
                    if (!string.IsNullOrWhiteSpace(candidate))
                    {
                        result.Add(candidate.Trim());
                    }
                }

                return result;
            }

            var defaults = platform switch
            {
                "android" => args.force ? AndroidForceResolveMenuCandidates : AndroidResolveMenuCandidates,
                "version_handler" => VersionHandlerMenuCandidates,
                _ => Array.Empty<string>(),
            };

            result.AddRange(defaults);
            return result;
        }
    }
}
