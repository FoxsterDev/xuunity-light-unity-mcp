using System;
using System.Globalization;
using System.IO;
using System.Diagnostics;
using UnityEditor;
using UnityEngine;

namespace XUUnity.LightMcp.Editor.Bridge
{
    internal static class XUUnityLightMcpEditorLogAnchors
    {
        const string PlayModeOffsetKey = "XUUnityLightMcp.EditorLogOffsetAtPlayModeStart";
        const string PlayModeStartedUtcKey = "XUUnityLightMcp.EditorLogPlayModeStartedUtc";
        const string PlayModeEditorPidKey = "XUUnityLightMcp.EditorLogPlayModeEditorPid";
        const string BridgeGenerationOffsetKey = "XUUnityLightMcp.EditorLogOffsetAtBridgeGenerationStart";
        const string BridgeGenerationKey = "XUUnityLightMcp.EditorLogOffsetBridgeGeneration";
        const string BridgeGenerationEditorPidKey = "XUUnityLightMcp.EditorLogBridgeGenerationEditorPid";

        public static long PlayModeStartOffsetBytes => ReadLong(PlayModeOffsetKey);

        public static string PlayModeStartedUtc => SessionState.GetString(PlayModeStartedUtcKey, "");

        public static int PlayModeStartEditorPid => (int)ReadLong(PlayModeEditorPidKey);

        public static long BridgeGenerationStartOffsetBytes => ReadLong(BridgeGenerationOffsetKey);

        public static int BridgeGenerationForOffset => (int)ReadLong(BridgeGenerationKey);

        public static int BridgeGenerationStartEditorPid => (int)ReadLong(BridgeGenerationEditorPidKey);

        public static void CapturePlayModeStart()
        {
            WriteLong(PlayModeOffsetKey, CurrentEditorLogLengthBytes());
            SessionState.SetString(PlayModeStartedUtcKey, DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"));
            WriteLong(PlayModeEditorPidKey, CurrentEditorPid());
        }

        public static void CaptureBridgeGenerationStart(int generation)
        {
            WriteLong(BridgeGenerationOffsetKey, CurrentEditorLogLengthBytes());
            WriteLong(BridgeGenerationKey, generation);
            WriteLong(BridgeGenerationEditorPidKey, CurrentEditorPid());
        }

        public static long CurrentEditorLogLengthBytes()
        {
            try
            {
                var path = Application.consoleLogPath;
                if (string.IsNullOrWhiteSpace(path))
                {
                    return 0L;
                }

                var info = new FileInfo(path);
                return info.Exists ? Math.Max(0L, info.Length) : 0L;
            }
            catch
            {
                return 0L;
            }
        }

        public static string CurrentEditorLogPath()
        {
            try
            {
                return Application.consoleLogPath ?? "";
            }
            catch
            {
                return "";
            }
        }

        static long ReadLong(string key)
        {
            var raw = SessionState.GetString(key, "");
            return long.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value)
                ? Math.Max(0L, value)
                : 0L;
        }

        static void WriteLong(string key, long value)
        {
            SessionState.SetString(key, Math.Max(0L, value).ToString(CultureInfo.InvariantCulture));
        }

        static int CurrentEditorPid()
        {
            using var process = Process.GetCurrentProcess();
            return process.Id;
        }
    }
}
