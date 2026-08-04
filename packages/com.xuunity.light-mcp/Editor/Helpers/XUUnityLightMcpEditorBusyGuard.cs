using System;
using UnityEditor;

namespace XUUnity.LightMcp.Editor.Helpers
{
    internal sealed class XUUnityLightMcpEditorBusyException : InvalidOperationException
    {
        public XUUnityLightMcpEditorBusyException(string code, string message, string recommendedNextAction)
            : base(message)
        {
            Code = code ?? "";
            RecommendedNextAction = recommendedNextAction ?? "";
        }

        public string Code { get; }

        public string RecommendedNextAction { get; }
    }

    internal static class XUUnityLightMcpEditorBusyGuard
    {
        public const string EditorInPlayModeCode = "editor_in_play_mode";

        public static void ThrowIfBusy(string operationName)
        {
            var operation = string.IsNullOrWhiteSpace(operationName) ? "This operation" : operationName;

            if (EditorApplication.isPlayingOrWillChangePlaymode || EditorApplication.isPlaying)
            {
                throw new XUUnityLightMcpEditorBusyException(
                    EditorInPlayModeCode,
                    $"{operation} cannot run while the editor is in Play Mode. "
                    + "Exit Play Mode with unity.playmode.set action=stop, or run the closed-project batch lane instead. "
                    + $"isCompiling={EditorApplication.isCompiling}, "
                    + $"isPlayingOrWillChangePlaymode={EditorApplication.isPlayingOrWillChangePlaymode}, "
                    + $"isUpdating={EditorApplication.isUpdating}",
                    "exit_play_mode_or_use_batch_lane");
            }

            if (EditorApplication.isCompiling || EditorApplication.isUpdating)
            {
                throw new XUUnityLightMcpEditorBusyException(
                    "editor_busy",
                    $"Unity editor is busy. isCompiling={EditorApplication.isCompiling}, "
                    + $"isPlayingOrWillChangePlaymode={EditorApplication.isPlayingOrWillChangePlaymode}, "
                    + $"isUpdating={EditorApplication.isUpdating}",
                    "wait_for_editor_idle_then_retry");
            }
        }

        public static string ResolveErrorCode(Exception exception, string fallbackCode)
        {
            return exception is XUUnityLightMcpEditorBusyException busy ? busy.Code : fallbackCode;
        }
    }
}
