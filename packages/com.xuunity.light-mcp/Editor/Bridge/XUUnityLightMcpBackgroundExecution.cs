using UnityEngine;

namespace XUUnity.LightMcp.Editor.Bridge
{
    internal static class XUUnityLightMcpBackgroundExecution
    {
        public static void EnsureEnabled()
        {
            if (!Application.runInBackground)
            {
                Application.runInBackground = true;
            }
        }
    }
}
