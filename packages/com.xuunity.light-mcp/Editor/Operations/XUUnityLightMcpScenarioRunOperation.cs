using System;
using UnityEngine;
using XUUnity.LightMcp.Editor.Core;
using XUUnity.LightMcp.Editor.Helpers;

namespace XUUnity.LightMcp.Editor.Operations
{
    internal sealed class XUUnityLightMcpScenarioRunOperation : IXUUnityLightMcpOperation
    {
        public string OperationName => "unity.scenario.run";

        public XUUnityLightMcpResponse Execute(XUUnityLightMcpRequest request)
        {
            try
            {
                if (!XUUnityLightMcpScenarioProjectActionNormalizer.TryNormalizeArgsJson(
                        request.args_json,
                        out var argsJson,
                        out var errorCode,
                        out var errorMessage))
                {
                    return XUUnityLightMcpResponseWriter.Error(request.request_id, errorCode, errorMessage);
                }

                var args = string.IsNullOrWhiteSpace(argsJson)
                    ? new XUUnityLightMcpScenarioRunArgs()
                    : JsonUtility.FromJson<XUUnityLightMcpScenarioRunArgs>(argsJson) ?? new XUUnityLightMcpScenarioRunArgs();

                var validation = XUUnityLightMcpScenarioRunner.Validate(args.scenario);
                if (validation.status != "valid")
                {
                    return XUUnityLightMcpResponseWriter.Error(
                        request.request_id,
                        "scenario_invalid",
                        BuildValidationErrorMessage(validation));
                }

                if (XUUnityLightMcpScenarioRunner.HasActiveRun())
                {
                    return XUUnityLightMcpResponseWriter.Error(
                        request.request_id,
                        "scenario_already_running",
                        "Another Unity scenario is already running. Read it with unity.scenario.result before starting a new one.");
                }

                var payload = XUUnityLightMcpScenarioRunner.QueueRun(args.scenario);
                return XUUnityLightMcpResponseWriter.Success(
                    request.request_id,
                    OperationName,
                    JsonUtility.ToJson(payload)
                );
            }
            catch (Exception ex)
            {
                return XUUnityLightMcpResponseWriter.Error(request.request_id, "scenario_run_failed", ex.Message);
            }
        }

        public static string BuildValidationErrorMessage(XUUnityLightMcpScenarioValidatePayload validation)
        {
            var firstIssue = validation?.issues != null && validation.issues.Count > 0
                ? validation.issues[0]
                : null;
            if (firstIssue == null)
            {
                return "Scenario validation failed with no issue details.";
            }

            var stepContext = string.IsNullOrWhiteSpace(firstIssue.stepId)
                ? ""
                : $" at step '{firstIssue.stepId}'";
            var remainingCount = Math.Max(0, (validation?.error_count ?? 1) - 1);
            var remainingSummary = remainingCount > 0
                ? $" ({remainingCount} additional validation error(s); run unity.scenario.validate for the full list.)"
                : "";
            return $"Scenario validation failed{stepContext}: {firstIssue.code}: {firstIssue.message}{remainingSummary}";
        }
    }
}
