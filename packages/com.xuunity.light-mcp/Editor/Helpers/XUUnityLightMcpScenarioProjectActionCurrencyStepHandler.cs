using System;
using UnityEngine;
using XUUnity.LightMcp.Editor.Core;

namespace XUUnity.LightMcp.Editor.Helpers
{
    internal static class XUUnityLightMcpScenarioProjectActionCurrencyStepHandler
    {
        public static bool Process(
            XUUnityLightMcpScenarioRunState state,
            XUUnityLightMcpScenarioStepDefinition step,
            XUUnityLightMcpScenarioStepResult stepResult)
        {
            var refreshPerformed = ResolveRefreshPerformed(state, step);
            var payload = XUUnityLightMcpProjectActionCurrency.Capture(
                step.actionId,
                "",
                step.requiresFreshAssets,
                refreshPerformed,
                step.assetRefreshStepId);
            stepResult.payload_json = JsonUtility.ToJson(payload);
            if (payload.safe_to_invoke)
            {
                stepResult.status = "passed";
                stepResult.outcome = "project_action_currency_current";
                return true;
            }

            stepResult.status = "failed";
            stepResult.failure_class = "precondition";
            stepResult.outcome = "project_action_currency_blocked";
            if (!payload.editor_domain_currency_known)
            {
                stepResult.error_code = "editor_domain_currency_unknown";
            }
            else if (!payload.editor_domain_current)
            {
                stepResult.error_code = "editor_domain_stale";
            }
            else
            {
                stepResult.error_code = "fresh_assets_preflight_failed";
            }

            stepResult.error_message = payload.reason;
            return true;
        }

        static bool ResolveRefreshPerformed(
            XUUnityLightMcpScenarioRunState state,
            XUUnityLightMcpScenarioStepDefinition step)
        {
            if (!step.requiresFreshAssets)
            {
                return false;
            }

            if (state == null || string.IsNullOrWhiteSpace(step.assetRefreshStepId))
            {
                return false;
            }

            var refreshResult = XUUnityLightMcpScenarioScheduler.FindStepResult(state, step.assetRefreshStepId);
            if (refreshResult == null
                || !string.Equals(refreshResult.status, "passed", StringComparison.Ordinal)
                || string.IsNullOrWhiteSpace(refreshResult.payload_json))
            {
                return false;
            }

            try
            {
                var payload = JsonUtility.FromJson<XUUnityLightMcpProjectRefreshPayload>(refreshResult.payload_json);
                return payload != null && payload.asset_database_refreshed;
            }
            catch (Exception)
            {
                return false;
            }
        }
    }
}
