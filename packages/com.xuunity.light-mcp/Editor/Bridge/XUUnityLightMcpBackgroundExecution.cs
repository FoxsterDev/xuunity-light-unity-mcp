using UnityEditor;
using UnityEngine;

namespace XUUnity.LightMcp.Editor.Bridge
{
    internal static class XUUnityLightMcpBackgroundExecution
    {
        internal const string ManagedMode = "managed";
        internal const string ProjectOwnedMode = "project_owned";

        const string RestorePendingKey = "XUUnityLightMcp.BackgroundExecutionRestorePending";
        const string RestoreValueKey = "XUUnityLightMcp.BackgroundExecutionRestoreValue";

        static bool _resolvedThisDomain;
        static bool _applied;

        public static string Mode => _applied ? ManagedMode : ProjectOwnedMode;

        public static void ApplyIfConfigured()
        {
            if (_resolvedThisDomain)
            {
                return;
            }

            _resolvedThisDomain = true;
            if (!XUUnityLightMcpBridgeActivation.LoadConfig().background_execution_enabled)
            {
                Restore();
                return;
            }

            if (!SessionState.GetBool(RestorePendingKey, false))
            {
                SessionState.SetBool(RestoreValueKey, Application.runInBackground);
                SessionState.SetBool(RestorePendingKey, true);
            }

            _applied = true;
            if (!Application.runInBackground)
            {
                Application.runInBackground = true;
            }
        }

        public static void Restore()
        {
            _applied = false;
            if (!SessionState.GetBool(RestorePendingKey, false))
            {
                return;
            }

            var original = SessionState.GetBool(RestoreValueKey, Application.runInBackground);
            SessionState.EraseBool(RestorePendingKey);
            SessionState.EraseBool(RestoreValueKey);
            if (Application.runInBackground != original)
            {
                Application.runInBackground = original;
            }
        }
    }
}
