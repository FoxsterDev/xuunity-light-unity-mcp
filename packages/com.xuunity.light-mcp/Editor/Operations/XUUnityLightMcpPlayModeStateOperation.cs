using UnityEditor;
using UnityEngine;
using XUUnity.LightMcp.Editor.Bridge;
using XUUnity.LightMcp.Editor.Core;

namespace XUUnity.LightMcp.Editor.Operations
{
    internal sealed class XUUnityLightMcpPlayModeStateOperation : IXUUnityLightMcpOperation
    {
        public string OperationName => "unity.playmode.state";

        public XUUnityLightMcpResponse Execute(XUUnityLightMcpRequest request)
        {
            var payload = BuildPayload();
            return XUUnityLightMcpResponseWriter.Success(
                request.request_id,
                OperationName,
                JsonUtility.ToJson(payload)
            );
        }

        internal static XUUnityLightMcpPlayModeStatePayload BuildPayload()
        {
            var playmodeState = ResolvePlayModeState();
            var payload = new XUUnityLightMcpPlayModeStatePayload
            {
                project_root = XUUnityLightMcpFileIpcPaths.ProjectRootPath,
                playmode_transition_pending = XUUnityLightMcpBridgeRuntimeState.PlayModeTransitionPending,
                playmode_transition_request_id = XUUnityLightMcpBridgeRuntimeState.PlayModeTransitionRequestId,
                playmode_transition_action = XUUnityLightMcpBridgeRuntimeState.PlayModeTransitionAction,
                playmode_transition_target_state = XUUnityLightMcpBridgeRuntimeState.PlayModeTransitionTargetState,
                playmode_transition_started_utc = XUUnityLightMcpBridgeRuntimeState.PlayModeTransitionStartedUtc,
                playmode_transition_completed_utc = XUUnityLightMcpBridgeRuntimeState.PlayModeTransitionCompletedUtc,
                playmode_transition_phase = XUUnityLightMcpBridgeRuntimeState.PlayModeTransitionPhase,
                is_playing = EditorApplication.isPlaying,
                is_paused = EditorApplication.isPaused,
                is_playing_or_will_change_playmode = EditorApplication.isPlayingOrWillChangePlaymode,
            };
            PopulateLivenessEvidence(payload, playmodeState);
            return payload;
        }

        internal static void PopulateLivenessEvidence(
            XUUnityLightMcpPlayModeLivenessEvidence evidence,
            string playmodeState = "")
        {
            if (evidence == null)
            {
                return;
            }

            var resolvedState = string.IsNullOrWhiteSpace(playmodeState)
                ? ResolvePlayModeState()
                : playmodeState;
            var liveness = XUUnityLightMcpPlayModeLivenessTracker.ResolveCurrentLiveness(resolvedState);
            var editorFocused = XUUnityLightMcpPlayModeLivenessTracker.EditorApplicationFocused;
            var warning = XUUnityLightMcpPlayModeLivenessTracker.ResolveWarning(liveness, editorFocused);

            evidence.playmode_state = resolvedState;
            evidence.playmode_frame_count = XUUnityLightMcpPlayModeLivenessTracker.CurrentFrameCount;
            evidence.playmode_frames_advanced_last_interval = XUUnityLightMcpPlayModeLivenessTracker.FramesAdvancedLastInterval;
            evidence.playmode_frame_sample_interval_seconds = XUUnityLightMcpPlayModeLivenessTracker.SampleIntervalSeconds;
            evidence.editor_application_focused = editorFocused;
            evidence.playmode_loop_liveness = liveness;
            evidence.playmode_liveness_warning = warning;
            evidence.playmode_liveness_remediation = XUUnityLightMcpPlayModeLivenessTracker.ResolveRemediation(warning);
            evidence.result_trust_class = ResolveLivenessTrustClass(resolvedState, liveness);
        }

        internal static string ResolveLivenessTrustClass(string playmodeState, string liveness)
        {
            if (!string.Equals(playmodeState, "playing", System.StringComparison.Ordinal))
            {
                return "editor_truth_confirmed";
            }

            return liveness switch
            {
                "advancing" => "playmode_advancing_confirmed",
                "throttled" => "playmode_throttled",
                _ => "playmode_liveness_unproven"
            };
        }

        internal static string ResolvePlayModeState()
        {
            if (EditorApplication.isPlaying)
            {
                return EditorApplication.isPaused ? "paused" : "playing";
            }

            return EditorApplication.isPlayingOrWillChangePlaymode ? "transitioning" : "edit";
        }
    }
}
