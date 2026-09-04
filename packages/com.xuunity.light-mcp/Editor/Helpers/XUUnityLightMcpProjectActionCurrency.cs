using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;
using XUUnity.LightMcp.Editor.Bridge;
using XUUnity.LightMcp.Editor.Core;

namespace XUUnity.LightMcp.Editor.Helpers
{
    internal static class XUUnityLightMcpProjectActionCurrency
    {
        static readonly HashSet<string> EditorInputExtensions = new(StringComparer.OrdinalIgnoreCase)
        {
            ".cs",
            ".asmdef",
            ".asmref",
            ".rsp",
        };

        public static XUUnityLightMcpProjectActionCurrencyPayload Capture(
            string actionId = "",
            string catalogPath = "",
            bool requiresFreshAssets = false,
            bool assetRefreshPerformed = false,
            string assetRefreshStepId = "")
        {
            XUUnityLightMcpBackgroundExecution.EnsureEnabled();
            var payload = new XUUnityLightMcpProjectActionCurrencyPayload
            {
                project_root = XUUnityLightMcpFileIpcPaths.ProjectRootPath,
                action_id = actionId ?? "",
                catalog_path = catalogPath ?? "",
                requires_fresh_assets = requiresFreshAssets,
                asset_refresh_performed = assetRefreshPerformed,
                asset_refresh_step_id = assetRefreshStepId ?? "",
                editor_domain_loaded_utc = XUUnityLightMcpBridgeRuntimeState.EditorDomainLoadedUtc,
                application_run_in_background = Application.runInBackground,
                native_autofocus_enabled = false,
            };

            var scanSucceeded = TryFindNewestEditorInput(
                out var newestPath,
                out var newestWriteUtc,
                out var inputCount,
                out var scanError);
            payload.newest_editor_input_path = newestPath;
            payload.newest_editor_input_write_utc = newestWriteUtc;
            payload.editor_input_count = inputCount;
            payload.editor_domain_currency = ClassifyEditorDomainCurrency(
                payload.editor_domain_loaded_utc,
                newestWriteUtc,
                scanSucceeded,
                out var editorDomainCurrent,
                out var currencyKnown,
                out var currencyReason);
            payload.editor_domain_current = editorDomainCurrent;
            payload.editor_domain_currency_known = currencyKnown;

            if (!scanSucceeded)
            {
                currencyReason = string.IsNullOrWhiteSpace(scanError)
                    ? "editor_input_scan_failed"
                    : $"editor_input_scan_failed:{scanError}";
            }

            var assetsCurrent = !requiresFreshAssets || assetRefreshPerformed;
            payload.safe_to_invoke = currencyKnown && editorDomainCurrent && assetsCurrent;
            if (!currencyKnown)
            {
                payload.reason = currencyReason;
                payload.recommended_next_action = "run_unity_project_refresh_before_invoking";
            }
            else if (!editorDomainCurrent)
            {
                payload.reason = currencyReason;
                payload.recommended_next_action = "run_unity_project_refresh_before_invoking";
            }
            else if (!assetsCurrent)
            {
                payload.reason = "catalog_requires_fresh_assets_without_completed_refresh";
                payload.recommended_next_action = "run_automatic_project_refresh_before_invoking";
            }
            else
            {
                payload.reason = currencyReason;
                payload.recommended_next_action = "none";
            }

            return payload;
        }

        public static string ClassifyEditorDomainCurrency(
            string editorDomainLoadedUtc,
            string newestEditorInputWriteUtc,
            bool scanSucceeded,
            out bool editorDomainCurrent,
            out bool currencyKnown,
            out string reason)
        {
            editorDomainCurrent = false;
            currencyKnown = false;
            reason = "";
            if (!scanSucceeded)
            {
                reason = "editor_input_scan_failed";
                return "unknown";
            }

            if (!TryParseUtc(editorDomainLoadedUtc, out var domainLoadedUtc))
            {
                reason = "editor_domain_load_time_unavailable";
                return "unknown";
            }

            if (string.IsNullOrWhiteSpace(newestEditorInputWriteUtc))
            {
                editorDomainCurrent = true;
                currencyKnown = true;
                reason = "no_editor_domain_inputs_under_assets";
                return "current";
            }

            if (!TryParseUtc(newestEditorInputWriteUtc, out var newestInputUtc))
            {
                reason = "newest_editor_input_time_invalid";
                return "unknown";
            }

            currencyKnown = true;
            editorDomainCurrent = newestInputUtc <= domainLoadedUtc;
            reason = editorDomainCurrent
                ? "editor_domain_loaded_after_newest_assets_input"
                : "assets_editor_input_newer_than_loaded_editor_domain";
            return editorDomainCurrent ? "current" : "stale";
        }

        static bool TryFindNewestEditorInput(
            out string newestPath,
            out string newestWriteUtc,
            out int inputCount,
            out string error)
        {
            newestPath = "";
            newestWriteUtc = "";
            inputCount = 0;
            error = "";
            var assetsRoot = Path.Combine(XUUnityLightMcpFileIpcPaths.ProjectRootPath, "Assets");
            if (!Directory.Exists(assetsRoot))
            {
                return true;
            }

            try
            {
                var newestUtc = DateTime.MinValue;
                foreach (var path in Directory.EnumerateFiles(assetsRoot, "*", SearchOption.AllDirectories))
                {
                    if (!EditorInputExtensions.Contains(Path.GetExtension(path)))
                    {
                        continue;
                    }

                    inputCount++;
                    var writeUtc = File.GetLastWriteTimeUtc(path);
                    if (writeUtc <= newestUtc)
                    {
                        continue;
                    }

                    newestUtc = writeUtc;
                    newestPath = MakeProjectRelative(path);
                }

                if (newestUtc != DateTime.MinValue)
                {
                    newestWriteUtc = newestUtc.ToString("O", CultureInfo.InvariantCulture);
                }

                return true;
            }
            catch (Exception ex)
            {
                error = ex.GetType().Name;
                return false;
            }
        }

        static string MakeProjectRelative(string path)
        {
            var projectRoot = XUUnityLightMcpFileIpcPaths.ProjectRootPath.TrimEnd(
                Path.DirectorySeparatorChar,
                Path.AltDirectorySeparatorChar);
            var prefix = projectRoot + Path.DirectorySeparatorChar;
            var relative = path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)
                ? path.Substring(prefix.Length)
                : path;
            return relative.Replace('\\', '/');
        }

        static bool TryParseUtc(string value, out DateTime utc)
        {
            return DateTime.TryParse(
                value,
                CultureInfo.InvariantCulture,
                DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal,
                out utc);
        }
    }
}
