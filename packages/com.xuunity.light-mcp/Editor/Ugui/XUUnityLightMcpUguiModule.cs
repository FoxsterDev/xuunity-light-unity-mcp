using System.Collections.Generic;
using UnityEditor;
using XUUnity.LightMcp.Editor.Core;

namespace XUUnity.LightMcp.Editor.Ugui
{
    [InitializeOnLoad]
    internal static class XUUnityLightMcpUguiModule
    {
        static XUUnityLightMcpUguiModule()
        {
            XUUnityLightMcpUiComponentReaderRegistry.Register(new XUUnityLightMcpUguiComponentReader());
            XUUnityLightMcpOperationRegistry.Register(new XUUnityLightMcpPrefabRenderOperation());
            XUUnityLightMcpOperationRegistry.Register(new XUUnityLightMcpUiClickOperation());
            XUUnityLightMcpCapabilityRegistry.RegisterProvider(
                XUUnityLightMcpCapabilityRegistry.UiRenderCapability,
                BuildRenderCapability);
            XUUnityLightMcpCapabilityRegistry.RegisterProvider(
                XUUnityLightMcpCapabilityRegistry.UiInteractionCapability,
                BuildInteractionCapability);
        }

        static XUUnityLightMcpCapabilityRecord BuildRenderCapability()
        {
            return new XUUnityLightMcpCapabilityRecord
            {
                capability_id = XUUnityLightMcpCapabilityRegistry.UiRenderCapability,
                adapter_id = "unity_ugui_preview_render_v1",
                supported = true,
                status = "supported",
                reason = "",
                dependency = "com.unity.ugui",
                operations = new List<string> { XUUnityLightMcpPrefabRenderOperation.RegisteredOperationName }
            };
        }

        static XUUnityLightMcpCapabilityRecord BuildInteractionCapability()
        {
            return new XUUnityLightMcpCapabilityRecord
            {
                capability_id = XUUnityLightMcpCapabilityRegistry.UiInteractionCapability,
                adapter_id = "unity_ugui_event_system_click_v1",
                supported = true,
                status = "supported",
                reason = "",
                dependency = "com.unity.ugui",
                operations = new List<string> { XUUnityLightMcpUiClickOperation.RegisteredOperationName }
            };
        }
    }
}
