using System;
using System.Globalization;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace XUUnity.LightMcp.Editor.Bridge
{
    internal static class XUUnityLightMcpEditorLogAnchors
    {
        const string PlayModeOffsetKey = "XUUnityLightMcp.EditorLogOffsetAtPlayModeStart";
        const string PlayModeStartedUtcKey = "XUUnityLightMcp.EditorLogPlayModeStartedUtc";
        const string BridgeGenerationOffsetKey = "XUUnityLightMcp.EditorLogOffsetAtBridgeGenerationStart";
        const string BridgeGenerationKey = "XUUnityLightMcp.EditorLogOffsetBridgeGeneration";

        public static long PlayModeStartOffsetBytes => ReadLong(PlayModeOffsetKey);

        public static string PlayModeStartedUtc => SessionState.GetString(PlayModeStartedUtcKey, "");

        public static long BridgeGenerationStartOffsetBytes => ReadLong(BridgeGenerationOffsetKey);

        public static int BridgeGenerationForOffset => (int)ReadLong(BridgeGenerationKey);

        public static void CapturePlayModeStart()
        {
            WriteLong(PlayModeOffsetKey, CurrentEditorLogLengthBytes());
            SessionState.SetString(PlayModeStartedUtcKey, DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"));
        }

        public static void CaptureBridgeGenerationStart(int generation)
        {
            WriteLong(BridgeGenerationOffsetKey, CurrentEditorLogLengthBytes());
            WriteLong(BridgeGenerationKey, generation);
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
    }
}
