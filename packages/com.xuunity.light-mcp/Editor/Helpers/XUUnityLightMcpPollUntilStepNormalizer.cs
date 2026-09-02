using System;

namespace XUUnity.LightMcp.Editor.Helpers
{
    static class XUUnityLightMcpPollUntilStepNormalizer
    {
        public static bool TryNormalizeStepArray(
            LightJsonNode scenario,
            string arrayKey,
            out string errorCode,
            out string errorMessage)
        {
            errorCode = "";
            errorMessage = "";

            if (!scenario.TryGetArray(arrayKey, out var steps))
            {
                return true;
            }

            for (var i = 0; i < steps.Array.Count; i++)
            {
                var step = steps.Array[i];
                if (step.Kind != LightJsonKind.Object)
                {
                    continue;
                }

                var operation = step.GetString("kind");
                if (string.IsNullOrWhiteSpace(operation))
                {
                    operation = step.GetString("operation");
                    if (!string.IsNullOrWhiteSpace(operation))
                    {
                        step.Object["kind"] = LightJsonNode.String(operation);
                    }
                }

                if (string.Equals(operation, "project_defined_hook", StringComparison.Ordinal))
                {
                    if (!TryNormalizeProjectHookPayload(step, out errorCode, out errorMessage))
                    {
                        return false;
                    }
                    continue;
                }

                if (!string.Equals(operation, "project_defined_hook_poll_until", StringComparison.Ordinal))
                {
                    continue;
                }

                if (!TryPromoteObjectPayloadToJsonString(step, "startPayload", "startPayloadJson", out errorCode, out errorMessage)
                    || !TryPromoteObjectPayloadToJsonString(step, "pollPayload", "pollPayloadJson", out errorCode, out errorMessage))
                {
                    return false;
                }
            }

            return true;
        }

        static bool TryNormalizeProjectHookPayload(
            LightJsonNode step,
            out string errorCode,
            out string errorMessage)
        {
            errorCode = "";
            errorMessage = "";
            var hasPayload = step.Object.TryGetValue("payload", out var payload);
            var hasPayloadJson = step.Object.TryGetValue("payloadJson", out var payloadJson);
            var hasHookPayloadJson = step.Object.ContainsKey("hookPayloadJson");

            if ((hasPayload && (hasPayloadJson || hasHookPayloadJson)) || (hasPayloadJson && hasHookPayloadJson))
            {
                errorCode = "project_hook_payload_ambiguous";
                errorMessage = "project_defined_hook accepts one payload field; use hookPayloadJson (or object payload), not multiple payload fields.";
                return false;
            }

            if (hasPayload)
            {
                if (payload.Kind != LightJsonKind.Object)
                {
                    errorCode = "project_hook_payload_invalid";
                    errorMessage = "project_defined_hook payload must be a JSON object; use hookPayloadJson for encoded JSON.";
                    return false;
                }
                step.Object["hookPayloadJson"] = LightJsonNode.String(payload.ToJson());
                step.Object.Remove("payload");
            }
            else if (hasPayloadJson)
            {
                if (payloadJson.Kind != LightJsonKind.String)
                {
                    errorCode = "project_hook_payload_invalid";
                    errorMessage = "project_defined_hook payloadJson must be a string; prefer hookPayloadJson.";
                    return false;
                }
                step.Object["hookPayloadJson"] = payloadJson;
                step.Object.Remove("payloadJson");
            }
            return true;
        }

        static bool TryPromoteObjectPayloadToJsonString(
            LightJsonNode step,
            string objectKey,
            string jsonKey,
            out string errorCode,
            out string errorMessage)
        {
            errorCode = "";
            errorMessage = "";

            if (step.Object.ContainsKey(jsonKey) || !step.Object.TryGetValue(objectKey, out var payload))
            {
                return true;
            }

            if (payload.Kind != LightJsonKind.Object)
            {
                errorCode = $"poll_until_{objectKey}_invalid";
                errorMessage = $"project_defined_hook_poll_until {objectKey} must be a JSON object.";
                return false;
            }

            step.Object[jsonKey] = LightJsonNode.String(payload.ToJson());
            step.Object.Remove(objectKey);
            return true;
        }
    }
}
