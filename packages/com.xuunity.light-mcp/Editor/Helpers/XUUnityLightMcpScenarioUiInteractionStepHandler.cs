using System;
using System.Diagnostics;
using UnityEngine;
using XUUnity.LightMcp.Editor.Core;
using static XUUnity.LightMcp.Editor.Helpers.XUUnityLightMcpNestedOperationClient;

namespace XUUnity.LightMcp.Editor.Helpers
{
    static class XUUnityLightMcpScenarioUiInteractionStepHandler
    {
        const string ClickOperation = "unity.ui.click";

        public static bool ProcessUiClickStep(
            XUUnityLightMcpScenarioStepDefinition step,
            XUUnityLightMcpScenarioStepResult stepResult)
        {
            var interactionId = (step.interactionId ?? "").Trim();
            if (string.IsNullOrEmpty(interactionId))
            {
                return Fail(stepResult, "missing_interaction_id",
                    $"{XUUnityLightMcpUiRead.InteractionStepKind} requires interactionId so a reference can require it by name.");
            }

            if (!step.approve)
            {
                return Fail(stepResult, "ui_click_approval_required",
                    $"{XUUnityLightMcpUiRead.InteractionStepKind} requires approve=true; delivering a click mutates runtime UI state.");
            }

            var args = new XUUnityLightMcpUiClickArgs
            {
                action = "click",
                approve = true,
                targetKind = string.IsNullOrWhiteSpace(step.targetKind) ? XUUnityLightMcpUiRead.TargetActiveScene : step.targetKind,
                targetValue = step.targetValue ?? "",
                sceneName = step.sceneName ?? "",
                includeDontDestroyOnLoad = step.includeDontDestroyOnLoad,
                selector = step.selector ?? new XUUnityLightMcpUiSelectorArgs()
            };

            var stopwatch = Stopwatch.StartNew();
            var response = ExecuteNestedOperation(ClickOperation, JsonUtility.ToJson(args));
            stopwatch.Stop();
            stepResult.duration_seconds = Math.Round(stopwatch.Elapsed.TotalSeconds, 6);

            if (response == null)
            {
                return Fail(stepResult, "null_nested_response", $"Nested operation '{ClickOperation}' returned no response.");
            }

            if (response.status != "ok")
            {
                return Fail(
                    stepResult,
                    response.error?.code ?? "ui_click_unavailable",
                    response.error?.message
                        ?? $"'{ClickOperation}' is unavailable; it ships in the uGUI satellite assembly and needs com.unity.ugui.");
            }

            var click = string.IsNullOrWhiteSpace(response.payload_json)
                ? new XUUnityLightMcpUiClickPayload()
                : JsonUtility.FromJson<XUUnityLightMcpUiClickPayload>(response.payload_json) ?? new XUUnityLightMcpUiClickPayload();

            var expectStateChange = step.expectStateChange;
            var payload = new XUUnityLightMcpUiInteractionStepPayload
            {
                expect_state_change = expectStateChange,
                click_status = click.status ?? "",
                click_error = click.refusal_code ?? "",
                ui_interaction = new XUUnityLightMcpUiInteractionBlock
                {
                    interaction_id = interactionId,
                    action = "click",
                    selector = args.selector,
                    delivered = click.delivered,
                    delivery_mechanism = click.delivery_mechanism ?? "",
                    target_path = click.target_node != null ? click.target_node.path : "",
                    target_component = click.target_component ?? "",
                    handler_path = click.delivered_to_path ?? "",
                    state_changed = click.state_changed,
                    before_signature = click.before_snapshot != null ? click.before_snapshot.signature : "",
                    after_signature = click.after_snapshot != null ? click.after_snapshot.signature : "",
                    playmode_state = click.playmode_state ?? "",
                    refusal_code = click.refusal_code ?? ""
                }
            };

            payload.met_expectations = click.delivered
                && string.IsNullOrEmpty(click.refusal_code)
                && (!expectStateChange || click.state_changed);

            stepResult.payload_json = JsonUtility.ToJson(payload);

            if (!payload.met_expectations)
            {
                stepResult.status = "failed";
                stepResult.error_code = string.IsNullOrEmpty(click.refusal_code)
                    ? (click.delivered ? "ui_interaction_no_state_change" : "ui_interaction_not_delivered")
                    : click.refusal_code;
                stepResult.error_message = DescribeFailure(interactionId, click, expectStateChange);
                return true;
            }

            stepResult.status = "passed";
            stepResult.outcome = "interaction_delivered";
            return true;
        }

        static string DescribeFailure(string interactionId, XUUnityLightMcpUiClickPayload click, bool expectStateChange)
        {
            if (!string.IsNullOrEmpty(click.refusal_code))
            {
                return $"Interaction '{interactionId}' was refused as {click.refusal_code} before delivery.";
            }

            if (!click.delivered)
            {
                return $"Interaction '{interactionId}' reached a handler but no handler consumed the click.";
            }

            return expectStateChange
                ? $"Interaction '{interactionId}' was delivered but the UI tree did not change; set expectStateChange=false if that is intended."
                : $"Interaction '{interactionId}' did not meet its expectations.";
        }

        static bool Fail(XUUnityLightMcpScenarioStepResult stepResult, string code, string message)
        {
            stepResult.status = "failed";
            stepResult.error_code = code;
            stepResult.error_message = message;
            return true;
        }
    }
}
